#!/bin/bash
setenforce 0

if [[ "%(base)s" =~ (fedora-20|centos-7)/zfs-head ]]; then
   yum install -y --enablerepo=zfs-testing zfs
   systemctl restart zfs.target
fi

# We set umask so that package builds get the right permissions. (Lintian will catch us if we get it wrong).
buildslave create-slave --umask 022 /srv/buildslave %(buildmaster_host)s:%(buildmaster_port)d '%(name)s' '%(password)s'

# Set $HOME so that git has a config file to read.
export HOME=/srv/buildslave
echo "https://%(github_token)s:@github.com" >/srv/buildslave/.git-credentials

cp -r ~root/.pip $HOME/.pip

git config --global credential.helper "store"

cat <<"EOF" > $HOME/acceptance.yml
%(acceptance.yml)s
EOF
export FLOCKER_FUNCTIONAL_TEST_CLOUD_CONFIG_FILE=$HOME/acceptance.yml
export FLOCKER_FUNCTIONAL_TEST_CLOUD_PROVIDER=%(FLOCKER_FUNCTIONAL_TEST_CLOUD_PROVIDER)s

case "${FLOCKER_FUNCTIONAL_TEST_CLOUD_PROVIDER}" in
    aws)
        export FLOCKER_FUNCTIONAL_TEST_AWS_AVAILABILITY_ZONE="$(curl -s http://169.254.169.254/latest/meta-data/placement/availability-zone)"
        ;;

    openstack)
        export FLOCKER_FUNCTIONAL_TEST_OPENSTACK_REGION="$(xenstore-read vm-data/provider_data/region)"
        ;;
esac

touch /root/.ssh/known_hosts
cat <<"EOF"  > /root/.ssh/id_rsa
%(acceptance-ssh-key)s
EOF
chmod -R 0600 /root/.ssh

#GAH
mkdir /srv/buildslave/.ssh
ssh-keygen -N '' -f $HOME/.ssh/id_rsa_flocker

eval $(ssh-agent -s)
ssh-add /root/.ssh/id_rsa

twistd -d /srv/buildslave -y /srv/buildslave/buildbot.tac
