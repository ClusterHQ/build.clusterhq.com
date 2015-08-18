# Copyright 2015 ClusterHQ Inc

"""
Remove ClusterHQ Vagrant boxes older than a given number of days.
"""

from subprocess import check_output, call
import os.path
import os
import sys
import time

if __name__ == '__main__':
    num_days = float(sys.argv[1])
    min_time = num_days * 24 * 60 * 60

    box_name_prefix = 'clusterhq/'

    vagrant_boxes = check_output(
        ['vagrant', 'box', 'list']).strip().split('\n')
    box_names = {}
    for line in vagrant_boxes:
        box_name, box_details = line.split(None, 1)
        if box_name.startswith(box_name_prefix):
            box_platform, box_version = box_details[1:-1].split(', ', 1)
            if box_name in box_names:
                box_names[box_name].append(box_version)
            else:
                box_names[box_name] = [box_version]

    boxes_directory = os.path.expanduser('~/.vagrant.d/boxes/')
    for box_name in box_names:
        directory = os.path.join(
            boxes_directory, box_name.replace('/', '-VAGRANTSLASH-'))
        files_in_directory = os.listdir(directory)
        for version in box_names[box_name]:
            if version in files_in_directory:
                version_subdirectory = os.path.join(directory, version)
                m_time = os.path.getmtime(version_subdirectory)
                now = time.time()
                time_difference = now - m_time
                sys.stdout.write(
                    '{name} {version} is {time_difference} seconds old: '.format(
                        name=box_name,
                        version=version,
                        time_difference=time_difference,
                    )
                )
                if time_difference > min_time:
                    # /dev/null is used to select the default option (No)
                    # when Vagrant asks whether a box in use by a VM should be
                    # removed.
                    sys.stdout.write('Deleting.\n')
                    with open('/dev/null', 'rw') as f:
                        call(
                            args=[
                                'vagrant', 'box', 'remove',
                                '--box-version={}'.format(box_version),
                                box_name,
                            ],
                            stdin=f,
                            stderr=f,
                        )
                else:
                    sys.stdout.write('Not Deleting.\n')
