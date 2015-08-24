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
	libffi-dev \
	build-essential \
	wget \
	curl \
	yum \
	libssl-dev \
	dpkg-dev \
	enchant

# Install whatever version is newest in the Docker repository.  If you wanted a
# different version, you should have run the script at a different time.  This
# happens to more or less match a suggestion we give our users for when they
# install Flocker.  See the install-node document for that.  Users could
# install Docker in other ways, though, for which we presently have no test
# coverage.
#
# XXX This is duplicated in the centos-7 script.  It's hard to share this code
# because this individual file gets uploaded to the node being initialized so
# it's not clear where shared "library" code might belong.
curl https://get.docker.com/ > /tmp/install-docker.sh
sh /tmp/install-docker.sh

# XXX Maybe also linux-source

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
