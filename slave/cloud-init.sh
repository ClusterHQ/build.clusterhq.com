#!/bin/bash
setenforce 0

if [[ "%(base)s" =~ (fedora|centos)-zfs-head ]]; then
   yum install -y --enablerepo=zfs-testing zfs
   systemctl restart zfs.target
fi

# Set umask, so mock can write rpms to dist directory
buildslave create-slave --umask 002 /srv/buildslave %(buildmaster_host)s:%(buildmaster_port)d '%(name)s' '%(password)s'

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
"""
EOF

# Set $HOME so that git has a config file to read.
export HOME=/srv/buildslave
echo "https://%(github_token)s:@github.com" >/srv/buildslave/.git-credentials

echo -e "repo_token: %(coveralls_token)s\nservice_name: buildbot" >/srv/buildslave/coveralls.yml

cp -r ~root/.pip $HOME/.pip

git config --global credential.helper "store"

# Set group so that mock can write rpms to dist directory.
twistd -d /srv/buildslave -g $SUDO_GID -y /srv/buildslave/buildbot.tac
