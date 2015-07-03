FROM fedora:22
RUN dnf upgrade -y && \
    dnf install -y python-devel python-pip gcc libffi-devel openssl-devel gmp-devel git s3cmd dpkg-dev createrepo_c && \
    dnf clean all

ADD requirements.txt /srv/buildmaster/
RUN ["pip", "install", "-r", "/srv/buildmaster/requirements.txt"]

ADD buildbot.tac /srv/buildmaster/
ADD public_html /srv/buildmaster/public_html
ADD templates /srv/buildmaster/templates/
ADD flocker_bb /srv/buildmaster/flocker_bb
ADD slave/cloud-init.sh /srv/buildmaster/slave/cloud-init.sh
ADD config.py /srv/buildmaster/

EXPOSE 80 9989
CMD ["twistd", "--syslog", "--prefix", "buildmaster", "--pidfile", "/var/run/buildbot.pid", "-ny", "/srv/buildmaster/buildbot.tac"]
WORKDIR /srv/buildmaster/data
VOLUME ["/srv/buildmaster/data"]
