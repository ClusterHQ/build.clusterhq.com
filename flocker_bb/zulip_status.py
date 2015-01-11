# -*- test-case-name: flocker_bb.test.test_zulip_status -*-
# https://zulip.com/api/

from StringIO import StringIO
from urllib import urlencode
from base64 import b64encode

from twisted.python.log import msg, err
from twisted.web.http_headers import Headers
from twisted.web.client import FileBodyProducer, Agent, readBody

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


class _Zulip(object):
    _POST_HEADERS = Headers({
        b"content-type": [b"application/x-www-form-urlencoded"]})
    _MESSAGES = b"https://api.zulip.com/v1/messages"

    def __init__(self, bot, key, agent):
        """
        @param bot: The name of the zulip bot as which to authenticate.
        @type bot: L{bytes}

        @param key: The API key to use to authenticate.
        @type key: L{bytes}

        @param agent: An http agent to use to issue http requests to the zulip
            http API.
        @type agent: L{twisted.web.iweb.IAgent} provider
        """
        self.bot = bot
        self.key = key
        self.agent = agent
        self._headers = self._POST_HEADERS.copy()
        self._headers.setRawHeaders(
            b"authorization",
            [b"Basic " + b64encode(self.bot + b":" + self.key)])

    def send(self, type, content, to, subject):
        """
        Add a new message to a zulip stream.

        Unicode values are encoded to UTF-8.  Bytes values had better be UTF-8
        encoded.

        @param type: C{b"stream"} or C{b"private"} to add to a normal stream or
            a private conversation.
        @type type: L{bytes} or L{unicode}

        @param content: The content of the message to add.
        @type content: L{bytes} or L{unicode}

        @param to: The name of the stream or user the message is for.
        @type to: L{bytes} or L{unicode}

        @param subject: The subject of the message to send.
        @type subject: L{bytes} or L{unicode}

        """
        def encode(value):
            if isinstance(value, unicode):
                return value.encode("utf-8")
            if not isinstance(value, bytes):
                raise ValueError(
                    "_Zulip.send arguments must be bytes or unicode")
            return value

        body = urlencode([
            (b"type", encode(type)),
            (b"content", encode(content)),
            (b"to", encode(to)),
            (b"subject", encode(subject)),
        ])
        producer = FileBodyProducer(StringIO(body))
        msg(format="_Zulip.send requesting %(url)s with body %(body)s",
            url=self._MESSAGES, body=body)

        requesting = self.agent.request(
            b"POST", self._MESSAGES, self._headers, producer)

        def requested(response):
            msg(format="_Zulip.send received response, code = %(code)d",
                code=response.code)
            return readBody(response)
        requesting.addCallback(requested)
        return requesting


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


def createZulipStatus(reactor, bot, key, stream):
    agent = Agent(reactor)
    zulip = _Zulip(bot, key, agent)
    writer = _ZulipWriteOnlyStatus(zulip=zulip, stream=stream)
    status = BuildsetStatusReceiver(finished=writer.buildsetFinished)
    return status
