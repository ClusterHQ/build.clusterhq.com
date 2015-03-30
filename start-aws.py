#!/usr/bin/env python
import argparse
import os
import time

import boto.ec2


# Usual images used for Buildbot infrastructure
ec2_image = {
    'centos': 'ami-c7d092f7',  # CentOS 7 x86_64 (2014_09_29)
    'fedora': 'ami-cc8de6fc',  # Fedora-x86_64-20-20140407-sda
    'ubuntu': 'ami-29ebb519',  # ubuntu-trusty-14.04-amd64-server-20150123
}


def start_instance(
        aws_region, key_name, instance_type, security_group, operating_system,
        instance_name):

    conn = boto.ec2.connect_to_region(aws_region)

    # Buildbot master requires 4Gb diskspace. Fedora default is 2Gb.
    # Ubuntu default is 8Gb, which cannot be reduced. Set the EBS root
    # disk (disk1) to be 8Gb instead of default.  This gives plenty of
    # leeway for future increases.
    disk1 = boto.ec2.blockdevicemapping.EBSBlockDeviceType()
    disk1.size = 8
    diskmap = boto.ec2.blockdevicemapping.BlockDeviceMapping()
    diskmap['/dev/sda1'] = disk1

    reservation = conn.run_instances(
        ec2_image[operating_system],
        key_name=key_name,
        instance_type=instance_type,
        security_groups=[security_group],
        block_device_map=diskmap)

    instance = reservation.instances[0]

    conn.create_tags([instance.id], {'Name': instance_name})

    state = instance.state
    print 'Instance', state

    # Display state as instance starts up, to keep user informed that
    # things are happening.
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
        '--os', choices=ec2_image.keys(), default='fedora',
        help='Operating System')
    parser.add_argument(
        '--key-name', default='hybrid-master', help='AWS key name')
    parser.add_argument(
        '--instance-type', default='m3.medium', help='AWS instance type')
    parser.add_argument(
        '--instance-name',
        default='{} BuildBot staging'.format(os.environ['USER']),
        help='AWS instance name')
    args = parser.parse_args()

    start_instance(
        args.region, args.key_name, args.instance_type, args.security_group,
        args.os, args.instance_name)
