import argparse
import os
import time

import boto.ec2


# Usual Fedora 20 image used for most Buildbot infrastructure
ec2_image = {
    'Fedora-x86_64-20-20140407-sda': 'ami-cc8de6fc'
}


def start_instance(
        aws_region, key_name, instance_type, security_group, instance_name):

    conn = boto.ec2.connect_to_region(aws_region)

    # Buildbot master requires 4Gb diskspace.  Set the EBS root disk (disk1)
    # to be 4Gb instead of default (2Gb).
    disk1 = boto.ec2.blockdevicemapping.EBSBlockDeviceType()
    disk1.size = 4
    diskmap = boto.ec2.blockdevicemapping.BlockDeviceMapping()
    diskmap['/dev/sda1'] = disk1

    reservation = conn.run_instances(
        ec2_image['Fedora-x86_64-20-20140407-sda'],
        key_name=key_name,
        instance_type=instance_type,
        security_groups=[security_group],
        block_device_map=diskmap)

    instance = reservation.instances[0]

    conn.create_tags([instance.id], {'Name': instance_name})

    state = instance.state
    print 'Instance', state

    while state != 'running':
        time.sleep(1)
        instance.update()
        new_state = instance.state
        if new_state != state:
            state = new_state
            print 'Instance', state

    print 'Instance ID:', instance.id
    print 'Instance IP:', instance.ip_address

if __name__ == '__main__':

    parser = argparse.ArgumentParser(
        description='Start AWS EC2 instance for Buildbot master')
    parser.add_argument('--region', default='us-west-2', help='AWS region')
    parser.add_argument(
        '--security-group', default='Buildbot staging',
        help='AWS security group')
    parser.add_argument(
        '--key-name', default='hybrid-master', help='AWS key name')
    parser.add_argument(
        '--instance-type', default='m3.medium', help='AWS instance type')
    parser.add_argument('--instance-name', help='AWS instance name')
    args = parser.parse_args()

    # AWS region
    aws_region = args.region

    # Name of security group exposing ports for Buildmaster
    security_group = args.security_group

    # Key name for EC2 host
    key_name = 'hybrid-master'

    instance_name = args.instance_name
    if instance_name is None:
        instance_name = '{} BuildBot staging'.format(os.environ['USER'])

    start_instance(
        args.region, args.key_name, args.instance_type, args.security_group,
        instance_name)
