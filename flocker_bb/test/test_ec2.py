# Copyright Hybrid Logic Ltd.  See LICENSE file for details.

"""
Tests for ``flocker_bb.ec2``.
"""
import yaml

from twisted.python.filepath import FilePath
from twisted.trial.unittest import SynchronousTestCase

from zope.interface.verify import verifyObject

from flocker_bb import __file__ as flocker_bb_dir
from flocker_bb.ec2 import ec2_slave, ICloudDriver, rackspace_slave
from flocker_bb.password import generate_password

sample_config = FilePath(flocker_bb_dir).parent().sibling('config.yml.sample')


def ec2_slave_config():
    all_config = yaml.load(sample_config.open())
    for slave_name, slave_config in all_config['slaves'].items():
        if u'ami' in slave_config:
            return slave_name, slave_config


def rackspace_slave_config():
    all_config = yaml.load(sample_config.open())
    for slave_name, slave_config in all_config['slaves'].items():
        if u'openstack-image' in slave_config:
            return slave_name, slave_config


def sample_credentials(provider):
    return yaml.load(sample_config.open())[provider]


def sample_build_master():
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


class EC2SlaveTests(OnDemandBuildSlaveTestsMixin, SynchronousTestCase):
    def setUp(self):
        """
        """
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
            image_tags=credentials.get('image_tags', {}),
        )


class RackspaceSlaveTests(OnDemandBuildSlaveTestsMixin, SynchronousTestCase):
    def setUp(self):
        """
        """
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
            image_tags=credentials.get('image_tags', {}),
        )
