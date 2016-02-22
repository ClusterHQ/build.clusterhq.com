import os

from buildbot.steps.master import MasterShellCommand
from buildbot.steps.shell import ShellCommand
from buildbot.config import BuilderConfig
from buildbot.process.factory import BuildFactory
from buildbot.schedulers.timed import Periodic


def makeCleanOldBuildsFactory():
    """
    Remove build results older than 14 days.
    """
    # FIXME we shouldn't hard code this (DRY)
    basedir = r'/srv/buildmaster/data'
    path = os.path.join(basedir, "private_html")

    factory = BuildFactory()
    factory.addStep(MasterShellCommand(
        ['find', path,
         '-type', 'f', '-mtime', '+14',
         '-exec', 'unlink', '{}', ';', '-print'],
        description=['Removing', 'old', 'results'],
        descriptionDone=['Remove', 'old', 'results'],
        name='remove-old-results'))

    # Vagrant tutorial boxes are created on the Vagrant slave, and
    # uploaded to S3.  However, the boxes must be kept on the slave
    # for running subsequent tests
    # (flocker/acceptance/vagrant/centos-7/zfs and
    # flocker/installed-package/vagrant/centos-7). This means there is
    # not an obvious place to remove the boxes.  So, we periodically
    # cleanup old boxes here. "Old" is the number of days passed as
    # parameter to script.
    factory.addStep(ShellCommand(
        command=['python', '/home/buildslave/remove-old-boxes.py', '14'],
        description=['Removing', 'old', 'boxes'],
        descriptionDone=['Remove', 'old', 'boxes'],
        name='remove-old-boxes'))

    return factory


def getBuilders(slavenames):
    return [
        BuilderConfig(
            name='clean-old-builds',
            # These slaves are dedicated slaves.
            slavenames=slavenames['fedora-20/vagrant'],
            factory=makeCleanOldBuildsFactory()),
    ]


def getSchedulers():
    daily = Periodic(name='daily',
                     builderNames=['clean-old-builds'],
                     periodicBuildTimer=24*3600)
    # This is so the zulip reporter gives better message.
    daily.codebases = {'maint': {'branch': 'daily'}}

    return [daily]
