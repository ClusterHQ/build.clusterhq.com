#!/bin/sh
setenforce 0
modprobe zfs
buildslave create-slave /srv/buildslave build.flocker.hybridcluster.net:9989 '%(name)s' '%(password)s'
export HOME=/srv/buildslave
echo "https://%(token)s:@github.com" >/srv/buildslave/.git-credentials
git config --global credential.helper "store"
twistd -d /srv/buildslave -y /srv/buildslave/buildbot.tac
