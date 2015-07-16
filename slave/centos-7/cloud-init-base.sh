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
        python-tox \
        python-virtualenv \
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

# Restrict the size of the Docker loopback data device
cat <<EOF > /etc/sysconfig/docker-storage
DOCKER_STORAGE_OPTIONS="--storage-opt dm.loopdatasize=2G"
EOF

systemctl stop docker
rm -rf /var/lib/docker
systemctl start docker

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
docker pull python:2.7-slim


# Configure pip wheelhouse and cache
mkdir ~root/.pip
cat > ~root/.pip/pip.conf <<EOF
[global]
find-links = file:///var/cache/wheelhouse
EOF
