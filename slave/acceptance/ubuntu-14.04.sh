#!/bin/sh

set -e

# This script is run as a libcloud ScriptDeployment.
# On AWS, this is run as a non-root user, so switch to root.
if [ -z "$SUDO_COMMAND" ]
then
      sudo $0 $*
      exit $?
fi

export DEBIAN_FRONTEND=noninteractive
apt-get -y install apt-transport-https software-properties-common
add-apt-repository -y ppa:james-page/docker
apt-get -y install docker.io

docker pull postgres:latest
docker pull clusterhq/mongodb:latest
docker pull clusterhq/flask
docker pull clusterhq/flaskenv
docker pull busybox
