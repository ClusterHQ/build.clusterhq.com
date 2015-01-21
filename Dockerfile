FROM fedora:20
#ADD https://copr.fedoraproject.org/coprs/tomprince/hybridlogic/repo/fedora-20-x86_64/tomprince-hybridlogic-fedora-20-x86_64.repo /etc/yum.repos.d/
ADD tomprince-hybridlogic-fedora-20-x86_64.repo /etc/yum.repos.d/
#RUN yum upgrade -y
RUN yum install -y python-devel python-pip gcc libffi-devel openssl-devel git
RUN ["pip", "install", "buildbot==0.8.9", "txgithub==15.0.0", "eliot", "apache-libcloud", "service_identity", "git+https://github.com/ClusterHQ/machinist@fd749b6e03ba1856b12378dc366fc05d4e0578cc#egg-name=machinist"]

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
