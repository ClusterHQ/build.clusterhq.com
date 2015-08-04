# Remove old Vagrant boxes

from subprocess import check_output, check_call
import os.path
import os
import time

if __name__ == '__main__':
    box_name_prefix = 'clusterhq/'

    vagrant_boxes = check_output(['vagrant', 'box', 'list']).strip().split('\n')
    box_names = {}
    for line in vagrant_boxes:
        box_name, box_details = line.split(None, 1)
        if box_name.startswith(box_name_prefix):
            box_platform, box_version = box_details[1:-1].split(', ', 1)
            if box_name in box_names:
                box_names[box_name].append(box_version)
            else:
                box_names[box_name] = [box_version]

    for box_name in box_names:
        directory = '/home/buildslave/.vagrant.d/boxes/clusterhq-VAGRANTSLASH-' + box_name[len(box_name_prefix):]
        files_in_directory = os.listdir(directory)
        for version in box_names[box_name]:
            if version in files_in_directory:
                version_subdirectory = os.path.join(directory, version)
                m_time = os.path.getmtime(version_subdirectory)
                now = time.time()
                time_difference = now - m_time
                if time_difference > 14 * 24 * 60 * 60:#14 * 24 * 60 * 60:
                    with open('/dev/null') as f:
                        check_call(['vagrant', 'box', 'remove', '--box-version={}'.format(box_version), box_name], stdin=f)
