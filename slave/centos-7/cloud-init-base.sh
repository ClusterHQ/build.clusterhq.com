#!/bin/sh

set -e

# This script is run as a libcloud ScriptDeployment.
# On fedora, this is run as the user fedora, so switch to root.
if [ -z "$SUDO_COMMAND" ]
then
      sudo $0 $*
      exit $?
fi

yum install -y http://archive.zfsonlinux.org/epel/zfs-release.el7.noarch.rpm

# For updated kernel (?)
yum install -y kernel-devel kernel

# For dkms and ... ?
yum install -y epel-release

# Enable debugging for ZFS modules
echo SPL_DKMS_DISABLE_STRIP=y >> /etc/sysconfig/spl
echo ZFS_DKMS_DISABLE_STRIP=y >> /etc/sysconfig/zfs

yum upgrade -y
yum install -y \
	git \
	python-devel \
	rpmdevtools \
	rpmlint \
	rpm-build \
	docker-io \
	libffi-devel \
	@buildsys-build \
	openssl-devel \
	wget \
	curl \
	enchant

curl https://bootstrap.pypa.io/get-pip.py | python -
pip install virtualenv==13.1.0 tox==2.1.1
pip install buildbot-slave==0.8.10

# Despite being a packaging tool, fpm isn't yet packaged for Fedora.
# See https://github.com/jordansissel/fpm/issues/611
yum -y install ruby-devel
gem install fpm

systemctl enable docker

# Pre-cache docker images
systemctl start docker
docker pull busybox
docker pull openshift/busybox-http-app
docker pull python:2.7-slim
