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
yum install -y \
	buildbot-slave \
	git \
	python-devel \
	python-tox \
	python-virtualenv \
	mock \
	rpmdev \
	rpmlint \
	zfs \
	rpm-build \
	docker-io \
	geard \
	@buildsys-build
yum clean -y all

systemctl enable docker


# Initialize mock yum cache
# Otherwise, all these packages would need to downloaded on each latent slave.
export SUDO_UID=99 # nobody
export SUDO_GID=135 # mock
mock --init --root fedora-20-x86_64
