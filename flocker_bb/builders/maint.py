import os
from datetime import datetime, timedelta
import json

from characteristic import attributes, Attribute

from dateutil.parser import parse as parse_date

from libcloud.compute.providers import get_driver, Provider
from libcloud.compute.base import NodeState

from twisted.internet.threads import deferToThread

from buildbot.steps.master import MasterShellCommand
from buildbot.config import BuilderConfig
from buildbot.process.factory import BuildFactory
from buildbot.schedulers.timed import Periodic
from buildbot.process.buildstep import LoggingBuildStep
from buildbot.status.results import SUCCESS

from flocker_bb import privateData


def makeCleanOldBuildsFactory():
    """
    Remove build results older than 14 days.
    """
    # FIXME we shouldn't hard code this (DRY)
    basedir = r'/srv/buildmaster/data'
    path = os.path.join(basedir, "private_html")

    factory = BuildFactory()
    factory.addStep(MasterShellCommand(
        ['find', path,
         '-type', 'f', '-mtime', '+14',
         '-exec', 'unlink', '{}', ';'],
        description=['Removing', 'old', 'results'],
        descriptionDone=['Remove', 'old', 'results'],
        name='remove-old-results'))

    return factory


def get_creation_time(node):
    """
    Get the creation time of a libcloud node.

    Rackspace and EC2 store the information in different metadta.

    :return datetime:
    """
    date_string = node.extra.get("created", node.extra.get("launch_time"))
    if date_string is None:
        return None
    else:
        return parse_date(date_string)


@attributes([
    Attribute('lag'),
    Attribute('prefixes',
              default_value=('acceptance-test-', 'client-test-')),
])
class CleanAcceptanceInstances(LoggingBuildStep):
    """
    :ivar timedelta lag: THe age of instances to destroy.
    :param prefixes: List of prefixes of instances to destroy.
    """
    name = 'clean-acceptance-instances'
    description = ['Cleaning', 'acceptance', 'instances']
    descriptionDone = ['Clean', 'acceptance', 'instances']
    haltOnFailure = True
    flunkOnFailure = True

    def _thd_clean_nodes(self, config):
        # Get the libcloud drivers corresponding to the acceptance tests.
        rackspace = get_driver(Provider.RACKSPACE)(
            config['rackspace']['username'], config['rackspace']['key'],
            region=config['rackspace']['region'])
        ec2 = get_driver(Provider.EC2)(
            config['aws']['access_key'], config['aws']['secret_access_token'],
            region=config['aws']['region'])

        drivers = [rackspace, ec2]

        # Get the prefixes of the instance names, appending the creator from
        # the config.
        creator = config['metadata']['creator']
        prefixes = tuple(map(lambda prefix: prefix + creator, self.prefixes))

        # Find out the cutoff time to use.
        now = datetime.utcnow()
        cutoff = now - self.lag

        # Get all the nodes from the cloud providers
        all_nodes = []
        for driver in drivers:
            all_nodes += driver.list_nodes()

        # Filter them for running nodes with the right prefix.
        test_nodes = [
            node for node
            in all_nodes
            if node.name.startswith(prefixes)
            and (node.state == NodeState.RUNNING)
        ]

        # Split the nodes into kept and destroyed nodes;
        # destroying the ones older than the cut-off.
        destroyed_nodes = []
        kept_nodes = []
        for node in test_nodes:
            creation_time = get_creation_time(node)
            if creation_time is not None and creation_time < cutoff:
                node.destroy()
                destroyed_nodes.append(node)
            else:
                kept_nodes.append(node)

        return {
            'destroyed': destroyed_nodes,
            'kept': kept_nodes,
        }

    def start(self):
        config = privateData['acceptance']['config']
        d = deferToThread(self._thd_clean_nodes, config)
        d.addCallback(self.log)
        d.addErrback(self.failed)

    def log(self, result):
        """
        Log the nodes kept and destroyed.
        """
        for kind, nodes in result.iteritems():
            content = json.dumps([
                {
                    'id': node.id,
                    'name': node.name,
                    'provider': node.driver.name,
                    'creatation_time': get_creation_time(node),
                }
                for node in nodes
            ], sort_keys=True, indent=4, separators=(',', ': '))
            self.addCompleteLog(name=kind, text=content)
        self.finished(SUCCESS)


def makeCleanOldAcceptanceInstances():
    """
    Remove acceptance and client test nodes older than 2 hours.
    """
    factory = BuildFactory()
    factory.addStep(CleanAcceptanceInstances(
        lag=timedelta(hours=2),
    ))
    return factory


def getBuilders(slavenames):
    return [
        BuilderConfig(
            name='clean-old-builds',
            # These slaves are dedicated slaves.
            slavenames=slavenames['fedora-20/vagrant'],
            factory=makeCleanOldBuildsFactory()),
        BuilderConfig(
            name='clean-old-nodes',
            # These slaves are dedicated slaves.
            slavenames=slavenames['fedora-20/vagrant'],
            factory=makeCleanOldAcceptanceInstances()),
    ]


def getSchedulers():
    daily = Periodic(name='daily',
                     builderNames=['clean-old-builds'],
                     periodicBuildTimer=24*3600)
    # This is so the zulip reporter gives better message.
    daily.codebases = {'maint': {'branch': 'daily'}}

    hourly = Periodic(name='hourly',
                      builderNames=['clean-old-nodes'],
                      periodicBuildTimer=3600)
    # This is so the zulip reporter gives better message.
    hourly.codebases = {'maint': {'branch': 'hourly'}}

    return [daily, hourly]
