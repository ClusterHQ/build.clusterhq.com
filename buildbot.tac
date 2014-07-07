import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from twisted.application import service
from buildbot.master import BuildMaster

basedir = r'/srv/buildmaster/data'

# note: this line is matched against to check that this is a buildmaster
# directory; do not edit it.
application = service.Application('buildmaster')

from twisted.python.util import sibpath
configfile = sibpath(__file__, 'config.py')

from flocker_bb.upgrade import UpgradeService

master = BuildMaster(basedir, configfile)
UpgradeService(basedir, configfile, master).setServiceParent(application)

from twisted.application.internet import TimerService
TimerService(30, master.botmaster.maybeStartBuildsForAllBuilders).setServiceParent(master)
