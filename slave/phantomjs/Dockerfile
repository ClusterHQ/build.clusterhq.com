FROM fedora:20

RUN yum --assumeyes install \
	git \
	&& yum clean all

RUN git clone https://github.com/ariya/phantomjs.git

WORKDIR phantomjs

RUN yum --assumeyes install gcc gcc-c++ make flex bison gperf ruby \
  openssl-devel freetype-devel fontconfig-devel libicu-devel sqlite-devel \
  libpng-devel libjpeg-devel \
  && yum clean all

RUN git checkout 1.9

RUN ./build.sh --confirm

WORKDIR rpm

RUN yum --assumeyes install \
	rpm-build \
	&& yum clean all

RUN ./mkrpm.sh phantomjs
