from collections import Counter

from twisted.application.internet import TimerService
from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.python import log

from buildbot.status.base import StatusReceiverMultiService

from prometheus_client import Gauge


class Monitor(StatusReceiverMultiService):

    pending_counts_gauge = Gauge(
        'pending_builds_total',
        'Number of pending builds',
        labelnames=['builder'],
        namespace='buildbot',
    )

    def __init__(self):
        StatusReceiverMultiService.__init__(self)
        timer = TimerService(60*60, self.report_pending_builds)
        timer.setServiceParent(self)

        timer = TimerService(30, self.metrics)
        timer.setServiceParent(self)

    def startService(self):
        self.status = self.parent
        self.master = self.status.master
        StatusReceiverMultiService.startService(self)

    @inlineCallbacks
    def count_pending_builds(self):
        build_reqs = yield self.master.db.buildrequests.getBuildRequests(
            claimed=False)
        pending_counts = Counter([br['buildername'] for br in build_reqs])
        returnValue(pending_counts)

    @inlineCallbacks
    def metrics(self):
        pending_counts = yield self.count_pending_builds()
        for builder, count in pending_counts.items():
            self.pending_counts_gauge.labels(builder).set(count)

    @inlineCallbacks
    def report_pending_builds(self):
        """
        If there are many pending builds, report them to zulip.
        """
        pending_counts = yield self.count_pending_builds()
        if pending_counts and max(pending_counts.values()) > 10:
            message = [
                "|Builder|Pending Builds",
                "|:-|-:|",
            ]
            message += ['|%s|%d|' % item for item in pending_counts.items()]
            log.msg('\n'.join(message),
                    zulip_subject="Too Many Pending Builds")
