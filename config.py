# -*- python -*-
# ex: set syntax=python:

from os.path import dirname
import sys
sys.path.insert(0, dirname(__file__))
del sys, dirname

import os

# This is the dictionary that the buildmaster pays attention to. We also use
# a shorter alias to save typing.
c = BuildmasterConfig = {}

from twisted.python.filepath import FilePath
import json

privateData = json.loads(os.environ.get("BUILDBOT_CONFIG", "{}"))
# Some credentials
USER = privateData['auth']['user'].encode("utf-8")
PASSWORD = privateData['auth']['password'].encode("utf-8")


####### BUILDSLAVES

# 'slavePortnum' defines the TCP port to listen on for connections from slaves.
# This must match the value configured into the buildslaves (with their
# --master option)
c['slavePortnum'] = 9989

from flocker_bb import password
from flocker_bb.ec2_buildslave import EC2LatentBuildSlave

slaves = [('slave-%d' % (i,), password.generate(32))
          for i in range(2)]
cloudInit = FilePath(__file__).sibling("slave").child("cloud-init.sh").getContent()

c['slaves'] = [
        EC2LatentBuildSlave(
            name, password,
            'c3.large',
            build_wait_timeout=50*60,
            valid_ami_owners=[121466501720],
            valid_ami_location_regex=r'.*/fedora-buildslave-base',
            region='us-west-2',
            security_name='ssh',
            keypair_name='hybrid-master',
            identifier=privateData['aws']['identifier'],
            secret_identifier=privateData['aws']['secret_identifier'],
            user_data=cloudInit % {
                "token": privateData['github']['token'],
                "name": name,
                "password": password,
                'buildmaster_host': privateData['buildmaster']['host'],
                'buildmaster_port': c['slavePortnum'],
                },
            spot_instance=True,
            max_spot_price=0.10,
            )
        for name, password in slaves]


FLOCKER_SLAVES = [name for name, password in slaves]



####### CODEBASE GENERATOR

# A codebase generator synthesizes an internal identifier from a ... change.
# The codebase identifier lets parts of the build configuration more easily
# inspect attributes of the change without ambiguity when there are potentially
# multiple change sources (eg, multiple repositories being fetched for a single
# build).

FLOCKER_REPOSITORY = "git@github.com:ClusterHQ/flocker.git"

CODEBASES = {
    FLOCKER_REPOSITORY: "flocker",
    "https://github.com/ClusterHQ/flocker": "flocker",
    }

c['codebaseGenerator'] = lambda change: CODEBASES[change["repository"]]

c['change_source'] = []

####### BUILDERS

def rebuild(module):
    # Specify fromlist, so that __import__ returns the module, not the
    # top-level package
    reload(__import__(module, fromlist=['__path__']))

rebuild('flocker_bb.steps')
rebuild('flocker_bb.builders.flocker')


from flocker_bb.builders import flocker

c['builders'] = flocker.getBuilders(FLOCKER_SLAVES)

####### SCHEDULERS

# Configure the Schedulers, which decide how to react to incoming changes.  In
# this case, just kick off a 'runtests' build

c['schedulers'] = flocker.getSchedulers()

####### STATUS TARGETS

# 'status' is a list of Status Targets. The results of each build will be
# pushed to these targets. buildbot/status/*.py has a variety to choose from,
# including web pages, email senders, and IRC bots.

c['status'] = []

from flocker_bb.github import codebaseStatus
if privateData['github']['report_status']:
    c['status'].append(codebaseStatus('flocker', token=privateData['github']['token']))

rebuild('flocker_bb.boxes')
rebuild('flocker_bb.github')

from flocker_bb.boxes import FlockerWebStatus as WebStatus
from buildbot.status.web import authz
from buildbot.status.web.auth import BasicAuth
from twisted.python.util import sibpath
import jinja2


authz_cfg = authz.Authz(
    auth=BasicAuth([(USER, PASSWORD)]),

    # The "auth" value lines up with the `auth` keyword argument above!
    forceBuild='auth',
    forceAllBuilds='auth',
    stopBuild='auth',

    # Leave all this stuff disabled for now, but maybe enable it with "auth"
    # later.
    gracefulShutdown=False,
    pingBuilder=False,
    stopAllBuilds=False,
    cancelPendingBuild=False,
)
c['status'].append(WebStatus(
    http_port=80, authz=authz_cfg,
    public_html=sibpath(__file__, 'public_html'),
    jinja_loaders=[jinja2.FileSystemLoader(sibpath(__file__, 'templates'))],
    change_hook_dialects={'github': True}))

rebuild('flocker_bb.zulip_status')
from flocker_bb.zulip_status import createZulipStatus
from twisted.internet import reactor

if 'zulip' in privateData:
    ZULIP_BOT = privateData['zulip']['user']
    ZULIP_KEY = privateData['zulip']['password']
    c['status'].append(createZulipStatus(reactor, ZULIP_BOT, ZULIP_KEY))

####### PROJECT IDENTITY

# the 'title' string will appear at the top of this buildbot
# installation's html.WebStatus home page (linked to the
# 'titleURL') and is embedded in the title of the waterfall HTML page.

c['title'] = "ClusterHQ"
c['titleURL'] = "http://www.clusterhq.com/"

# the 'buildbotURL' string should point to the location where the buildbot's
# internal web server (usually the html.WebStatus page) is visible. This
# typically uses the port number set in the Waterfall 'status' entry, but
# with an externally-visible host name which the buildbot cannot figure out
# without some help.

c['buildbotURL'] = "http://%s/" % (privateData['buildmaster']['host'],)

####### DB URL

# This specifies what database buildbot uses to store change and scheduler
# state.  You can leave this at its default for all but the largest
# installations.
c['db_url'] = "sqlite:///" + sibpath(__file__, "data/state.sqlite")
