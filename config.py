# -*- python -*-
# ex: set syntax=python:

from os.path import dirname
import sys
sys.path.insert(0, dirname(__file__))
del sys, dirname

# This is the dictionary that the buildmaster pays attention to. We also use
# a shorter alias to save typing.
c = BuildmasterConfig = {}

from twisted.python.filepath import FilePath

from flocker_bb import privateData
# Some credentials
USER = privateData['auth']['user'].encode("utf-8")
PASSWORD = privateData['auth']['password'].encode("utf-8")

from flocker_bb.zulip import createZulip, ZulipLogger
from twisted.internet import reactor

if 'zulip' in privateData:
    ZULIP_BOT = privateData['zulip']['user']
    ZULIP_KEY = privateData['zulip']['password']
    zulip = createZulip(reactor, ZULIP_BOT, ZULIP_KEY)

    ZulipLogger(zulip=zulip, stream="BuildBot - Operation").start()


####### BUILDSLAVES

# 'slavePortnum' defines the TCP port to listen on for connections from slaves.
# This must match the value configured into the buildslaves (with their
# --master option)
c['slavePortnum'] = 9989

from flocker_bb.password import generate_password
from flocker_bb.ec2_buildslave import EC2BuildSlave
from buildbot.buildslave import BuildSlave

cloudInit = FilePath(__file__).sibling("slave").child("cloud-init.sh").getContent()

c['slaves'] = []
SLAVENAMES = {}

for base, slaveConfig in privateData['slaves'].items():
    SLAVENAMES[base] = []
    if 'ami' in slaveConfig:
        for i in range(slaveConfig['slaves']):
            name = '%s-%d' % (base, i)
            password = generate_password(32)

            SLAVENAMES[base].append(name)
            c['slaves'].append(
                EC2BuildSlave(
                    name, password,
                    instance_type=slaveConfig['instance_type'],
                    build_wait_timeout=50*60,
                    image_name=slaveConfig['ami'],
                    region='us-west-2',
                    security_name='ssh',
                    keypair_name='hybrid-master',
                    identifier=privateData['aws']['identifier'],
                    secret_identifier=privateData['aws']['secret_identifier'],
                    user_data=cloudInit % {
                        "github_token": privateData['github']['token'],
                        "coveralls_token": privateData['coveralls']['token'],
                        "name": name,
                        "base": base,
                        "password": password,
                        'buildmaster_host': privateData['buildmaster']['host'],
                        'buildmaster_port': c['slavePortnum'],
                        },
                    keepalive_interval=60,
                    tags={
                        'Image': slaveConfig['ami'],
                        'Class': base,
                        'BuildMaster': privateData['buildmaster']['host'],
                        },
                    ))
    else:
        for i, password in enumerate(slaveConfig['passwords']):
            name = '%s-%d' % (base, i)
            SLAVENAMES[base].append(name)
            c['slaves'].append(BuildSlave(name, password=password))



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

from flocker_bb.builders import flocker, maint, flocker_vagrant

c['builders'] = []
c['schedulers'] = []


def addBuilderModule(module):
    c['builders'].extend(module.getBuilders(SLAVENAMES))
    c['schedulers'].extend(module.getSchedulers())

addBuilderModule(flocker)
addBuilderModule(flocker_vagrant)
addBuilderModule(maint)


####### STATUS TARGETS

# 'status' is a list of Status Targets. The results of each build will be
# pushed to these targets. buildbot/status/*.py has a variety to choose from,
# including web pages, email senders, and IRC bots.

c['status'] = []

from flocker_bb.github import createGithubStatus
if privateData['github']['report_status']:
    c['status'].append(createGithubStatus('flocker', token=privateData['github']['token']))


from flocker_bb.monitoring import Monitor
c['status'].append(Monitor())

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


from flocker_bb.zulip_status import createZulipStatus
if 'zulip' in privateData:
    ZULIP_STREAM = privateData['zulip'].get('stream', u"BuildBot")
    CRITICAL_STREAM = privateData['zulip'].get('critical_stream',
                                               u"Engineering")
    c['status'].append(createZulipStatus(zulip, ZULIP_STREAM, CRITICAL_STREAM))

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


# Keep a bunch of build in memory rather than constantly re-reading them from disk.
c['buildCacheSize'] = 1000
# Cleanup old builds.
c['buildHorizon'] = 1000
