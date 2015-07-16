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

# Restrict the size of the Docker loopback data device
# A 1G device allowed 723 stopped containers on Ubuntu 14.04 with Docker 1.3.3

# root@ip-172-31-10-80:~# docker version
# Client version: 1.3.3
# Client API version: 1.15
# Go version (client): go1.2.1
# Git commit (client): d344625
# OS/Arch (client): linux/amd64
# Server version: 1.3.3
# Server API version: 1.15
# Go version (server): go1.2.1
# Git commit (server): d344625

# i=0; while true; do echo "COUNT=$((i++))"; container_id=$(docker run --detach openshift/busybox-http-app);  docker stop $container_id; docker wait $container_id; ls -lsh /var/lib/docker/devicemapper/devicemapper/; done
# ...
# COUNT=721
# ff49d920e7be0c5dd4fedc3014a7b8fe70a86e794bed9322dad285acdf940364
# 143
# total 1.1G
# 1022M -rw------- 1 root root 1.0G Jul 16 16:54 data
#   29M -rw------- 1 root root 2.0G Jul 16 16:54 metadata
# COUNT=722

# ^C^Ctotal 1.1G
# 1023M -rw------- 1 root root 1.0G Jul 16 16:54 data
#   30M -rw------- 1 root root 2.0G Jul 16 16:54 metadata
# COUNT=723

# dmesg
# ...
# [ 7463.263003] device-mapper: thin: 252:4: no free data space available.

# Then an attempt to stop the docker daemon hangs and leaves a zombie process
# root@ip-172-31-10-80:~# ps ax | grep docker
#  4640 pts/1    S+     0:00 grep --color=auto docker
# 11243 ?        Zsl    0:25 [docker.io] <defunct>

# And the devicemapper files can't be removed.
# root@ip-172-31-10-80:~# rm -rf /var/lib/docker/
# rm: cannot remove ‘/var/lib/docker/devicemapper’: Device or resource busy
cat <<EOF > /etc/default/docker.io
DOCKER_OPTS="--storage-opt dm.loopdatasize=2G"
EOF

# After reconfiguring Docker storage we need to remove the existing files and
# restart the daemon.
service docker.io stop
rm -rf /var/lib/docker
service docker.io start

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
