import os
import time

import boto.ec2

ec2_image = {
    'Fedora-x86_64-20-20140407-sda': 'ami-cc8de6fc'
}

conn = boto.ec2.connect_to_region('us-west-2')

# Buildbot master requires more than standard 2Gb disk.
# Also add an ephemeral (4Gb) disk, not currently used.
# If we link /var/lib/docker to /mnt/docker, we don't need the EBS disk
disk1 = boto.ec2.blockdevicemapping.EBSBlockDeviceType()
disk1.size = 4
disk2 = boto.ec2.blockdevicemapping.BlockDeviceType(ephemeral_name='ephemeral0')
diskmap = boto.ec2.blockdevicemapping.BlockDeviceMapping()
diskmap['/dev/sda1'] = disk1
diskmap['/dev/sdb1'] = disk2


reservation = conn.run_instances(
    ec2_image['Fedora-x86_64-20-20140407-sda'],
    key_name='hybrid-master',
    instance_type='m3.medium',
    security_groups=['Buildbot staging'],
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
