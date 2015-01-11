from StringIO import StringIO
from urllib import urlencode
from base64 import b64encode
from twisted.web.client import FileBodyProducer, Agent, readBody
from twisted.web.http_headers import Headers

from twisted.python.log import msg


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


def createZulip(reactor, bot, key):
    agent = Agent(reactor)
    zulip = _Zulip(bot, key, agent)
    return zulip
