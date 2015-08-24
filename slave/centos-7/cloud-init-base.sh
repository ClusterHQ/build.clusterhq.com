#!/bin/sh

#
# Initialize a cloud instance with the software required to use the instance as
# a BuildBot slave.  This is invoked the build-images script.  If versions of
# software are installed which eventually become outdated, they will continue
# to be used until the script is re-run.
#

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
	libffi-devel \
	@buildsys-build \
	openssl-devel \
	wget \
	curl \
	enchant

# Raise the startup timeout for the Docker service.  On the first start, it
# does some initialization work that can be quite time consuming.  The default
# timeout tends to be too short, startup fails, and the service is marked as
# failed.  This larger timeout was selected based on observation of how long
# the initialization seems to take on some arbitrarily selected systems.
#
# This comes before installation of Docker because the installation includes
# a step to enable and start Docker.
mkdir -p /etc/systemd/system/docker.service.d
cat >/etc/systemd/system/docker.service.d/01-TimeoutStartSec.conf <<EOF
[Service]
TimeoutStartSec=10min
EOF

# Install whatever version is newest in the Docker repository.  If you wanted a
# different version, you should have run the script at a different time.
curl https://get.docker.com/ > /tmp/install-docker.sh
sh /tmp/install-docker.sh

# Get the build slave dependencies.
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
