# Remove old Vagrant boxes

from subprocess import check_output, check_call

if __name__ == '__main__':
    vagrant_boxes = check_output(['vagrant', 'box', 'list']).strip().split('\n')
    for line in vagrant_boxes:
        box_name, box_details = line.split(None, 1)
        box_platform, box_version = box_details[1:-1].split(', ', 1)
        check_call(['vagrant', 'box', 'remove', '--box-version={}'.format(box_version), box_name])
