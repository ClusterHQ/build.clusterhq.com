#!/usr/bin/python
"""
Small Python script to fetch a large number of files with a glob and tar them
to the standard output.
"""

import glob
import tarfile
import sys
import os

os.chdir(sys.argv[1])
tar = tarfile.open(fileobj=sys.stdout, mode='w|gz')

files = []
for pattern in file('/data/globber-files').readlines():
        files += glob.glob(pattern.strip())

for filename in files:
    try:
        tar.add(filename)
    except:
        sys.stderr.write(pattern.strip() + ' not found, going on.\n')
tar.close()
