
from twisted.application.internet import TimerService
from twisted.internet.defer import inlineCallbacks, returnValue

from buildbot.status.base import StatusReceiverMultiService
from buildbot.status.results import Results

from flocker_bb.steps import getBranchType
from flocker_bb.util import getBranch

from prometheus_client import Gauge, Counter, Histogram


class Monitor(StatusReceiverMultiService):

    pending_counts_gauge = Gauge(
        'pending_builds',
        'Number of pending builds',
        labelnames=['builder'],
        namespace='buildbot',
    )

    building_counts_gauge = Gauge(
        'running_builds',
        'Number of running builds',
        labelnames=['builder', 'slave_class', 'slave_number', 'branch_type'],
        namespace='buildbot',
    )

    build_counts = Counter(
        'finished_builds_total',
        'Number of finished builds',
        labelnames=[
            'builder', 'slave_class', 'slave_number', 'result', 'branch_type'],
        namespace='buildbot',
    )

    build_duration = Histogram(
        'build_duration_minutes',
        "Length of build.",
        labelnames=[
            'builder', 'slave_class', 'slave_number', 'result', 'branch_type'],
        namespace="buildbot",
        buckets=[1, 2, 3, 4, 5, 10, 15, 20, 25, 30, 35, 40, 45, 60])

    def __init__(self):
        StatusReceiverMultiService.__init__(self)
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
        slave_name, slave_number = build.getSlavename().rsplit('/', 1)
        branch_type = getBranchType(getBranch(build)).name
        self.building_counts_gauge.labels(
            builderName, slave_name, slave_number, branch_type).inc()

    def buildFinished(self, builderName, build, results):
        """
        Notify this receiver that a build has started.

        Reports to github that a build has started, along with a link to the
        build.
        """
        slave_name, slave_number = build.getSlavename().rsplit('/', 1)
        branch_type = getBranchType(getBranch(build)).name
        self.building_counts_gauge.labels(
            builderName, slave_name, slave_number, branch_type,
        ).dec()
        self.build_counts.labels(
            builderName, slave_name, slave_number, Results[build.getResults()],
            branch_type,
        ).inc()

        (start, end) = build.getTimes()
        self.build_duration.labels(
            builderName, slave_name, slave_number, Results[build.getResults()],
            branch_type,
        ).observe(
            (end-start)/60
        )
