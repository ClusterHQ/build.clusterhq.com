import os
from twisted.application import service
from twisted.python.filepath import FilePath
from buildslave.bot import BuildSlave

basedir = FilePath(__file__).parent()

# note: this line is matched against to check that this is a buildslave
# directory; do not edit it.
application = service.Application('buildslave')

githubToken = os.environ.pop('GITHUB_TOKEN')
basedir.child('git-credentials').setContent('https://%s:@github.com' % (githubToken,))

buildmaster_host = os.environ.pop('BUILDMASTER_PORT_9989_TCP_ADDR')
port = int(os.environ.pop('BUILDMASTER_PORT_9989_TCP_PORT'))
slavename = os.environ.pop('SLAVENAME')
passwd = os.environ.pop('SLAVEPASSWD')
keepalive = 600
usepty = False
umask = 0022
maxdelay = 300

s = BuildSlave(buildmaster_host, port, slavename, passwd, basedir.path,
               keepalive, usepty, umask=umask, maxdelay=maxdelay,
               allow_shutdown=False)
s.setServiceParent(application)
