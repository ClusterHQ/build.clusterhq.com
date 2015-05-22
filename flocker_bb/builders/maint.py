import os
from buildbot.steps.master import MasterShellCommand
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
         '-exec', 'unlink', '{}', ';'],
        description=['Removing', 'old', 'results'],
        descriptionDone=['Remove', 'old', 'results'],
        name='remove-old-results'))

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
