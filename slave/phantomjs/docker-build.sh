#!/bin/sh

set -e -x

cd /tmp

yum --assumeyes install	git

git clone https://github.com/ariya/phantomjs.git

cd phantomjs

git checkout 1.9

yum --assumeyes install gcc gcc-c++ make flex bison gperf ruby \
  openssl-devel freetype-devel fontconfig-devel libicu-devel sqlite-devel \
  libpng-devel libjpeg-devel

./build.sh --confirm

cd rpm

yum --assumeyes install \
	rpm-build

# Script copies the built RPM to ${TMPDIR}, so set that to our desired destination
TMPDIR=/docker ./mkrpm.sh phantomjs
