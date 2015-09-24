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
	rpmdevtools \
	rpmlint \
	rpm-build \
	libffi-devel \
	@buildsys-build \
	openssl-devel \
	wget \
	curl \
	enchant

wget https://bitbucket.org/squeaky/portable-pypy/downloads/pypy-2.6.1-linux_x86_64-portable.tar.bz2
tar xf pypy-2.6.1-linux_x86_64-portable.tar.bz2

curl https://bootstrap.pypa.io/get-pip.py | python -
# The version of virtualenv here should correspond to the version of 
# pip used by flocker. (See https://virtualenv.pypa.io/en/latest/changes.html to
# find which version of virtualenv corresponds to which version of pip).
pip install virtualenv==13.1.0 tox==2.1.1
pip install buildbot-slave==0.8.10

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
# different version, you should have run the script at a different time.  This
# happens to more or less match a suggestion we give our users for when they
# install Flocker.  See the install-node document for that.  Users could
# install Docker in other ways, though, for which we presently have no test
# coverage.
#
# XXX This is duplicated in the ubuntu-14.04 script.  It's hard to share this code
# because this individual file gets uploaded to the node being initialized so
# it's not clear where shared "library" code might belong.
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
