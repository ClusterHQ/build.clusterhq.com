#!/bin/sh

set -e

# This script is run as a libcloud ScriptDeployment.
# On fedora, this is run as the user fedora, so switch to root.
if [ -z "$SUDO_COMMAND" ]
then
      sudo $0 $*
      exit $?
fi


cat <<"EOF" >/etc/yum.repos.d/hybridlogic.repo
[hybridlogic]
name = Copr repo for hybridlogic
baseurl = http://copr-be.cloud.fedoraproject.org/results/tomprince/hybridlogic/fedora-$releasever-$basearch/
skip_if_unavailable = True
gpgcheck = 0
enabled = 1
EOF

# Install development headers for the currently running kernel.
cat <<"EOF" >/etc/sysconfig/kernel
UPDATEDEFAULT=yes
DEFAULTKERNEL=kernel
EOF

yum install -y http://archive.zfsonlinux.org/fedora/zfs-release$(rpm -E %dist).noarch.rpm
yum install -y https://storage.googleapis.com/archive.clusterhq.com/fedora/clusterhq-release$(rpm -E %dist).noarch.rpm

# Enable debugging for ZFS modules
echo SPL_DKMS_DISABLE_STRIP=y >> /etc/sysconfig/spl
echo ZFS_DKMS_DISABLE_STRIP=y >> /etc/sysconfig/zfs

yum upgrade -y
yum install -y \
	buildbot-slave \
	git \
	python-devel \
	python-tox \
	python-virtualenv \
	rpmdev \
	rpmlint \
	rpm-build \
	docker-io \
	geard \
	libffi-devel \
	@buildsys-build \
	kernel-headers \
	kernel-devel \
	openssl-devel \
	wget \
	curl \
	apt \
	dpkg \
	dpkg-dev \
	enchant

# Despite being a packaging tool, fpm isn't yet packaged for Fedora.
# See https://github.com/jordansissel/fpm/issues/611
sudo yum -y install ruby-devel
gem install fpm

systemctl enable docker
systemctl enable geard


# Pre-cache docker images
systemctl start docker
docker pull busybox:latest
docker pull openshift/busybox-http-app:latest
docker pull python:2.7-slim
# For omnibus builds
docker pull fedora:20
docker pull fedora:21
docker pull ubuntu:14.04
docker pull centos:centos7
