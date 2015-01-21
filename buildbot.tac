import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from flocker_bb.monkeypatch import apply_patches
apply_patches()

from flocker_bb.eliot import eliot_to_twisted_logging
eliot_to_twisted_logging()

from twisted.application import service
from buildbot.master import BuildMaster

# This is currently duplicated in flocker.bb.builders.maint
basedir = r'/srv/buildmaster/data'

# note: this line is matched against to check that this is a buildmaster
# directory; do not edit it.
application = service.Application('buildmaster')

from twisted.python.util import sibpath
configfile = sibpath(__file__, 'config.py')

from flocker_bb.upgrade import UpgradeService

master = BuildMaster(basedir, configfile)
UpgradeService(basedir, configfile, master).setServiceParent(application)
