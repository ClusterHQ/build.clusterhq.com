In this directory, run ./build.sh

This script will start a Fedora 20 Docker image, fetch PhantomJS from Github,
build the source, and then build the RPM.  The RPM will be copied into this
directory.

Upload the RPM to a permanent web address, and set the URL in file
slave/vagrant/fabfile.py
