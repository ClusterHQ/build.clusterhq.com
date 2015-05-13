# Copyright Hybrid Logic Ltd.  See LICENSE file for details.

"""
Tests for ``flocker_bb.ec2``.
"""

from twisted.python.filepath import FilePath
from twisted.trial.unittest import SynchronousTestCase

import yaml

from flocker_bb import __file__ as flocker_bb_dir
from flocker_bb.ec2 import ec2_slave
from flocker_bb.password import generate_password

sample_config = FilePath(flocker_bb_dir).parent().sibling('config.yml.sample')


def ec2_slave_config():
    all_config = yaml.load(sample_config.open())
    for slave_name, slave_config in all_config['slaves'].items():
        if u'ami' in slave_config:
            return slave_name, slave_config


def ec2_credentials():
    return yaml.load(sample_config.open())['aws']


def sample_build_master():
    return yaml.load(sample_config.open())['buildmaster']


class EC2SlaveTests(SynchronousTestCase):
    def test_constructor(self):
        """
        """
        slave_name, slave_config = ec2_slave_config()
        ec2_slave(
            name=slave_name,
            password=generate_password(32),
            config=slave_config,
            credentials=ec2_credentials(),
            user_data=u'',
            region=u'us-west-2',
            keypair_name=u'hybrid-master',
            security_name=u'ssh',
            build_wait_timeout=50*60,
            keepalive_interval=60,
            buildmaster=sample_build_master(),
            image_tags=ec2_credentials().get('image_tags', {}),
        )
