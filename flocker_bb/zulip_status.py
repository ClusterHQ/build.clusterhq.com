# -*- test-case-name: flocker_bb.test.test_zulip_status -*-
# https://zulip.com/api/


from twisted.python.log import msg, err

from buildbot.status.results import (
    Results, EXCEPTION, FAILURE, RETRY, SUCCESS, WARNINGS)

from flocker_bb.buildset_status import BuildsetStatusReceiver

from characteristic import attributes


RESULT_SYMBOLS = {
    SUCCESS: "white_check_mark",
    WARNINGS: "heavy_exclamation_mark",
    FAILURE: "x",
    EXCEPTION: "interrobang",
    RETRY: "repeat",
}


@attributes(['zulip', 'stream'])
class _ZulipWriteOnlyStatus(object):
    """
    BuildBot status hook-up object.

    Add this as a status thing to buildbot and it will send updates to zulip.

    @ivar _builders: List of builders we are subscribed to.
    """
    def __init__(self):
        """
        @param zulip: A zulip client to use to send messages.
        @type zulip: L{_Zulip}
        """
        self._builders = []

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

    def _sendMessage(self, (subjects, message)):
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
            msg(format="_ZulipWriteOnlyStatus sending, subject = %(subject)s",
                subject=subject)
            d = self.zulip.send(
                type=u"stream",
                content=message,
                to=self.stream,
                subject=subject)
            d.addCallback(
                lambda ignored: msg("_ZulipWriteOnlyStatus send success"))
            d.addErrback(err, "_ZulipWriteOnlyStatus send failed")

    def buildsetFinished(self, data, status):
        message = self._composeMessage(data, status)
        self._sendMessage(message)


def createZulipStatus(zulip, stream):
    writer = _ZulipWriteOnlyStatus(zulip=zulip, stream=stream)
    status = BuildsetStatusReceiver(finished=writer.buildsetFinished)
    return status
