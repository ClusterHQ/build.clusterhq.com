from __future__ import absolute_import
from twisted.python import log
from eliot import add_destination
import json


def _destination(message):
    """
    Log ``message`` to twisted's log.
    """
    log.msg(json.dumps(message))


def eliot_to_twisted_logging():
    """
    Ship eliot logs to twisted.
    """
    add_destination(_destination)
