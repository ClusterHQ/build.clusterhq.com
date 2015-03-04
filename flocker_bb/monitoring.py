
from twisted.application.internet import TimerService
from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.python import log

from buildbot.status.base import StatusReceiverMultiService
from buildbot.status.results import Results

from prometheus_client import Gauge, Counter


class Monitor(StatusReceiverMultiService):

    pending_counts_gauge = Gauge(
        'pending_builds_total',
        'Number of pending builds',
        labelnames=['builder'],
        namespace='buildbot',
    )

    building_counts_gauge = Gauge(
        'running_builds_total',
        'Number of running builds',
        labelnames=['builder', 'slave_class', 'slave_number'],
        namespace='buildbot',
    )

    build_counts = Counter(
        'finished_builds_total',
        'Number of finished builds',
        labelnames=['builder', 'slave_class', 'slave_number', 'result'],
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
        self.status.subscribe(self)

    @inlineCallbacks
    def count_pending_builds(self):
        from collections import Counter
        build_reqs = yield self.master.db.buildrequests.getBuildRequests(
            claimed=False)
        pending_counts = Counter([br['buildername'] for br in build_reqs])
        returnValue(pending_counts)

    @inlineCallbacks
    def metrics(self):
        pending_counts = yield self.count_pending_builds()
        for builder in self.master.botmaster.builders.keys():
            self.pending_counts_gauge.labels(builder).set(
                pending_counts[builder])

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

    def builderAdded(self, builderName, builder):
        """
        Notify this receiver of a new builder.

        :return StatusReceiver: An object that should get notified of events on
            the builder.
        """
        return self

    def buildStarted(self, builderName, build):
        """
        Notify this receiver that a build has started.

        Reports to github that a build has started, along with a link to the
        build.
        """
        slave_name, slave_number = build.getSlavename().rsplit('-', 1)
        self.building_counts_gauge.labels(
            builderName, slave_name, slave_number).inc()

    def buildFinished(self, builderName, build):
        """
        Notify this receiver that a build has started.

        Reports to github that a build has started, along with a link to the
        build.
        """
        slave_name, slave_number = build.getSlavename().rsplit('-', 1)
        self.building_counts_gauge.labels(
            builderName, slave_name, slave_number,
        ).dec()
        self.build_counts.labels(
            builderName, slave_name, slave_number, Results[build.getResults()],
        ).inc()
