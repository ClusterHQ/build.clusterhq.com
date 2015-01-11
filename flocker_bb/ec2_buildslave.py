# Copied form e081bd2d0f4e959ad90be9f83a7bd5ce58001cee
# This file is part of Buildbot.  Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Portions Copyright Buildbot Team Members

from __future__ import with_statement
# Portions Copyright Canonical Ltd. 2009

"""A LatentSlave that uses EC2 to instantiate the slaves on demand.

Tested with Python boto 1.5c
"""

from twisted.application.internet import TimerService
from twisted.internet import defer
from twisted.internet import reactor

from buildbot.buildslave.base import BuildSlave

from flocker_bb.ec2 import EC2


class EC2BuildSlave(BuildSlave):

    instance = image = None
    _poll_resolution = 5  # hook point for tests

    build_wait_timer = None

    def __init__(self, name, password, instance_type, image_name,
                 identifier, secret_identifier,
                 user_data, region,
                 keypair_name, security_name,
                 max_builds=None, notify_on_missing=[],
                 missing_timeout=60 * 20,
                 build_wait_timeout=60 * 10, properties={}, locks=None,
                 keepalive_interval=None,
                 tags={}):

        BuildSlave.__init__(
            self, name, password, max_builds, notify_on_missing,
            missing_timeout, properties, locks)
        self.build_wait_timeout = build_wait_timeout
        # Uggh
        if keepalive_interval is not None:
            self.keepalive_interval = keepalive_interval

        self.building = set()

        self.ec2 = EC2(
            access_key=identifier,
            secret_access_token=secret_identifier,
            region=region,
            name=name,
            image_name=image_name,
            size=instance_type,
            keyname=keypair_name,
            security_groups=[security_name],
            userdata=user_data,
            metadata=tags,
        )

        self.addService(TimerService(60, self.periodic))

    def buildStarted(self, sb):
        self._clearBuildWaitTimer()
        self.building.add(sb.builder_name)

    def buildFinished(self, sb):
        BuildSlave.buildFinished(self, sb)

        self.building.discard(sb.builder_name)
        if not self.building:
            if self.build_wait_timeout == 0:
                self.ec2.stop()
            else:
                self._setBuildWaitTimer()

    def _clearBuildWaitTimer(self):
        if self.build_wait_timer is not None:
            if self.build_wait_timer.active():
                self.build_wait_timer.cancel()
            self.build_wait_timer = None

    def _setBuildWaitTimer(self):
        self._clearBuildWaitTimer()
        if self.build_wait_timeout <= 0:
            return
        self.build_wait_timer = reactor.callLater(
            self.build_wait_timeout, self.ec2.stop)

    def requestSubmitted(self, request):
        builder_names = [b.name for b in
                         self.botmaster.getBuildersForSlave(self.slavename)]
        if request['buildername'] in builder_names:
            self.ec2.start()

    def startService(self):
        BuildSlave.startService(self)

        self._shutdown_callback_handle = reactor.addSystemEventTrigger(
            'before', 'shutdown', self.ec2.stop)

        self.master.subscribeToBuildRequests(self.requestSubmitted)

    @defer.inlineCallbacks
    def periodic(self):
        build_reqs = yield self.master.db.buildrequests.getBuildRequests(
            claimed=False)
        pending_builders = set([
            br['buildername'] for br in build_reqs])
        our_builders = set([
            b.name for b in
            self.botmaster.getBuildersForSlave(self.slavename)])
        if pending_builders & our_builders:
            self.ec2.start()
