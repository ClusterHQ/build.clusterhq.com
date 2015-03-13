import os
import time

import boto.ec2


# AWS region
aws_region = 'us-west-2'

# Name of security group exposing ports for Buildmaster
security_group = 'Buildbot staging'

# Key name for EC2 host
key_name = 'hybrid-master'


ec2_image = {
    'Fedora-x86_64-20-20140407-sda': 'ami-cc8de6fc'
}

conn = boto.ec2.connect_to_region(aws_region)

# Buildbot master requires more than standard 4Gb disk.  Set the EBS
# root disk to be 4Gb instead of default 2Gb.
# Also add an ephemeral (4Gb) disk, not currently used.  If we link
# /var/lib/docker to /mnt/docker, we don't need to increase the
# size of the EBS disk.
disk1 = boto.ec2.blockdevicemapping.EBSBlockDeviceType()
disk1.size = 4
disk2 = boto.ec2.blockdevicemapping.BlockDeviceType(
    ephemeral_name='ephemeral0')
diskmap = boto.ec2.blockdevicemapping.BlockDeviceMapping()
diskmap['/dev/sda1'] = disk1
diskmap['/dev/sdb1'] = disk2


reservation = conn.run_instances(
    ec2_image['Fedora-x86_64-20-20140407-sda'],
    key_name=key_name,
    instance_type='m3.medium',
    security_groups=[security_group],
    block_device_map=diskmap)

instance = reservation.instances[0]

username = os.environ['USER']
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
