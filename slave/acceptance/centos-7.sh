#!/bin/sh

set -e

# This script is run as a libcloud ScriptDeployment.
# On AWS, this is run as a non-root user, so switch to root.
if [ -z "$SUDO_COMMAND" ]
then
      sudo $0 $*
      exit $?
fi

yum install -y docker
systemctl enable docker
systemctl start docker
docker pull postgres:latest
docker pull clusterhq/mongodb:latest
docker pull clusterhq/flask:latest
docker pull clusterhq/flaskenv:latest
docker pull busybox:latest
