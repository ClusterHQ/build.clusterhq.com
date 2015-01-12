from twisted.internet import defer
from buildbot.process import metrics
from twisted.python import log


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


def apply_patches():
    from buildbot.process.buildrequestdistributor import (
        BuildRequestDistributor)
    BuildRequestDistributor._activityLoop = brd_activityLoop
