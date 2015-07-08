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
	git \
	python-dev \
	docker.io \
	libffi-dev \
	build-essential \
	wget \
	curl \
	yum \
	libssl-dev \
	dpkg-dev \
	enchant

curl https://bootstrap.pypa.io/get-pip.py | python -
pip install virtualenv==12.1.1 tox==2.1.1
pip install buildbot-slave==0.8.10

# Despite being a packaging tool, fpm isn't yet packaged for Fedora.
# See https://github.com/jordansissel/fpm/issues/611
sudo apt-get -y install ruby-dev
gem install fpm

# Pre-cache docker images
docker pull busybox:latest
docker pull openshift/busybox-http-app:latest
docker pull python:2.7-slim
