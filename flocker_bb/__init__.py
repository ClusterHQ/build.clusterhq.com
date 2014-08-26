import os
import json

# We define this here so that
# 1) It is preserved over multiple runs of config.py
# 2) The environment isn't leaked to subprocesses
if 'privateData' not in globals():
    privateData = json.loads(os.environ.pop("BUILDBOT_CONFIG", "{}"))
