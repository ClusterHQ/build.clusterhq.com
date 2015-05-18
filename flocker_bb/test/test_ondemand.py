# Copyright Hybrid Logic Ltd.  See LICENSE file for details.

"""
Tests for ``flocker_bb.ondemand``.
"""
import os

import yaml

from twisted.python.filepath import FilePath
from twisted.trial.unittest import SynchronousTestCase

from zope.interface.verify import verifyObject

from flocker_bb import __file__ as flocker_bb_dir
from flocker_bb.ec2 import ec2_slave, ICloudDriver, rackspace_slave
from flocker_bb.password import generate_password

# Use either the ``config.yml.sample`` or a config file path supplied in the
# environment.
sample_config_path = os.environ.get('BUILDBOT_CONFIG_PATH')
if sample_config_path is None:
    sample_config = FilePath(flocker_bb_dir).parent().sibling(
        'config.yml.sample')
    
else:
    sample_config = FilePath(sample_config_path)


def ec2_slave_config():
    """
    :return: The configuration for the first EC2 slave defined in the config
        file.
    """
    all_config = yaml.load(sample_config.open())
    for slave_name, slave_config in all_config['slaves'].items():
        if u'ami' in slave_config:
            return slave_name, slave_config


def rackspace_slave_config():
    """
    :return: The configuration for the first Rackspace slave defined in the
        config file.
    """
    all_config = yaml.load(sample_config.open())
    for slave_name, slave_config in all_config['slaves'].items():
        if u'openstack-image' in slave_config:
            return slave_name, slave_config


def sample_credentials(provider):
    """
    :return: The credentials for ``provider`` found in the ``sample_config``.
    """
    return yaml.load(sample_config.open())[provider]


def sample_build_master():
    """
    :return: The buildmaster configuration from the ``sample_config``.
    """
    return yaml.load(sample_config.open())['buildmaster']


class OnDemandBuildSlaveTestsMixin(object):
    """
    Tests for ``OnDemandBuildSlave`` factory functions.
    """
    def test_driver_interface(self):
        """
        ``buildslave`` has an instance_booter with a driver
        implementing the ``ICloudDriver`` interface.
        """
        self.assertTrue(
            verifyObject(
                ICloudDriver,
                self.buildslave.instance_booter.driver
            )
        )

    def test_start_service(self):
        """
        An unfinished attempt to test how the ``OnDemandBuildSlave`` responds
        to build requests.

        I intended to feed a fake request to the ``OnDemandBuildSlave`` and
        verify that it creates a cloud node in response.

        This will require real credentials to be included in the supplied
        config file.
        """
        from twisted.internet.defer import succeed
        class FakeMaster(object):
            @staticmethod
            def subscribeToBuildRequests(request):
                """
                """
            class db(object):
                class buildslaves(object):
                    @staticmethod
                    def getBuildslaveByName(slavename):
                        """
                        """
                        return succeed(None)

                class buildrequests(object):
                    @staticmethod
                    def getBuildRequests(claimed):
                        """
                        """
                        return [dict(buildername=self.buildslave.slavename)]

        self.buildslave.master = FakeMaster

        class FakeBuilder(object):
            name = self.buildslave.slavename

        class FakeBotMaster(object):
            @staticmethod
            def getBuildersForSlave(slavename):
                return [FakeBuilder()]

        self.buildslave.botmaster = FakeBotMaster()
        self.buildslave.startService()


class EC2SlaveTests(OnDemandBuildSlaveTestsMixin, SynchronousTestCase):
    """
    Tests for ``ec2_slave`` factory function and the ``OnDemandBuildSlave``
    that it returns.
    """
    def setUp(self):
        slave_name, slave_config = ec2_slave_config()
        credentials = sample_credentials('aws')
        self.buildslave = ec2_slave(
            name=slave_name,
            password=generate_password(32),
            config=slave_config,
            credentials=credentials,
            user_data=u'',
            region=u'us-west-2',
            keypair_name=u'hybrid-master',
            security_name=u'ssh',
            build_wait_timeout=50*60,
            keepalive_interval=60,
            buildmaster=sample_build_master(),
        )


class RackspaceSlaveTests(OnDemandBuildSlaveTestsMixin, SynchronousTestCase):
    """
    Tests for ``rackspace_slave`` factory function and the
    ``OnDemandBuildSlave`` that it returns.
    """
    def setUp(self):
        slave_name, slave_config = rackspace_slave_config()
        credentials = sample_credentials('rackspace')
        self.buildslave = rackspace_slave(
            name=slave_name,
            password=generate_password(32),
            config=slave_config,
            credentials=credentials,
            user_data=u'',
            build_wait_timeout=50*60,
            keepalive_interval=60,
            buildmaster=sample_build_master(),
        )
