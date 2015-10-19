"""
This Ansible module reads Buildbot jobs, identifies failed ones, and outputs 
the logfile name of the failed jobs.

Results are returned as a string, one by line in the jobs variable.
"""


import glob
import pickle
import sys
import cStringIO as StringIO
from ansible.runner.return_data import ReturnData


class ActionModule:
    def __init__(self, runner):
        self.runner = runner

    def run(self, conn, tmp, module_name, module_args,
            inject, complex_args=None, **kwargs):
        jobs = glob.glob('/tmp/jobs-work/*/*')

        out = StringIO.StringIO()

        count = 0
        count_failed = 0

        for job in jobs:
            builder, job_num = job.split('/')[-2:]

            job_obj = pickle.load(file(job))

            for step in job_obj.getSteps():
                if step.getResults()[0] != 0:
                    count_failed += 1
                    for log in step.getLogs():
                        if 'stdio' in log.filename:
                            out.write(builder + '/' + log.filename + '*\n')
                            break
                    break

            sys.stdout.write('Jobs: %d, failed jobs: %d\r'
                             % (count, count_failed))
            sys.stdout.flush()
            count += 1

        return ReturnData(conn=conn, result=dict(
            changed=True,
            jobs=out.getvalue()
        ))
