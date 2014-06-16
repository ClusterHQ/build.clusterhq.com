#!/bin/sh
setenforce 0
modprobe zfs

# Set umask, so mock can write rpms to dist directory
buildslave create-slave --umask 002 /srv/buildslave build.flocker.hybridcluster.net:9989 '%(name)s' '%(password)s'

# mock needs a unprivelged user to drop priveleges to.
useradd -d /srv/buildslave -g mock -r buildslave
export SUDO_UID=$(id -u buildslave)
export SUDO_GID=135 # mock


mkdir /srv/buildslave/.mock
cat <<"EOF" >/srv/buildslave/.mock/user.cfg
config_opts['yum.conf'] += """
[hybridlogic]
name = Copr repo for hybridlogic
baseurl = http://copr-be.cloud.fedoraproject.org/results/tomprince/hybridlogic/fedora-$releasever-$basearch/
skip_if_unavailable = True
gpgcheck = 0
enabled = 1

[zfs]
name=ZFS Fedora 20
failovermethod=priority
baseurl=http://data.hybridcluster.net/zfs-fedora20/
enabled=1
gpgcheck=0
metadata_expire=10
"""
EOF

# Set $HOME so that git has a config file to read.
export HOME=/srv/buildslave
echo "https://%(token)s:@github.com" >/srv/buildslave/.git-credentials

git config --global credential.helper "store"

# Set group so that mock can write rpms to dist directory.
twistd -d /srv/buildslave -g $SUDO_GID -y /srv/buildslave/buildbot.tac
