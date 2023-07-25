import os
import re
import math
import signal
import argparse
import datetime
import platform
import textwrap
import xml.etree.ElementTree as ET
from ftplib import FTP
from progressbar import ProgressBar, Bar, ETA, FileTransferSpeed, Percentage, DataSize

#Define constants
#Myrient FTP-server address
MYRIENTFTPADDR = 'ftp.myrient.erista.me'
#Catalog URLs, to find out the catalog in use from DAT
CATALOGURLS = {
    'https://www.no-intro.org': 'No-Intro',
    'http://redump.org/': 'Redump'
}
#Postfixes in DATs to strip away
DATPOSTFIXES = [
    ' (Retool)'
]

#Print output function
def logger(str, color=None, rewrite=False):
    colors = {'red': '\033[91m', 'green': '\033[92m', 'yellow': '\033[93m', 'cyan': '\033[96m'}
    if rewrite:
        print('\033[1A', end='\x1b[2K')
    if color:
        print(f'{datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")} | {colors[color]}{str}\033[00m')
    else:
        print(f'{datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")} | {str}')

#Input request function
def inputter(str, color=None):
    colors = {'red': '\033[91m', 'green': '\033[92m', 'yellow': '\033[93m', 'cyan': '\033[96m'}
    if color:
        val = input(f'{datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")} | {colors[color]}{str}\033[00m')
    else:
        val = input(f'{datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")} | {str}')
    return val

#Scale file size
def scale1024(val):
    prefixes=['', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB', 'EiB', 'ZiB', 'YiB']
    if val <= 0:
        power = 0
    else:
        power = min(int(math.log(val, 2) / 10), len(prefixes) - 1)
    scaled = float(val) / (2 ** (10 * power))
    unit = prefixes[power]
    return scaled, unit

#Exit handler function
def exithandler(signum, frame):
    logger('Exiting script!', 'red', True)
    exit()
signal.signal(signal.SIGINT, exithandler)

#Generate argument parser
parser = argparse.ArgumentParser(
    add_help=False,
    formatter_class=argparse.RawTextHelpFormatter,
    description=textwrap.dedent('''\
        \033[92mTool to automatically download ROMs of a DAT-file from Myrient.
        
        Generate a DAT-file with the tool of your choice to include ROMs that you
        want from a No-Intro/Redump/etc catalog, then use this tool to download
        the matching files from Myrient.\033[00m
    '''))

#Add required arguments
requiredargs = parser.add_argument_group('\033[91mRequired arguments\033[00m')
requiredargs.add_argument('-i', dest='inp', metavar='nointro.dat', help='Input DAT-file containing wanted ROMs', required=True)
requiredargs.add_argument('-o', dest='out', metavar='/data/roms', help='Output path for ROM files to be downloaded', required=True)
#Add optional arguments
optionalargs = parser.add_argument_group('\033[96mOptional arguments\033[00m')
optionalargs.add_argument('-c', dest='catalog', action='store_true', help='Choose catalog manually, even if automatically found')
optionalargs.add_argument('-s', dest='system', action='store_true', help='Choose system collection manually, even if automatically found')
optionalargs.add_argument('-l', dest='list', action='store_true', help='List only ROMs that are not found in FTP-server (if any)')
optionalargs.add_argument('-h', '--help', dest='help', action='help', help='Show this help message')
args = parser.parse_args()

#Init variables
catalog = None
collection = None
totaldlsize = 0
wantedroms = []
wantedfiles = []
missingroms = []
collectiondir = []
availableroms = {}
foundcollections = []

#Validate arguments
if not os.path.isfile(args.inp):
    logger('Invalid input DAT-file!', 'red')
    exit()
if not os.path.isdir(args.out):
    logger('Invalid output ROM path!', 'red')
    exit()
if platform.system() == 'Linux' and args.out[-1] == '/':
    args.out = args.out[:-1]
elif platform.system() == 'Windows' and args.out[-1] == '\\':
    args.out = args.out[:-1]

#Open input DAT-file
logger('Opening input DAT-file...', 'green')
datxml = ET.parse(args.inp)
datroot = datxml.getroot()

#Loop through ROMs in input DAT-file
for datchild in datroot:
    #Print out system information
    if datchild.tag == 'header':
        system = datchild.find('name').text
        for fix in DATPOSTFIXES:
            system = system.replace(fix, '')
        catalogurl = datchild.find('url').text
        if catalogurl in CATALOGURLS:
            catalog = CATALOGURLS[catalogurl]
            logger(f'Processing {catalog}: {system}...', 'green')
        else:
            logger(f'Processing {system}...', 'green')
    #Add found ROMs to wanted list
    elif datchild.tag == 'game':
        rom = datchild.find('rom')
        filename = rom.attrib['name']
        filename = re.sub(r'\.[(a-zA-Z0-9)]{1,3}\Z', '', filename)
        if filename not in wantedroms:
            wantedroms.append(filename)

#Connect to Myrient FTP
logger(f'Connecting to Myrient FTP-server...', 'green')
ftp = FTP(MYRIENTFTPADDR)
ftp.login()

#Get main directory and select wanted catalog
maindir = ftp.nlst()
if not catalog in maindir or args.catalog:
    logger('Catalog for DAT not automatically found, please select from the following:', 'yellow')
    dirnbr = 1
    for dir in maindir:
        logger(f'{str(dirnbr).ljust(2)}: {dir}', 'yellow')
        dirnbr += 1
    sel = inputter('Input selected catalog number: ', 'cyan')
    try:
        sel = int(sel)
        if sel > 0 and sel < dirnbr:
            catalog = maindir[sel-1]
        else:
            logger('Input number out of range!', 'red')
            exit()
    except:
        logger('Given input is not a number!', 'red')
        exit()

#Get catalog directory and select wanted collection
ftp.cwd(catalog)
contentdir = ftp.nlst()
for content in contentdir:
    if content.startswith(system):
        foundcollections.append(content)
if len(foundcollections) == 1:
    collection = foundcollections[0]
if not collection or args.system:
    logger('Collection for DAT not automatically found, please select from the following:', 'yellow')
    dirnbr = 1
    if len(foundcollections) > 1 and not args.system:
        for foundcollection in foundcollections:
            logger(f'{str(dirnbr).ljust(2)}: {foundcollection}', 'yellow')
            dirnbr += 1
    else:
        for dir in contentdir:
            logger(f'{str(dirnbr).ljust(2)}: {dir}', 'yellow')
            dirnbr += 1
    sel = inputter('Input selected collection number: ', 'cyan')
    try:
        sel = int(sel)
        if sel > 0 and sel < dirnbr:
            if len(foundcollections) > 1:
                collection = foundcollections[sel-1]
            else:
                collection = contentdir[sel-1]
        else:
            logger('Input number out of range!', 'red')
            exit()
    except:
        logger('Given input is not a number!', 'red')
        exit()

#Get collection directory contents and list contents to available ROMs
ftp.cwd(collection)
ftp.dir(collectiondir.append)
for line in collectiondir:
    file = re.findall('([0-9]{1,})[\s]{1,}[A-Za-z]{3,4}[\s]{1,}[0-9]{1,2}[\s]{1,}[0-9|:]{4,5}[\s]{1,}(.*?)\Z', line[28:].strip())
    filesize = file[0][0]
    filename = file[0][1]
    romname = re.sub(r'\.[(a-zA-Z0-9)]{1,3}\Z', '', filename)
    availableroms[romname] = {'name': romname, 'file': filename, 'size': filesize}

#Compare wanted ROMs and contents of the collection, parsing out only wanted files
for wantedrom in wantedroms:
    if wantedrom in availableroms:
        totaldlsize += int(availableroms[wantedrom]['size'])
        wantedfiles.append(availableroms[wantedrom])
    else:
        missingroms.append(wantedrom)

#Print out information about wanted/found/missing ROMs
wantedamt = len(wantedroms)
foundamt = len(wantedfiles)
totaldlsize, totaldlunit = scale1024(totaldlsize)
logger(f'Amount of wanted ROMs in DAT-file   : {wantedamt}', 'green')
logger(f'Amount of found ROMs at FTP-server  : {foundamt}', 'green')
logger(f'Amount of total data to download    : {round(totaldlsize, 2)} {totaldlunit}', 'green')
if missingroms:
    missingamt = len(missingroms)
    logger(f'Amount of missing ROMs at FTP-server: {missingamt}', 'yellow')

#Download wanted files
if not args.list:
    dlcounter = 0
    for wantedfile in wantedfiles:
        dlcounter += 1
        resumedl = False
        proceeddl = True

        if platform.system() == 'Linux':
            localpath = f'{args.out}/{wantedfile["file"]}'
        elif platform.system() == 'Windows':
            localpath = f'{args.out}\{wantedfile["file"]}'
        
        remotefilesize = int(wantedfile['size'])
        if os.path.isfile(localpath):
            localfilesize = int(os.path.getsize(localpath))
            if localfilesize != remotefilesize:
                resumedl = True
            else:
                proceeddl = False

        if proceeddl:
            file = open(localpath, 'ab')

            size, unit = scale1024(remotefilesize)
            pbar = ProgressBar(widgets=['\033[96m', Percentage(), ' | ', DataSize(), f' / {round(size, 1)} {unit}', ' ', Bar(marker='#'), ' ', ETA(), ' | ', FileTransferSpeed(), '\033[00m'], max_value=int(wantedfile['size']), redirect_stdout=True)
            pbar.start()

            def writefile(data):
                global pbar
                file.write(data)
                pbar += len(data)
            
            if resumedl:
                logger(f'Resuming    {str(dlcounter).zfill(len(str(foundamt)))}/{foundamt}: {wantedfile["name"]}', 'cyan')
                pbar += localfilesize
                ftp.retrbinary(f'RETR {wantedfile["file"]}', writefile, rest=localfilesize)
            else:
                logger(f'Downloading {str(dlcounter).zfill(len(str(foundamt)))}/{foundamt}: {wantedfile["name"]}', 'cyan')
                ftp.retrbinary(f'RETR {wantedfile["file"]}', writefile)

            file.close()
            pbar.finish()
            print('\033[1A', end='\x1b[2K')
            logger(f'Downloaded  {str(dlcounter).zfill(len(str(foundamt)))}/{foundamt}: {wantedfile["name"]}', 'green', True)
        else:
            logger(f'Skipping    {str(dlcounter).zfill(len(str(foundamt)))}/{foundamt}: {wantedfile["name"]}', 'green')
    logger('Downloading complete!', 'green', False)

#Output missing ROMs, if any
if missingroms:
    logger(f'Following {missingamt} ROMs in DAT not automatically found from FTP-server, grab these manually:', 'red')
    for missingrom in missingroms:
        logger(missingrom, 'yellow')
else:
    logger('All ROMs in DAT found from FTP-server!', 'green')
