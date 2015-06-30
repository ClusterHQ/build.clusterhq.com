import os
from datetime import datetime, timedelta
import json
import yaml
from uuid import UUID

from characteristic import attributes, Attribute

from dateutil.parser import parse as parse_date
from dateutil.tz import tzutc

from libcloud.compute.providers import get_driver, Provider
from libcloud.compute.base import NodeState

from twisted.python.log import err
from twisted.internet.threads import deferToThread

from buildbot.steps.master import MasterShellCommand
from buildbot.config import BuilderConfig
from buildbot.process.factory import BuildFactory
from buildbot.schedulers.timed import Periodic
from buildbot.schedulers.forcesched import ForceScheduler
from buildbot.process.buildstep import LoggingBuildStep
from buildbot.status.results import SUCCESS, FAILURE

from flocker_bb import privateData


MAGIC = 42


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

    Rackspace and EC2 store the information in different metadeta.

    :return: The creation time, if available.
    :rtype: datetime or None
    """
    date_string = node.extra.get("created", node.extra.get("launch_time"))
    if date_string is None:
        return None
    else:
        return parse_date(date_string)


def fmap(_f, _value, *args, **kwargs):
    """
    Apply a function to a value unless the value is None

    :param _f: Function to call. Should be passed positionally.
    :param _value: Value to pass to function, if it is not None.
    :param *args: Extra parameters to pass to function.
    :param *kwargs: Extra parameters to pass to function.

    :return: The result of calling the function, or None if the value is None.
    """
    if _value is None:
        return None
    else:
        return _f(_value, *args, **kwargs)

# FLOC-2288
# New CleanVolumes LoggingBuildStep
# parameterized on age (lag, like CleanAcceptanceInstances)
#
# libcloud configured just as it is in CleanAcceptanceInstances (But with
# multiple AWS regions since, unlike instances, volumes are created in more
# than one AWS region by the test suite).
#
# log method that reports every volume destroyed
# if any volumes were destroyed, the build step finishes with FAILURE
# otherwise with SUCCESS

def get_rackspace_driver(rackspace):
    rackspace = get_driver(Provider.RACKSPACE)(
        rackspace['username'], rackspace['key'],
        region=rackspace['region'],
    )
    return rackspace


def get_ec2_driver(aws):
    ec2 = get_driver(Provider.EC2)(
        aws['access_key'], aws['secret_access_token'],
        region=aws['region'],
    )
    return ec2


@attributes(["lag"])
class CleanVolumes(LoggingBuildStep):
    def start(self):
        config = privateData['acceptance']['config']
        d = deferToThread(self._blocking_clean_volumes, yaml.safe_load(config))
        d.addCallback(self.log)
        d.addErrback(self.failed)

    def _get_cloud_drivers(self, config):
        base_ec2 = config["aws"]

        drivers = [
            get_rackspace_driver(config["rackspace"]),
            get_ec2_driver(base_ec2),
        ]

        for extra in config["extra-aws"]:
            extra_driver_config = base_ec2.copy()
            extra_driver_config.update(extra)
            drivers.append(get_ec2_driver(config))
        return drivers

    def _get_cloud_volumes(self, drivers):
        volumes = []
        for driver in drivers:
            volumes.extend(driver.list_volumes())
        return volumes

    def _get_cluster_id(self, volume):
        return _get_tag(volume, 'flocker-cluster-id')

    def _get_dataset_id(self, volume):
        return _get_tag(volume, 'flocker-cluster-id')

    def _is_test_cluster(self, cluster_id):
        try:
            return UUID(cluster_id).node == MAGIC
        except:
            err(None, "Could not parse cluster_id {!r}".format(cluster_id))
            return False

    def _is_test_volume(self, volume):
        try:
            cluster_id = self._get_cluster_id(volume)
        except KeyError:
            return False
        return self._is_test_cluster(cluster_id)

    def _get_volume_creation_time(self, volume):
        try:
            # AWS
            return volume.extra['create_time']
        except KeyError:
            # Rackspace.  Timestamps have no timezone indicated.  Manual
            # experimentation indicates timestamps are in UTC (which of course
            # is the only reasonable thing).
            return parse_date(
                volume.extra['created_at']
            ).replace(tzinfo=tzutc())

    def _filter_test_volumes(self, maximum_age, volumes):
        """
        From the given list of volumes, find volumes created by tests which are
        older than the maximum age.

        :param timedelta maximum_age: The oldest a volume may be without being
            considered old enough to include in the result.
        :param list all_volumes: The libcloud volumes representing all the
            volumes we can see on a particular cloud service.

        :rtype: ``VolumeActions``
        """
        now = datetime.now(tz=tzutc())
        destroy = []
        keep = []
        for volume in volumes:
            created = self._get_volume_creation_time(volume)
            if self._is_test_volume(volume) and now - created > maximum_age:
                destroy.append(volume)
            else:
                keep.append(volume)
        return VolumeActions(destroy=destroy, keep=keep)

    def _destroy_cloud_volumes(self, volumes):
        for volume in volumes:
            print(
                "Would have destroyed {}".format(self._describe_volume(volume))
            )

    def _blocking_clean_volumes(self, config):
        drivers = self._get_cloud_drivers(config)
        volumes = self._get_cloud_volumes(drivers)
        actions = self._filter_test_volumes(self.lag, volumes)
        self._destroy_cloud_volumes(actions.destroy)
        return {
            "destroyed": actions.destroy,
            "kept": actions.keep,
        }

    def _describe_volume(self, volume):
        return {
            'id': volume.id,
            'creation_time': fmap(
                datetime.isoformat, self._get_volume_creation_time(volume),
            ),
            'provider': volume.driver.name,
            # *Stuffed* with non-JSON-encodable goodies.
            'extra': repr(volume.extra),
        }

    def log(self, result):
        for (kind, volumes) in result.items():
            content = _dumps(
                sorted(
                    list(
                        self._describe_volume(volume) for volume in volumes
                    ), key=lambda description: description['creation_time'],
                )
            )
            self.addCompleteLog(name=kind, text=content)

        if len(result['destroyed']) > 0:
            # We fail if we destroyed any volumes because that means that
            # something is leaking volumes.
            self.finished(FAILURE)
        else:
            self.finished(SUCCESS)


def _dumps(obj):
    return json.dumps(obj, sort_keys=True, indent=4, separators=(',', ': '))


def _format_time(when):
    return fmap(datetime.isoformat, when)


def _get_tag(volume, tag_name):
    return volume.extra.get("tags", volume.extra.get("metadata"))[tag_name]


@attributes(["destroy", "keep"])
class VolumeActions(object):
    pass


@attributes([
    Attribute('lag'),
    Attribute('prefixes',
              default_value=('acceptance-test-', 'client-test-')),
])
class CleanAcceptanceInstances(LoggingBuildStep):
    """
    :ivar timedelta lag: The age of instances to destroy.
    :param prefixes: List of prefixes of instances to destroy.
    """
    name = 'clean-acceptance-instances'
    description = ['Cleaning', 'acceptance', 'instances']
    descriptionDone = ['Clean', 'acceptance', 'instances']
    haltOnFailure = False
    flunkOnFailure = True

    def _thd_clean_nodes(self, config):
        # Get the libcloud drivers corresponding to the acceptance tests.
        config = yaml.safe_load(config)
        rackspace = get_rackspace_driver(config["rackspace"])
        ec2 = get_ec2_driver(config["aws"])
        drivers = [rackspace, ec2]

        # Get the prefixes of the instance names, appending the creator from
        # the config.
        creator = config['metadata']['creator']
        prefixes = tuple(map(lambda prefix: prefix + creator, self.prefixes))

        # Find out the cutoff time to use.
        now = datetime.now(tzutc())
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
            content = _dumps([
                {
                    'id': node.id,
                    'name': node.name,
                    'provider': node.driver.name,
                    'creation_time': _format_time(get_creation_time(node)),
                }
                for node in nodes
            ])
            self.addCompleteLog(name=kind, text=content)
        if len(result['destroyed']) > 0:
            # We fail if we destroyed any nodes, because that means that
            # something is leaking nodes.
            self.finished(FAILURE)
        else:
            self.finished(SUCCESS)


def makeCleanOldResources():
    """
    Remove cloud instances (from acceptance and client tests) and cloud volumes
    nodes more than two hours old.
    """
    factory = BuildFactory()
    age = timedelta(hours=2)
    factory.addStep(CleanAcceptanceInstances(lag=age))
    factory.addStep(CleanVolumes(lag=age))
    return factory


RESOURCE_CLEANUP_BUILDER = 'clean-old-resources'


def getBuilders(slavenames):
    return [
        BuilderConfig(
            name='clean-old-builds',
            # These slaves are dedicated slaves.
            slavenames=slavenames['fedora-20/vagrant'],
            factory=makeCleanOldBuildsFactory()),
        BuilderConfig(
            name=RESOURCE_CLEANUP_BUILDER,
            slavenames=slavenames['aws/ubuntu-14.04'],
            factory=makeCleanOldResources()),
    ]


def getSchedulers():
    daily = Periodic(name='daily',
                     builderNames=['clean-old-builds'],
                     periodicBuildTimer=24*3600)
    # This is so the zulip reporter gives better message.
    daily.codebases = {'maint': {'branch': 'daily'}}

    hourly = Periodic(name='hourly',
                      builderNames=[RESOURCE_CLEANUP_BUILDER],
                      periodicBuildTimer=3600)
    # This is so the zulip reporter gives better message.
    hourly.codebases = {'maint': {'branch': 'hourly'}}

    force = ForceScheduler(
        name="force-maintenance",
        builderNames=["clean-old-builds", RESOURCE_CLEANUP_BUILDER],
    )

    return [daily, hourly, force]
