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
# Portions Copyright Canonical Ltd. 2009

from __future__ import with_statement

"""
Fake latent slave implementation for AWS EC2.

Buiildbot's latent slave implementation has some issues. It will often get into
a state where where it doesn't try to start a slave. I'm not sure exactly why
this is but it is related to the fact that the state is spread out over 4
objects and 6 classes
- buildbot.buildslave.base.AbstractLatentBuildSlave
  - buildbot.buildslave.base.AbstractBuildSlave
- buildbot.process.slavebuilder.LatentSlaveBuilder
  - buildbot.process.slavebuilder.AbstractSlaveBuilder
- buildbot.process.builder.Builder
- buildbot.process.botmaster.BotMaster

This implements a simpler scheme, which acts like a regular slave, but watches
buildbots state to start and stop the slave.
- When a build request comes in for a builder the slave is allocated to,
  start this slave.
- Poll for existing requests for builders the slave is allocated to.
  (This catches the case where there are existing requests, and probably
  also the case where a build failed).
- Keep track of the builders using this slave, and stop the slave
  after it has been idle for a specified amount of time.

The starting and stopping of the node is handled in flocker_bb.ec2,
using an explicit state machine.


A few other changes are required to make this work well.

- Since buildbot doesn't know these slaves are latent, it will schedule all
  builds on the first slave to connect. To handle this, we monkeypatch
  ``BotMaster.maybeStartBuildsForSlave`` to wait 10s before starting builds on
  a newly connected slave.
- Only latent slaves receive a ``buildStarted`` call. We monkeypatch
  ``SlaveBuilder.buildStarted`` to call ``buildStarted`` if it exists.
- Since buildbot doesn't know these slaves are latent, the builders page
  doesn't show force build options if no slaves are connected. An updated
  template is included that always shows the force build forms.

"""

from twisted.application.internet import TimerService
from twisted.internet import defer
from twisted.internet import reactor

from buildbot.buildslave.base import BuildSlave
from buildbot import config

from machinist import WrongState


class OnDemandBuildSlave(BuildSlave):

    instance = image = None
    _poll_resolution = 5  # hook point for tests

    build_wait_timer = None

    def __init__(self,
                 # On-Demand related stuff
                 name, password, instance_booter,
                 build_wait_timeout=60 * 10,
                 keepalive_interval=None,

                 # Generic stuff for the base class
                 max_builds=None, notify_on_missing=[],
                 missing_timeout=60 * 20,
                 properties={}, locks=None,
                 ):

        BuildSlave.__init__(
            self, name, password, max_builds, notify_on_missing,
            missing_timeout, properties, locks)
        if build_wait_timeout < 0:
            config.error("%s: %s: Can't wait for negative time."
                         % (self.__class__, name))
        self.build_wait_timeout = build_wait_timeout
        # Uggh
        if keepalive_interval is not None:
            self.keepalive_interval = keepalive_interval

        self.building = set()

        self.instance_booter = instance_booter

        self.addService(TimerService(60, self.periodic))

    def buildStarted(self, sb):
        self._clearBuildWaitTimer()
        self.building.add(sb.builder_name)

    def buildFinished(self, sb):
        BuildSlave.buildFinished(self, sb)

        self.building.discard(sb.builder_name)
        if not self.building:
            if self.build_wait_timeout == 0:
                self.instance_booter.stop()
            else:
                self._setBuildWaitTimer()

    def _clearBuildWaitTimer(self):
        if self.build_wait_timer is not None:
            if self.build_wait_timer.active():
                self.build_wait_timer.cancel()
            self.build_wait_timer = None

    def attached(self, bot):
        d = BuildSlave.attached(self, bot)

        def set_metadata_and_timer(result):
            try:
                self.properties.setProperty(
                    'image_metadata',
                    self.instance_booter.image_metadata,
                    "buildslave"
                )
            except WrongState:
                self.properties.setProperty(
                    'image_metadata', None, "buildslave")
            try:
                self.properties.setProperty(
                    'instance_metadata',
                    self.instance_booter.instance_metadata,
                    "buildslave")
            except WrongState:
                self.properties.setProperty(
                    'instance_metadata', None, "buildslave")
            self._setBuildWaitTimer()
            return result
        d.addCallback(set_metadata_and_timer)
        return d

    def detached(self, mind):
        BuildSlave.detached(self, mind)
        # If the slave disconnects, assuming it is a problem with the instance,
        # and stop it.
        self.instance_booter.stop()

    def _setBuildWaitTimer(self):
        self._clearBuildWaitTimer()
        self.build_wait_timer = reactor.callLater(
            self.build_wait_timeout, self.instance_booter.stop)

    def requestSubmitted(self, request):
        builder_names = [b.name for b in
                         self.botmaster.getBuildersForSlave(self.slavename)]
        if request['buildername'] in builder_names:
            self.instance_booter.start()

    def startService(self):
        BuildSlave.startService(self)

        self._shutdown_callback_handle = reactor.addSystemEventTrigger(
            'before', 'shutdown', self.instance_booter.stop)

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
            self.instance_booter.start()
