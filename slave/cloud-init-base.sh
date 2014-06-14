#!/bin/sh

cat <<"EOF" >/etc/yum.repos.d/hybridlogic.repo
[hybridlogic]
name = Copr repo for hybridlogic
baseurl = http://copr-be.cloud.fedoraproject.org/results/tomprince/hybridlogic/fedora-$releasever-$basearch/
skip_if_unavailable = True
gpgcheck = 0
enabled = 1
EOF

cat <<"EOF" >/etc/yum.repos.d/zfs.repo
[zfs]
name=ZFS Fedora 20
failovermethod=priority
baseurl=http://data.hybridcluster.net/zfs-fedora20/
enabled=1
gpgcheck=0
metadata_expire=10
EOF

yum upgrade -y
yum install -y buildbot-slave git python-devel python-tox python-virtualenv mock rpmdev zfs rpm-build @buildsys-build
yum clean -y
