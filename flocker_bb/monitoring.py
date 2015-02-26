from collections import Counter

from twisted.application.internet import TimerService
from twisted.internet.defer import inlineCallbacks
from twisted.python import log

from buildbot.status.base import StatusReceiverMultiService


class Monitor(StatusReceiverMultiService):

    def __init__(self):
        StatusReceiverMultiService.__init__(self)
        timer = TimerService(60*60, self.report_pending_builds)
        timer.setServiceParent(self)

    def startService(self):
        self.status = self.parent
        self.master = self.status.master
        StatusReceiverMultiService.startService(self)

    @inlineCallbacks
    def report_pending_builds(self):
        """
        If there are many pending builds, report them to zulip.
        """
        build_reqs = yield self.master.db.buildrequests.getBuildRequests(
            claimed=False)
        pending_counts = Counter([br['buildername'] for br in build_reqs])
        if pending_counts and max(pending_counts.values()) > 10:
            message = [
                "|Builder|Pending Builds",
                "|:-|-:|",
            ]
            message += ['|%s|%d|' % item for item in pending_counts.items()]
            log.msg('\n'.join(message),
                    zulip_subject="Too Many Pending Builds")
