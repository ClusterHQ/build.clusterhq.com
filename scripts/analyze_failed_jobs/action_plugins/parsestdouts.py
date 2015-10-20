"""
Ansible module for finding failed buildbot jobs.

Stores results in ``out/test-count.csv``, which has columns for builder, test
and failure count.
"""

import glob
import bz2
from ansible.runner.return_data import ReturnData

IGNORED_BUILDERS = [
    'flocker',
    'flocker-twisted-trunk',
    'flocker-acceptance-vagrant-centos-7-zfs',
    'flocker-installed-package-vagrant-centos-7'
]


class ActionModule:
    def __init__(self, runner):
        self.runner = runner

    def run(self, conn, tmp, module_name, module_args,
            inject, complex_args=None, **kwargs):
        stdouts = glob.glob('/tmp/jobs-work/*/*-*')

        stats = {}

        for filename in stdouts:
            builder = filename.split('/')[3]

            if builder in IGNORED_BUILDERS:
                continue

            if filename.endswith('bz2'):
                data = bz2.BZ2File(filename).readlines()
            else:
                data = file(filename).readlines()

            for line in data:
                if '... [ERROR]' in line:
                    test = builder + ':' + line.split(' ')[0]
                    if test not in stats:
                        stats[test] = 0
                    stats[test] += 1

        stats = stats.items()
        stats.sort(key=lambda x: x[1])

        out = file('out/test-count.csv', 'w')
        for stat in stats:
            out.write('%s:%s\n' % stat)
        out.close()

        return ReturnData(conn=conn, result=dict(
            changed=True
        ))
