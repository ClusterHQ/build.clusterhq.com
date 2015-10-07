import glob, pickle, buildbot, re, sys, cStringIO as StringIO
from ansible.utils import template
from ansible.runner.return_data import ReturnData

class ActionModule:
    def __init__(self, runner):
        self.runner = runner
        
        
    def run(self, conn, tmp, module_name, module_args, inject, complex_args=None, **kwargs):
        jobs = glob.glob('work/*/*')

        out = StringIO.StringIO()

        count = 0
        count_failed = 0

        for job in jobs:
            foo, builder, job_num = job.split('/')

            job_obj = pickle.load(file(job))

            for step in job_obj.getSteps():
                if step.getResults()[0] != 0:
                    count_failed += 1
                    for log in step.getLogs():
                        if 'stdio' in log.filename:
                            out.write(builder + '/' + log.filename + '\n')
                            out.write(builder + '/' + log.filename + '.bz2\n')
                            break
                    break

            sys.stdout.write('Jobs: %d, failed jobs: %d\r' % (count, count_failed))
            sys.stdout.flush()
            count +=1
        
        return ReturnData(conn=conn, result=dict(
            changed=True,
            jobs=out.getvalue()
        ))
