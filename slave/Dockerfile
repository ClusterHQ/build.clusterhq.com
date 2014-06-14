FROM          ubuntu:trusty

WORKDIR /srv/buildslave

RUN apt-get update
RUN apt-get install -y buildbot-slave python2.7-dev python-virtualenv git dh-virtualenv debhelper
RUN ["git", "config", "--global", "credential.helper", "store --file=/srv/buildslave/git-credentials"]

ADD buildbot.tac /srv/buildslave/
CMD ["twistd", "-ny", "/srv/buildslave/buildbot.tac"]
