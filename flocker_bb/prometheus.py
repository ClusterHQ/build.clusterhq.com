from prometheus_client import REGISTRY, generate_latest, CONTENT_TYPE_LATEST

from twisted.web.resource import Resource


class PrometheusMetrics(Resource):
    isLeaf = True

    def __init__(self, registry=REGISTRY):
        self.registry = registry

    def render_GET(self, request):
        request.setHeader('Content-Type', CONTENT_TYPE_LATEST.encode('ascii'))
        return generate_latest(self.registry).encode('ascii')
