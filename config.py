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

from flocker_bb.zulip import createZulip
from twisted.internet import reactor

if 'zulip' in privateData:
    ZULIP_BOT = privateData['zulip']['user']
    ZULIP_KEY = privateData['zulip']['password']
    zulip = createZulip(reactor, ZULIP_BOT, ZULIP_KEY)


def maybeAddManhole(config, privateData):
    try:
        manhole = privateData['manhole']
    except KeyError:
        return

    from tempfile import NamedTemporaryFile

    from buildbot.manhole import AuthorizedKeysManhole

    with NamedTemporaryFile(delete=False) as authorized_keys:
        authorized_keys.write(
            "\n".join(manhole['authorized_keys']) + "\n"
        )

    c['manhole'] = AuthorizedKeysManhole(manhole['port'], authorized_keys.name)

maybeAddManhole(c, privateData)


# 'slavePortnum' defines the TCP port to listen on for connections from slaves.
# This must match the value configured into the buildslaves (with their
# --master option)
c['slavePortnum'] = 9989

from flocker_bb.password import generate_password
from flocker_bb.ec2 import rackspace_slave, ec2_slave
from buildbot.buildslave import BuildSlave

cloudInit = FilePath(__file__).sibling("slave").child(
    "cloud-init.sh").getContent()

c['slaves'] = []
SLAVENAMES = {}


def get_cloud_init(name, base, password, provider, privateData, slavePortnum):
    """
    :param bytes name: The name of the buildslave.
    :param bytes base: The name of image used for the buildslave.
    :param bytes password: The password that the buildslave will use to
       authenticate with the buildmaster.
    :param bytes provider: The cloud ``provider`` hosting the buildslave. This
        is added to an environment variable, so that cloud ``provider``
        specific tests know which cloud authentication plugin to load and which
        credentials to load from the credentials file.
    :param dict privateData: The non-slave specific keys and values from the
        buildbot ``config.yml`` file.
    :parma int slavePortnum: The TCP port number on the buildmaster to which
        the buildslave will connect.
    :returns: The ``bytes`` of a ``cloud-init.sh`` script which can be supplied
       as ``userdata`` when creating an on-demand buildslave.
    """
    return cloudInit % {
        "github_token": privateData['github']['token'],
        "name": name,
        "base": base,
        "password": password,
        "FLOCKER_FUNCTIONAL_TEST_CLOUD_PROVIDER": provider,
        'buildmaster_host': privateData['buildmaster']['host'],
        'buildmaster_port': slavePortnum,
        'acceptance.yml': privateData['acceptance'].get('config', ''),
        'acceptance-ssh-key': privateData['acceptance'].get('ssh-key', ''),
    }


for base, slaveConfig in privateData['slaves'].items():
    SLAVENAMES[base] = []
    if "openstack-image" in slaveConfig:
        # Give this multi-slave support like the EC2 implementation below.
        # FLOC-1907
        password = generate_password(32)

        SLAVENAMES[base].append(base)
        # Factor the repetition out of this section and the ec2_slave call
        # below.  Maybe something like ondemand_slave(rackspace_driver, ...)
        # FLOC-1908
        slave = rackspace_slave(
            name=base,
            password=password,
            config=slaveConfig,
            credentials=privateData['rackspace'],
            user_data=get_cloud_init(
                base, base, password,
                provider="openstack",
                privateData=privateData,
                slavePortnum=c['slavePortnum'],
            ),
            build_wait_timeout=50*60,
            keepalive_interval=60,
            buildmaster=privateData['buildmaster']['host'],
            max_builds=slaveConfig.get('max_builds'),
        )
        c['slaves'].append(slave)
    elif 'ami' in slaveConfig:
        for index in range(slaveConfig['slaves']):
            name = '%s/%d' % (base, index)
            password = generate_password(32)

            SLAVENAMES[base].append(name)
            slave = ec2_slave(
                name=name,
                password=password,
                config=slaveConfig,
                credentials=privateData['aws'],
                user_data=get_cloud_init(
                    name, base, password,
                    provider="aws",
                    privateData=privateData,
                    slavePortnum=c['slavePortnum'],
                ),
                region='us-west-2',
                keypair_name='hybrid-master',
                security_name='ssh',
                build_wait_timeout=50*60,
                keepalive_interval=60,
                buildmaster=privateData['buildmaster']['host'],
                max_builds=slaveConfig.get('max_builds'),
            )
            c['slaves'].append(slave)
    else:
        for index, password in enumerate(slaveConfig['passwords']):
            name = '%s/%d' % (base, index)
            SLAVENAMES[base].append(name)
            c['slaves'].append(BuildSlave(
                name, password=password,
                max_builds=slaveConfig.get('max_builds'),
            ))


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

from flocker_bb.builders import flocker, maint

c['builders'] = []
c['schedulers'] = []


def addBuilderModule(module):
    c['builders'].extend(module.getBuilders(SLAVENAMES))
    c['schedulers'].extend(module.getSchedulers())

addBuilderModule(flocker)
addBuilderModule(maint)


# 'status' is a list of Status Targets. The results of each build will be
# pushed to these targets. buildbot/status/*.py has a variety to choose from,
# including web pages, email senders, and IRC bots.

failing_builders = frozenset(privateData.get('failing_builders', ()))

c['status'] = []

from flocker_bb.github import createGithubStatus
if privateData['github']['report_status']:
    c['status'].append(createGithubStatus(
        'flocker', token=privateData['github']['token'],
        failing_builders=failing_builders,
        ))


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
    pingBuilder='auth',
    stopAllBuilds=False,
    cancelPendingBuild='auth',
    cancelAllPendingBuilds=False,
)
c['status'].append(WebStatus(
    http_port=80, authz=authz_cfg,
    public_html=sibpath(__file__, 'public_html'),
    jinja_loaders=[jinja2.FileSystemLoader(sibpath(__file__, 'templates'))],
    change_hook_dialects={'github': True},
    failing_builders=failing_builders,
))


from flocker_bb.zulip_status import createZulipStatus
if 'zulip' in privateData:
    ZULIP_STREAM = privateData['zulip'].get('stream', u"BuildBot")
    CRITICAL_STREAM = privateData['zulip'].get('critical_stream',
                                               u"Engineering")
    c['status'].append(createZulipStatus(
        zulip, ZULIP_STREAM, CRITICAL_STREAM,
        failing_builders=failing_builders,
    ))


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

# This specifies what database buildbot uses to store change and scheduler
# state.  You can leave this at its default for all but the largest
# installations.
c['db_url'] = "sqlite:///" + sibpath(__file__, "data/state.sqlite")


# Keep a bunch of build in memory rather than constantly re-reading them from
# disk.
c['buildCacheSize'] = 1000
# Cleanup old builds.
c['buildHorizon'] = 1000
