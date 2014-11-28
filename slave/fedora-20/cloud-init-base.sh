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
	mock \
	rpmdev \
	rpmlint \
	rpm-build \
	docker-io \
	geard \
	libffi-devel \
	@buildsys-build \
	kernel-headers \
	kernel-devel \
	wget \
	curl \
	apt \
	dpkg \
	dpkg-dev

# Despite being a packaging tool, fpm isn't yet packaged for Fedora.
# See https://github.com/jordansissel/fpm/issues/611
sudo yum -y install ruby-devel
gem install fpm

systemctl enable docker
systemctl enable geard


# Initialize mock yum cache
# Otherwise, all these packages would need to downloaded on each latent slave.
export SUDO_UID=99 # nobody
export SUDO_GID=135 # mock
mock --init --root fedora-20-x86_64

# Pre-cache docker images
systemctl start docker
docker pull busybox
docker pull openshift/busybox-http-app


# Configure pip wheelhouse and cache
mkdir ~root/.pip
cat > ~root/.pip/pip.conf <<EOF
[global]
find-links = https://s3-us-west-2.amazonaws.com/clusterhq-wheelhouse/fedora20-x86_64/index
find-links = file:///var/cache/wheelhouse
EOF
mkdir /var/cache/wheelhouse
wget -r -nd -P /var/cache/wheelhouse https://s3-us-west-2.amazonaws.com/clusterhq-wheelhouse/fedora20-x86_64/index
