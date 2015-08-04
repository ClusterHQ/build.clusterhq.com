"""
Remove Vagrant boxes created more than 14 days ago.
"""

from subprocess import check_output, call
import os.path
import os
import time

if __name__ == '__main__':
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
                if time_difference > 14 * 24 * 60 * 60:
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
