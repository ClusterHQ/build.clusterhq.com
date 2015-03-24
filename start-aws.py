import os
import time

import boto.ec2


# Usual Fedora 20 image used for most Buildbot infrastructure
ec2_image = {
    'Fedora-x86_64-20-20140407-sda': 'ami-cc8de6fc'
}


def start_instance(
        aws_region, key_name, instance_type, security_group, username):

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

    instance_name = '{} BuildBot staging'.format(username)
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
    # AWS region
    aws_region = 'us-west-2'

    # Name of security group exposing ports for Buildmaster
    security_group = 'Buildbot staging'

    # Key name for EC2 host
    key_name = 'hybrid-master'

    username = os.environ['USER']
    start_instance(aws_region, key_name, 'm3.medium', security_group, username)
