#!/bin/sh

set -e

# This script is run as a libcloud ScriptDeployment.
# On fedora, this is run as the user fedora, so switch to root.
if [ -z "$SUDO_COMMAND" ]
then
      sudo $0 $*
      exit $?
fi

yum install -y kernel-devel-$(uname -r)

yum install -y http://archive.zfsonlinux.org/epel/zfs-release.el7.noarch.rpm

# Enable debugging for ZFS modules
echo SPL_DKMS_DISABLE_STRIP=y >> /etc/sysconfig/spl
echo ZFS_DKMS_DISABLE_STRIP=y >> /etc/sysconfig/zfs

yum upgrade -y
yum install -y epel-release
yum install -y \
	git \
	python-devel \
	python-tox \
	python-virtualenv \
	mock \
	rpmdevtools \
	rpmlint \
	rpm-build \
	docker-io \
	libffi-devel \
	@buildsys-build \
	kernel-headers \
	kernel-devel \
	openssl-devel \
	wget \
	curl \
	enchant

yum -y install python-pip
pip install buildbot-slave

# Despite being a packaging tool, fpm isn't yet packaged for Fedora.
# See https://github.com/jordansissel/fpm/issues/611
yum -y install ruby-devel
gem install fpm

systemctl enable docker

# Pre-cache docker images
systemctl start docker
docker pull busybox
docker pull openshift/busybox-http-app


# Configure pip wheelhouse and cache
mkdir ~root/.pip
cat > ~root/.pip/pip.conf <<EOF
[global]
find-links = file:///var/cache/wheelhouse
EOF
