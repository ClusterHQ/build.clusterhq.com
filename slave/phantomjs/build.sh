#!/bin/sh

set -e

docker run --rm -v `pwd`:/docker fedora:20 /docker/docker-build.sh
