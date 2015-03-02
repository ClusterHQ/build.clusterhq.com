# -*- test-case-name: flocker_bb.test.test_zulip_status -*-
# https://zulip.com/api/


from twisted.python.log import msg, err

from buildbot.status.results import (
    Results, EXCEPTION, FAILURE, RETRY, SUCCESS, WARNINGS)

from flocker_bb.buildset_status import BuildsetStatusReceiver

from characteristic import attributes, Attribute
from textwrap import dedent


RESULT_SYMBOLS = {
    SUCCESS: "white_check_mark",
    WARNINGS: "heavy_exclamation_mark",
    FAILURE: "x",
    EXCEPTION: "interrobang",
    RETRY: "repeat",
}


@attributes([
    'zulip', 'stream', 'critical_stream',
    Attribute('failing_builders', default_factory=frozenset),
])
class ZulipStatus(BuildsetStatusReceiver):
    """
    BuildBot status hook-up object.

    Add this as a status thing to buildbot and it will send updates to zulip.

    @ivar _builders: List of builders we are subscribed to.
    """
    def __init__(self):
        """
        @param zulip: A zulip client to use to send messages.
        @type zulip: L{_Zulip}

        @param stream: The stream build results should be reported to.
        @param critical_stream: The stream critical build failures should be
            reported to.
        @param failing_builderes: List of builders for which critical failures
            shouldn't be repotrted.
        """
        self._builders = []
        BuildsetStatusReceiver.__init__(
            self, finished=self.report_buildsetFinished)

    def builderAdded(self, builderName, builder):
        """
        Notify this receiver of a new builder.

        :return StatusReceiver: An object that should get notified of events on
            the builder.
        """
        return self

    @staticmethod
    def _simplifyBuilderName(name):
        name = name.rpartition('flocker-')[2]
        return name

    def _composeMessage(self, (sourceStamps, buildRequests), status):
        message = "**Build Complete**\n"
        subjects = []

        for sourceStamp in sourceStamps:
            template = u"%(codebase)s : %(branch)s"
            subjects += [template % sourceStamp]
            if sourceStamp['revision']:
                template += (u": [%(revision)s]"
                             u"(https://github.com/ClusterHQ/%(codebase)s/"
                             u"commit/%(revision)s)")
                message += template % sourceStamp + u"\n"

        success = []
        other = []
        for buildRequest in buildRequests:
            build = max(buildRequest['builds'],
                        key=lambda build: build['number'])
            builderName = self._simplifyBuilderName(build['builderName'])
            buildURL = status.getURLForBuild(
                build['builderName'], build['number'])

            if build['results'] == SUCCESS:
                template = u"[%(builderName)s](%(url)s)"
                success.append(template % {'builderName': builderName,
                                           "url": buildURL})
            else:
                template = (
                    u":%(result_symbol)s: build [#%(buildNumber)d](%(url)s) "
                    u"of %(builderName)s: %(text)s"
                )
                other.append(template % {
                    'buildNumber': build['number'],
                    'builderName': builderName,
                    'url': buildURL,
                    'result_symbol': RESULT_SYMBOLS[build['results']],
                    'result': Results[build['results']],
                    'text': u" ".join(build['text']),
                    })
        if success:
            message += u':%(result_symbol)s: %(builders)s\n' % {
                'result_symbol': RESULT_SYMBOLS[SUCCESS],
                'builders': u', '.join(success),
                }
        if other:
            message += u'\n'.join(other)

        return subjects, message

    def _sendMessage(self, (subjects, message), stream):
        """
        Announce completed builds.
        """
        # TODO Eventual goal is to have similar functionality to irc and email
        # status things.  Be able to announce only transitions, mainly.  Also,
        # do better than either of those: consider the branch being built when
        # deciding if there is a transition.  And put results for different
        # branches into different zulip subjects.  zulip is also pretty good at
        # rendering more information so we could probably include failure
        # results if we want.
        msg(format="_ZulipWriteOnlyStatus message = %(message)s",
            message=message)

        # For each source stamp we'll send a message to Zulip with that stamp's
        # project and branch as the subject.  This way the information will be
        # visible on each project/branch the build relates to.
        for subject in subjects:
            msg(format="ZulipStatus sending, "
                       "subject = %(subject)s, stream = %(stream)s",
                subject=subject, stream=stream)
            d = self.zulip.send(
                type=u"stream",
                content=message,
                to=stream,
                subject=subject)
            d.addErrback(err, "ZulipStatus send failed")

    def report_buildsetFinished(self, data, status):
        message = self._composeMessage(data, status)
        self._sendMessage(message, stream=self.stream)

    def buildFinished(self, builderName, build, results):
        """
        Notify this receiver that a build has finished.

        Reports to github that a build has finished, along with a link to the
        build, and the build result.
        """
        if build.getResults() in (SUCCESS, WARNINGS, RETRY):
            # Not failing.
            return

        sourceStamps = [ss.asDict() for ss in build.getSourceStamps()]

        subjects = []

        for sourceStamp in sourceStamps:
            if sourceStamp['branch'] == 'master':
                subjects.append("%(codebase)s %(branch)s is failing"
                                % sourceStamp)

        if not subjects:
            # Not on master
            return

        if (builderName in self.failing_builders
                and not build.getProperty("report-expected-failures")):
            # The failure is expected.
            return

        buildURL = self.parent.getURLForThing(build)

        message = dedent(
            """
            @engineering
            :fire: :fire: :fire:
            [Build #%(buildNumber)s](%(buildURL)s) of %(builderName)s: %(text)s
            :fire: :fire: :fire:
            """ % {
                'buildNumber': build.getNumber(),
                'buildURL': buildURL,
                'builderName': builderName,
                'text': u" ".join(build.getText()),
            })

        self._sendMessage((subjects, message), stream=self.critical_stream)


def createZulipStatus(zulip, stream, critical_stream, failing_builders):
    return ZulipStatus(
        zulip=zulip, stream=stream, critical_stream=critical_stream,
        failing_builders=failing_builders)
