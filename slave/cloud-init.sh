#!/bin/bash
setenforce 0

if [[ "%(base)s" =~ (fedora|centos)-zfs-head ]]; then
   yum install -y --enablerepo=zfs-testing zfs
   systemctl restart zfs.target
fi

buildslave create-slave /srv/buildslave %(buildmaster_host)s:%(buildmaster_port)d '%(name)s' '%(password)s'

# Set $HOME so that git has a config file to read.
export HOME=/srv/buildslave
echo "https://%(github_token)s:@github.com" >/srv/buildslave/.git-credentials

echo -e "repo_token: %(coveralls_token)s\nservice_name: buildbot" >/srv/buildslave/coveralls.yml

cp -r ~root/.pip $HOME/.pip

git config --global credential.helper "store"

twistd -d /srv/buildslave -y /srv/buildslave/buildbot.tac
