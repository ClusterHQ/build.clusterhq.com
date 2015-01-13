from twisted.python.log import err
from twisted.internet.defer import gatherResults

from buildbot.status.base import StatusReceiverService


class BuildsetStatusReceiver(StatusReceiverService):
    """
    BuildBot status hook-up object.

    @ivar _builders: List of builders we are subscribed to.
    """
    def __init__(self, started=None, finished=None):
        """
        """
        self.started = started
        self.finished = finished
        self._builders = []


    def startService(self):
        StatusReceiverService.startService(self)
        self.status = self.parent
        self.master = self.status.master

        # Get builderAdded notification
        self.status.subscribe(self)


    def stopService(self):
        self.status.unsubscribe(self)
        for builder in self._builders:
            builder.unsubscribe(self)

        return StatusReceiverService.stopService(self)


    def _buildsetData(self, buildset):
        """
        @returns: L{tuple} of sourcestamp dicts and buildrequest dicts.
        """
        dl = []
        dl.append(self.master.db.sourcestamps.getSourceStamps(buildset.bsdict['sourcestampsetid']))
        dl.append(buildset.getBuilderNamesAndBuildRequests()
                .addCallback(lambda res: gatherResults([br.asDict_async() for br in res.values()])))
        return gatherResults(dl)


    def buildsetFinished(self, buildset):
        d = self._buildsetData(buildset)
        d.addCallback(self.finished, self.parent)
        d.addErrback(err, "BuildsetStatusReceiver.buildsetFinished")


    def buildsetSubmitted(self, buildset):
        if self.finished:
            buildset.waitUntilFinished().addCallback(self.buildsetFinished)
        if self.started:
            d = self._buildsetData(buildset)
            d.addCallback(self.started, self.parent)
            d.addErrback(err, "BuildsetStatusReceiver.buildsetStarted")
