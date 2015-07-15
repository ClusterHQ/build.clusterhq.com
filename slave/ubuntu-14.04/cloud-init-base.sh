#!/bin/sh

set -e

# This script is run as a libcloud ScriptDeployment.
# On fedora, this is run as the user fedora, so switch to root.
if [ -z "$SUDO_COMMAND" ]
then
      sudo $0 $*
      exit $?
fi


add-apt-repository -y ppa:zfs-native/stable

# Updated docker version. See
# - https://bugs.launchpad.net/ubuntu/+source/docker.io/+bug/1396572
# - https://launchpad.net/~james-page/+archive/ubuntu/docker
add-apt-repository -y ppa:james-page/docker

# FLOC-2659 we're installing an old version of Docker, but I won't do anything about that here.
# It's been suggested elsewhere that we upgrade to a newer version of Docker
# (FLOC-1057, FLOC-2524, FLOC-2447)

# Enable debugging for ZFS modules
echo SPL_DKMS_DISABLE_STRIP=y >> /etc/default/spl
echo ZFS_DKMS_DISABLE_STRIP=y >> /etc/default/zfs

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get -y upgrade
apt-get install -y \
        buildbot-slave \
        git \
        python-dev \
        python-tox \
        python-virtualenv \
        docker.io \
        libffi-dev \
        build-essential \
        wget \
        curl \
        yum \
        libssl-dev \
        dpkg-dev \
        enchant

# FLOC-2659 After installing docker.io, I'll need to modify its configuration file.

# The configuration file to modify is:
# ```
# root@acceptance-test-richardw-0:~# cat /etc/default/docker.io
# # Docker Upstart and SysVinit configuration file

# # Customize location of Docker binary (especially for development testing).
# #DOCKER="/usr/local/bin/docker"

# # Use DOCKER_OPTS to modify the daemon startup options.
# #DOCKER_OPTS="--dns 8.8.8.8 --dns 8.8.4.4"

# # If you need Docker to use an HTTP proxy, it can also be specified here.
# #export http_proxy="http://127.0.0.1:3128/"

# # This is also a handy place to tweak where Docker's temporary files go.
# #export TMPDIR="/mnt/bigdrive/docker-tmp"
# ```

# And we need to add the following parameters to start docker with a smaller loop back filesystem:
# https://clusterhq.atlassian.net/browse/FLOC-2628?focusedCommentId=18912&page=com.atlassian.jira.plugin.system.issuetabpanels:comment-tabpanel#comment-18912
# ```
#  --storage-opt dm.loopdatasize=1G --storage-opt dm.basesize=1G
# ```
# ... one which won't grow larger than the root filesystem

# The default configuration of Docker on our Ubuntu  build slave is
# ```
# root@ip-172-31-39-9:~# docker info
# Containers: 1
# Images: 87
# Storage Driver: devicemapper
#  Pool Name: docker-202:1-273582-pool
#  Pool Blocksize: 65.54 kB
#  Data file: /var/lib/docker/devicemapper/devicemapper/data
#  Metadata file: /var/lib/docker/devicemapper/devicemapper/metadata
#  Data Space Used: 5.016 GB
#  Data Space Total: 107.4 GB
#  Metadata Space Used: 5.915 MB
#  Metadata Space Total: 2.147 GB
#  Library Version: 1.02.77 (2012-10-15)
# ```

# And on acceptance nodes it's slightly different, but probably less important
# since the nodes are only used for a single test run:

# ```
# root@acceptance-test-richardw-0:~# docker info
# Containers: 0
# Images: 6
# Storage Driver: aufs
#  Root Dir: /var/lib/docker/aufs
#  Dirs: 6
# Execution Driver: native-0.2
# Kernel Version: 3.13.0-55-generic
# Operating System: Ubuntu 14.04.2 LTS
# ```

# After reconfiguring docker, we'll need to:
#  * stop it,
#  * remove the existing /var/lib/docker directory
#  * restart it


# Maybe also linux-source

# Despite being a packaging tool, fpm isn't yet packaged for Fedora.
# See https://github.com/jordansissel/fpm/issues/611
sudo apt-get -y install ruby-dev
gem install fpm

# Pre-cache docker images
docker pull busybox:latest
docker pull openshift/busybox-http-app:latest
docker pull python:2.7-slim

# Configure pip wheelhouse and cache
mkdir ~root/.pip
cat > ~root/.pip/pip.conf <<EOF
[global]
find-links = file:///var/cache/wheelhouse
EOF
mkdir /var/cache/wheelhouse
