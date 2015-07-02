from base64 import b64encode
from urllib import urlencode

from zope.interface import implementer
from zope.interface.verify import verifyClass

from twisted.trial.unittest import SynchronousTestCase
from twisted.web.iweb import IAgent, IResponse
from twisted.internet.defer import Deferred, succeed
from twisted.internet.interfaces import IPushProducer
from twisted.python.failure import Failure
from twisted.web.client import ResponseDone, FileBodyProducer
from twisted.web.http_headers import Headers

from ..zulip import _Zulip


@implementer(IResponse)
class MemoryResponse(object):
    def __init__(self, version, code, phrase, headers,
                 request, previousResponse, body):
        self.version = version
        self.code = code
        self.phrase = phrase
        self.headers = headers
        self.length = len(body)
        self.request = request
        self.setPreviousResponse(previousResponse)
        self._body = body

    def setPreviousResponse(self, previousResponse):
        self.previousResponse = previousResponse

    def deliverBody(self, protocol):
        protocol.makeConnection(_StubProducer())
        protocol.dataReceived(self._body)
        protocol.connectionLost(Failure(ResponseDone()))
verifyClass(IResponse, MemoryResponse)


@implementer(IPushProducer)
class _StubProducer(object):
    def pauseProducing(self):
        pass

    def resumeProducing(self):
        pass

    def stopProducing(self):
        pass
verifyClass(IPushProducer, _StubProducer)


def _consume(body):
    if not isinstance(body, FileBodyProducer):
        raise TypeError()
    return body._inputFile.read()


@implementer(IAgent)
class SpyAgent(object):
    def __init__(self, requestLog):
        self._requests = requestLog

    def request(self, method, url, headers=None, body=None):
        if body is not None:
            body = _consume(body)
        self._requests.append((method, url, headers, body))
        response = MemoryResponse(
            b"HTTP/1.1", 200, b"OK", Headers(), None, None, b"")
        return succeed(response)

verifyClass(IAgent, SpyAgent)


@implementer(IAgent)
class SlowAgent(object):
    def request(self, method, url, headers=None, body=None):
        return Deferred()

verifyClass(IAgent, SlowAgent)


class ZulipTests(SynchronousTestCase):
    def test_sendRequest(self):
        """
        L{_Zulip.send} issues a I{POST} request to the Zulip I{messages} API
        URL with a I{application/x-www-form-urlencoded} body encoding its
        parameters.
        """
        requestLog = []
        agent = SpyAgent(requestLog)

        bot = b"some test"
        key = b"abcdef1234"
        zulip = _Zulip(bot, key, agent)
        zulip.send(b"the type", b"the content", b"the to", b"the subject")
        self.assertEqual(
            [(b"POST", b"https://api.zulip.com/v1/messages",
              Headers({
                  b"content-type":
                      [b"application/x-www-form-urlencoded"],
                  b"authorization":
                      [b"Basic " + b64encode(bot + b":" + key)]}),
              b"type=the+type&content=the+content"
              b"&to=the+to&subject=the+subject",
              )],
            requestLog)

    def test_sendEncodes(self):
        """
        If called with unicode values, L{_Zulip.send} encodes them to UTF-8
        before encoding them into the request body.
        """
        requestLog = []
        agent = SpyAgent(requestLog)

        bot = b"some test"
        key = b"abcdef1234"
        zulip = _Zulip(bot, key, agent)
        type = u"\N{SNOWMAN} type"
        content = u"\N{ENVELOPE} content"
        to = u"\N{ROMAN NUMERAL FIFTY} to"
        subject = u"\N{AC CURRENT} subject"
        zulip.send(type, content, to, subject)
        self.assertEqual(
            [(b"POST", b"https://api.zulip.com/v1/messages",
              Headers({
                  b"content-type":
                      [b"application/x-www-form-urlencoded"],
                  b"authorization":
                      [b"Basic " + b64encode(bot + b":" + key)]}),
              urlencode([(b"type", type.encode("utf-8")),
                         (b"content", content.encode("utf-8")),
                         (b"to", to.encode("utf-8")),
                         (b"subject", subject.encode("utf-8"))]),
              )],
            requestLog)

    def test_sendResultBefore(self):
        """
        L{_Zulip.send} returns a L{Deferred} that does not fire before the
        underlying HTTP request has received a response.
        """
        agent = SlowAgent()
        zulip = _Zulip(b"some test", b"abcdef1234", agent)
        sending = zulip.send(
            b"the type", b"the content", b"the to", b"the subject")
        self.assertNoResult(sending)

    def test_sendResultAfter(self):
        """
        L{_Zulip.send} returns a L{Deferred} that fires with C{None} after the
        underlying HTTP request has received a response.
        """
        agent = SpyAgent([])
        zulip = _Zulip(b"some test", b"abcdef1234", agent)
        sending = zulip.send(
            b"the type", b"the content", b"the to", b"the subject")
        # SpyAgent always returns an empty response body
        self.assertEqual(b"", self.successResultOf(sending))
