#!/usr/bin/env python

import sys
import time
from uuid import UUID
from datetime import datetime
import yaml
from common import (
    wait_for_image, rackspace_is_ready, load_manifest
)

from libcloud.compute.base import NodeImage
from libcloud.compute.deployment import ScriptDeployment

# Watch out for dodgy providers that mangle your tag names (I'm looking *right*
# at you Rackspace).
BASE_NAME_TAG = 'base_name'


def get_size(driver, size_name):
    """
    Return a ``NodeSize`` corresponding to the name of size.
    """
    try:
        return [s for s in driver.list_sizes() if s.id == size_name][0]
    except IndexError:
        raise ValueError("Unknown EC2 size.", size_name)


def deploy_node_aws(driver, name, base_ami, deploy, username, userdata=None,
                    size="t1.micro", disk_size=8,
                    private_key_file=None,
                    keyname=None):
    """
    Deploy a node.

    :param driver: The libcloud driver.
    :param str name: The name of the node.
    :param str base_ami: The name of the ami to use.
    :param Deployment deploy: The libcloud ``ScriptDeployment`` to run on the
        node.
    :param bytes userdata: User data to pass to the instance.
    :param bytes size: The name of the size to use.
    :param int disk_size: The size of disk to allocate.
    """
    from common import aws_config

    if private_key_file is None:
        private_key_file = aws_config['private_key_file']

    if keyname is None:
        keyname = aws_config['keyname']

    node = driver.deploy_node(
        name=name,
        image=NodeImage(id=base_ami, name=None, driver=driver),
        size=get_size(driver, size),

        ex_keyname=keyname,
        ex_security_groups=['ssh'],
        ex_blockdevicemappings=[
            {"DeviceName": "/dev/sda1",
             "Ebs": {"VolumeSize": disk_size,
                     "DeleteOnTermination": True,
                     "VolumeType": "gp2"}}
        ],

        ssh_key=private_key_file,
        ssh_username=username,
        # Deploy stuff
        deploy=deploy,
        ex_userdata=userdata,
    )
    if deploy.exit_status:
        print deploy.stdout
        print deploy.stderr
        print
        print "Deploy failed."
        driver.destroy_node(node)
        sys.exit(1)
    return node


def deploy_node_rackspace(driver, name, base_image, deploy, ssh_username,
                          userdata, size, private_key_file, keyname):
    """
    Deploy a node.

    :param driver: The libcloud driver.
    :param str name: The name of the node.
    :param str base_ami: The name of the ami to use.
    :param Deployment deploy: The libcloud ``ScriptDeployment`` to run on the
        node.
    :param bytes userdata: User data to pass to the instance.
    :param bytes size: The name of the size to use.
    :param int disk_size: The size of disk to allocate.
    """
    node = driver.deploy_node(
        name=name,
        image=NodeImage(id=base_image, name=None, driver=driver),
        size=get_size(driver, size),
        ex_keyname=keyname,
        ssh_key=private_key_file,
        ssh_username=ssh_username,
        # Deploy stuff
        deploy=deploy,
        ex_userdata=userdata,
    )
    if deploy.exit_status:
        print deploy.stdout
        print deploy.stderr
        print
        print "Deploy failed."
        driver.destroy_node(node)
        sys.exit(1)
    return node


def stop_node(driver, node):
    driver.ex_stop_node(node)
    while driver.list_nodes(
            ex_node_ids=[node.id])[0].extra['status'] != 'stopped':
        time.sleep(1)


def create_image(driver, node, name):
    image = driver.create_image(node, name)
    wait_for_image(driver, image)
    return image


def build_image_aws(name, base_ami, deploy, username,
                    userdata=None, size="t1.micro", disk_size=8):
    """
    Build an image by deploying a node, and then snapshoting the image.

    See deploy node for arguments.
    """
    from common import driver

    timestamp = datetime.utcnow().strftime('%Y%m%d.%H%M%S')
    print "Deploying %(name)s-build." % dict(name=name)
    node = deploy_node_aws(
        driver,
        name=name + "-build",
        base_ami=base_ami,
        deploy=deploy,
        userdata=userdata,
        username=username,
        size=size,
        disk_size=disk_size,
    )
    try:
        print "Stopping %(name)s-build." % dict(name=name)
        stop_node(driver, node)
        ami_name = "%(name)s/%(timestamp)s" % {
            'name': name,
            'timestamp': timestamp,
        }
        print "Creating image %(name)s." % dict(name=ami_name)
        image = create_image(driver, node, ami_name)
        driver.ex_create_tags(image, tags={
            BASE_NAME_TAG: name,
            'timestamp': timestamp,
            })
    finally:
        print "Destroying %(name)s-build." % dict(name=name)
        driver.destroy_node(node)

    print "%(name)s: %(ami)s" % dict(name=name, ami=image.id)
    return image.id


def rackspace_driver(username, api_key, region):
    from libcloud.compute.providers import get_driver, Provider
    rackspace = get_driver(Provider.RACKSPACE)
    driver = rackspace(username, api_key, region=region)
    driver.is_ready = rackspace_is_ready
    return driver


def build_image_rackspace(name, base_image, deploy, **kwargs):
    """
    Build an image by deploying a node, and then snapshoting the image.

    See deploy node for arguments.
    """
    username = kwargs.pop('username')
    api_key = kwargs.pop('api_key')
    region = kwargs.pop('region')
    driver = rackspace_driver(username, api_key, region)
    timestamp = datetime.utcnow().strftime('%Y%m%d.%H%M%S')
    print "Deploying %(name)s-build." % dict(name=name)
    node = deploy_node_rackspace(
        driver,
        name=name + "-build",
        base_image=base_image,
        deploy=deploy,
        **kwargs
    )
    try:
        image_name = "%(name)s/%(timestamp)s" % {
            'name': name,
            'timestamp': timestamp,
        }
        print "Creating image %(name)s." % dict(name=image_name)
        image = driver.create_image(node, image_name, metadata={
            BASE_NAME_TAG: name,
            'timestamp': timestamp,
        })
        wait_for_image(driver, image)
    finally:
        print "Destroying %(name)s-build." % dict(name=name)
        driver.destroy_node(node)

    print "%(name)s: %(id)s" % dict(name=name, id=image.id)
    return image.id


def process_image_aws(manifest_base, images, args):
    image_name = args.pop('name')
    base_ami = args.pop('base-ami')
    if not base_ami.startswith('ami-'):
        base_ami = images[base_ami]

    step = args.pop('deploy')
    if 'script' in step:
        deploy = ScriptDeployment(step['script'])
    elif 'file' in step:
        deploy = ScriptDeployment(
            manifest_base.child(step['file']).getContent())
    else:
        raise ValueError('Unknown deploy type.')

    images[image_name] = build_image_aws(
        name=image_name,
        base_ami=base_ami,
        deploy=deploy,
        **args
    )


def process_image_rackspace(manifest_base, images, args):
    image_name = args.pop('name')
    base_image = args.pop('base-image')

    try:
        UUID(base_image)
    except ValueError:
        base_image = images[base_image]

    step = args.pop('deploy')
    if 'script' in step:
        deploy = ScriptDeployment(step['script'])
    elif 'file' in step:
        deploy = ScriptDeployment(
            manifest_base.child(step['file']).getContent()
            # To ensure a consistent state before taking a snapshot
            + b'\n'
            + b'sync'
            + b'\n'
        )
    else:
        raise ValueError('Unknown deploy type.')

    rackspace_config = yaml.safe_load(open("rackspace_config.yml"))

    args.update(rackspace_config)

    images[image_name] = build_image_rackspace(
        name=image_name,
        base_image=base_image,
        deploy=deploy,
        **args
    )


image_processors = {
    'aws': process_image_aws,
    'rackspace': process_image_rackspace,
}


def main():
    DISTRO = sys.argv[1]
    PROVIDER = sys.argv[2]
    base, manifest = load_manifest(DISTRO, PROVIDER)

    images = {}

    for image in manifest['images']:
        image_processors[PROVIDER](base, images, image)
