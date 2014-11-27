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
	mock \
	docker.io \
	libffi-dev \
	build-essential \
	wget \
	curl \
	yum \
	dpkg-dev

# Maybe also linux-source

# Despite being a packaging tool, fpm isn't yet packaged for Fedora.
# See https://github.com/jordansissel/fpm/issues/611
sudo apt-get -y install ruby-dev
gem install fpm

# Pre-cache docker images
docker pull busybox
docker pull openshift/busybox-http-app

# Configure pip wheelhouse and cache
mkdir ~root/.pip
cat > ~root/.pip/pip.conf <<EOF
[global]
#find-links = https://s3-us-west-2.amazonaws.com/clusterhq-wheelhouse/fedora20-x86_64/index
find-links = file:///var/cache/wheelhouse
EOF
mkdir /var/cache/wheelhouse
#wget -r -nd -P /var/cache/wheelhouse https://s3-us-west-2.amazonaws.com/clusterhq-wheelhouse/fedora20-x86_64/index
