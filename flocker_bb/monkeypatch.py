from twisted.internet import defer
from buildbot.process import metrics
from twisted.python import log
from twisted.internet import reactor


@defer.inlineCallbacks
def brd_activityLoop(self):
    self.active = True

    timer = metrics.Timer('BuildRequestDistributor._activityLoop()')
    timer.start()

    while True:
        yield self.activity_lock.acquire()

        # lock pending_builders, pop an element from it, and release
        yield self.pending_builders_lock.acquire()

        # bail out if we shouldn't keep looping
        if not self.running or not self._pending_builders:
            self.pending_builders_lock.release()
            self.activity_lock.release()
            break

        bldr_name = self._pending_builders.pop(0)
        self.pending_builders_lock.release()

        # get the actual builder object
        bldr = self.botmaster.builders.get(bldr_name)
        if bldr:
            d = self._maybeStartBuildsOnBuilder(bldr)
            self._pendingMSBOCalls.append(d)
            d.addErrback(
                log.err,
                "from maybeStartBuild for builder '%s'" % (bldr_name,))
            d.addCallback(lambda _, d=d: self._pendingMSBOCalls.remove(d))

        self.activity_lock.release()

    timer.stop()

    self.active = False
    self._quiet()


def botmaster_maybeStartBuildsForSlave(self, slave_name):
    """
    We delay this for 10 seconds, so that if multiple slaves start at the same
    time, builds will be distributed between them.
    """
    def do_start():
        log.msg(format="Really starting builds on %(slave_name)s",
                slave_name=slave_name)
        builders = self.getBuildersForSlave(slave_name)
        self.brd.maybeStartBuildsOn([b.name for b in builders])
    log.msg(format="Waiting to start builds on %(slave_name)s",
            slave_name=slave_name)
    reactor.callLater(10, do_start)


from buildbot.process.slavebuilder import AbstractSlaveBuilder


def slavebuilder_buildStarted(self):
    AbstractSlaveBuilder.buildStarted(self)
    if self.slave and hasattr(self.slave, 'buildStarted'):
        self.slave.buildStarted(self)


from buildbot.process.buildrequestdistributor import BasicBuildChooser


class NoFallBackBuildChooser(BasicBuildChooser):
    """
    BuildChooser that doesn't fall back to rejected slaves.
    In particular, builds with locks won't be assigned before a lock is ready.
    """

    def __init__(self, bldr, master):
        BasicBuildChooser.__init__(self, bldr, master)
        self.rejectedSlaves = None


def apply_patches():
    log.msg("Apply flocker_bb.monkeypatch.")
    from buildbot.process.buildrequestdistributor import (
        BuildRequestDistributor)
    BuildRequestDistributor._activityLoop = brd_activityLoop
    from buildbot.process.botmaster import BotMaster
    BotMaster.maybeStartBuildsForSlave = botmaster_maybeStartBuildsForSlave
    from buildbot.process.slavebuilder import SlaveBuilder
    SlaveBuilder.buildStarted = slavebuilder_buildStarted
    from buildbot.process.buildrequestdistributor import (
        BuildRequestDistributor)
    BuildRequestDistributor.BuildChooser = NoFallBackBuildChooser
