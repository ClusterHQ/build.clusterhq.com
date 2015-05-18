from buildbot.steps.shell import ShellCommand, SetPropertyFromCommand
from buildbot.process.properties import Interpolate, Property, renderer
from buildbot.steps.python_twisted import Trial
from buildbot.steps.trigger import Trigger
from buildbot.steps.transfer import StringDownload
from buildbot.interfaces import IBuildStepFactory

from ..steps import (
    buildVirtualEnv, virtualenvBinary,
    getFactory,
    GITHUB,
    buildbotURL,
    MasterWriteFile, asJSON,
    flockerBranch,
    resultPath, resultURL,
    slave_environ,
    )

# FIXME
from flocker_bb.builders.flocker import installDependencies, _flockerTests


from characteristic import attributes, Attribute


def dotted_version(version):
    @renderer
    def render(props):
        return (props.render(version)
                .addCallback(lambda v: v.replace('-', '.')
                                        .replace('_', '.')
                                        .replace('+', '.')))
    return render


def getFlockerFactory():
    factory = getFactory("flocker", useSubmodules=False, mergeForward=True)
    factory.addSteps(buildVirtualEnv("python2.7", useSystem=True))
    factory.addSteps(installDependencies())
    return factory


def destroy_box(path):
    """
    Step that destroys the vagrant boxes at the given path.

    :return BuildStep:
    """
    return ShellCommand(
        name='destroy-boxes',
        description=['destroy', 'boxes'],
        descriptionDone=['destroy', 'boxes'],
        command=['vagrant', 'destroy', '-f'],
        workdir=path,
        alwaysRun=True,
        haltOnFailure=False,
        flunkOnFailure=False,
    )


def buildVagrantBox(box, add=True):
    """
    Build a flocker base box.

    @param box: Name of box to build.
    @param add: L{bool} indicating whether the box should be added locally.
    """
    steps = [
        SetPropertyFromCommand(
            command=["python", "setup.py", "--version"],
            name='check-version',
            description=['checking', 'version'],
            descriptionDone=['checking', 'version'],
            property='version'
        ),
        ShellCommand(
            name='build-base-box',
            description=['building', 'base', box, 'box'],
            descriptionDone=['build', 'base', box, 'box'],
            command=[
                virtualenvBinary('python'),
                'admin/build-vagrant-box',
                '--box', box,
                '--branch', flockerBranch,
                '--build-server', buildbotURL,
            ],
            haltOnFailure=True,
        ),
    ]

    steps.append(ShellCommand(
        name='upload-base-box',
        description=['uploading', 'base', box, 'box'],
        descriptionDone=['upload', 'base', box, 'box'],
        command=[
            '/bin/s3cmd',
            'put',
            Interpolate(
                'vagrant/%(kw:box)s/flocker-%(kw:box)s-%(prop:version)s.box',
                box=box),
            Interpolate(
                's3://clusterhq-dev-archive/vagrant/%(kw:box)s/',
                box=box),
        ],
    ))
    steps.append(MasterWriteFile(
        name='write-base-box-metadata',
        description=['writing', 'base', box, 'box', 'metadata'],
        descriptionDone=['write', 'base', box, 'box', 'metadata'],
        path=resultPath('vagrant', discriminator="flocker-%s.json" % box),
        content=asJSON({
            "name": "clusterhq/flocker-%s" % (box,),
            "description": "Test clusterhq/flocker-%s box." % (box,),
            'versions': [{
                "version": dotted_version(Property('version')),
                "providers": [{
                    "name": "virtualbox",
                    "url": Interpolate(
                        'https://s3.amazonaws.com/clusterhq-dev-archive/vagrant/'  # noqa
                        '%(kw:box)s/flocker-%(kw:box)s-%(prop:version)s.box',
                        box=box),
                }]
            }]
        }),
        urls={
            Interpolate('%(kw:box)s box', box=box):
            resultURL('vagrant', discriminator="flocker-%s.json" % box),
        }
    ))

    if add:
        steps.append(ShellCommand(
            name='add-base-box',
            description=['adding', 'base', box, 'box'],
            descriptionDone=['add', 'base', box, 'box'],
            command=['vagrant', 'box', 'add',
                     '--force',
                     Interpolate('vagrant/%(kw:box)s/flocker-%(kw:box)s.json',
                                 box=box)
                     ],
            haltOnFailure=True,
        ))

    return steps


def buildDevBox():
    """
    Build a vagrant dev box.
    """
    factory = getFlockerFactory()

    # We have to insert this before the first step, so we don't
    # destroy the vagrant meta-data. Normally .addStep adapts
    # to IBuildStepFactory.
    factory.steps.insert(0, IBuildStepFactory(
        destroy_box(path='build/vagrant/dev')))

    factory.addSteps(buildVagrantBox('dev', add=True))

    factory.addStep(ShellCommand(
        name='start-dev-box',
        description=['starting', 'dev', 'box'],
        descriptionDone=['start', 'dev', 'box'],
        command=['vagrant', 'up'],
        haltOnFailure=True,
        ))

    factory.addStep(ShellCommand(
        name='run-tox',
        description=['running', 'tox'],
        descriptionDone=['run', 'tox'],
        command=['vagrant', 'ssh', '--', 'cd /vagrant; tox'],
        haltOnFailure=True,
        ))

    factory.addStep(ShellCommand(
        name='run-tox-root',
        description=['running', 'tox', 'as', 'root'],
        descriptionDone=['run', 'tox', 'as', 'root'],
        command=['vagrant', 'ssh', '--', 'cd /vagrant; sudo tox -e py27'],
        haltOnFailure=True,
        ))

    factory.addStep(ShellCommand(
        name='destroy-dev-box',
        description=['destroy', 'dev', 'box'],
        descriptionDone=['destroy', 'dev', 'box'],
        command=['vagrant', 'destroy', '-f'],
        alwaysRun=True,
        ))

    return factory


def buildTutorialBox():
    factory = getFlockerFactory()

    # We have to insert this before the first step, so we don't
    # destroy the vagrant meta-data. Normally .addStep adapts
    # to IBuildStepFactory.
    factory.steps.insert(0, IBuildStepFactory(
        destroy_box(path='build/vagrant/tutorial')))

    factory.addSteps(buildVagrantBox('tutorial', add=True))
    factory.addStep(Trigger(
        name='trigger-vagrant-tests',
        schedulerNames=['trigger/built-vagrant-box/flocker-tutorial'],
        set_properties={
            # lint_revision is the commit that was merged against,
            # if we merged forward, so have the triggered build
            # merge against it as well.
            'merge_target': Property('lint_revision')
        },
        updateSourceStamp=True,
        waitForFinish=False,
        ))
    return factory


def run_acceptance_tests(configuration):
    factory = getFlockerFactory()

    if configuration.provider == 'vagrant':
        # We have to insert this before the first step, so we don't
        # destroy the vagrant meta-data. Normally .addStep adapts
        # to IBuildStepFactory.
        factory.steps.insert(0, IBuildStepFactory(
            destroy_box(path='build/admin/vagrant-acceptance-targets/%s'
                             % configuration.distribution)))

    factory.addSteps(_flockerTests(
        kwargs={
            'trialMode': [],
            # Allow 5 minutes for acceptance test runner to shutdown gracefully
            # In particular, this allows it to clean up the VMs it spawns.
            'sigtermTime': 5*60,
        },
        tests=[],
        trial=[
            virtualenvBinary('python'),
            Interpolate('%(prop:builddir)s/build/admin/run-acceptance-tests'),
            '--distribution', configuration.distribution,
            '--provider', configuration.provider,
            '--branch', flockerBranch,
            '--build-server', buildbotURL,
            '--config-file', Interpolate("%(kw:home)s/acceptance.yml",
                                         home=slave_environ("HOME")),
        ] + [
            ['--variant', variant]
            for variant in configuration.variants
        ],
    ))
    return factory


VAGRANTFILE_TEMPLATE = """\
# -*- mode: ruby -*-
# vi: set ft=ruby :

# This requires Vagrant 1.6.2 or newer (earlier versions can't reliably
# configure the Fedora 20 network stack).
Vagrant.require_version ">= 1.6.2"


# Vagrantfile API/syntax version. Don't touch unless you know what you're doing
VAGRANTFILE_API_VERSION = "2"

Vagrant.configure(VAGRANTFILE_API_VERSION) do |config|
  config.vm.box = "clusterhq/flocker-%(kw:box)s"
  config.vm.box_version = "= %(kw:version)s"
  config.vm.box_url = "%(kw:buildbotURL)sresults/vagrant/%(kw:branch)s/flocker-%(kw:box)s.json"  # noqa
end
"""


def test_installed_package(box):
    factory = getFlockerFactory()

    factory.addStep(
        destroy_box(path='test'))

    factory.addStep(SetPropertyFromCommand(
        command=["python", "setup.py", "--version"],
        name='check-version',
        description=['checking', 'version'],
        descriptionDone=['checking', 'version'],
        property='version'
    ))
    factory.addStep(StringDownload(
        Interpolate(
            VAGRANTFILE_TEMPLATE,
            version=dotted_version(Property('version')),
            buildbotURL=buildbotURL, branch=flockerBranch, box=box),
        'Vagrantfile',
        workdir='test',
        name='init-%s-box' % (box,),
        description=['initializing', box, 'box'],
        descriptionDone=['initialize', box, 'box'],
        ))
    factory.addStep(ShellCommand(
        name='start-tutorial-box',
        description=['starting', box, 'box'],
        descriptionDone=['start', box, 'box'],
        command=['vagrant', 'up'],
        workdir='test',
        haltOnFailure=True,
        ))
    factory.addStep(Trial(
        trial=['vagrant', 'ssh', '--', 'sudo', '/opt/flocker/bin/trial'],
        # Set lazylogfiles, so that trial.log isn't captured
        # Trial is being run remotely, so it isn't available
        lazylogfiles=True,
        testpath=None,
        tests='flocker',
        workdir='test',
    ))
    factory.addStep(ShellCommand(
        name='destroy-%s-box' % (box,),
        description=['destroy', box, 'box'],
        descriptionDone=['destroy', box, 'box'],
        command=['vagrant', 'destroy', '-f'],
        workdir='test',
        alwaysRun=True,
        ))
    return factory


from buildbot.config import BuilderConfig
from buildbot.schedulers.basic import AnyBranchScheduler
from buildbot.schedulers.forcesched import (
    CodebaseParameter, StringParameter, ForceScheduler, FixedParameter)
from buildbot.schedulers.triggerable import Triggerable
from buildbot.changes.filter import ChangeFilter


from ..steps import idleSlave


from buildbot.locks import MasterLock


# Dictionary mapping providers for acceptence testing to a list of
# sets of variants to test on each provider.
@attributes([
    Attribute('provider'),
    # Vagrant doesn't take a distrubtion.
    Attribute('distribution', default_value=None),
    Attribute('variants', default_factory=set),
])
class AcceptanceConfiguration(object):
    """
    Configuration for an acceptance test run.

    :ivar provider: The provider to use.
    :ivar distribution: The distribution to use.
    :ivar variants: The variants to use.
    """

    @property
    def builder_name(self):
        return '/'.join(
            ['flocker', 'acceptance',
             self.provider,
             self.distribution]
            + sorted(self.variants))

    @property
    def builder_directory(self):
        return self.builder_name.replace('/', '-')

    @property
    def slave_class(self):
        if self.provider == 'vagrant':
            return 'fedora-vagrant'
        else:
            return 'centos-7'


ACCEPTANCE_CONFIGURATIONS = [
    AcceptanceConfiguration(
        provider='vagrant', distribution='fedora-20'),
    AcceptanceConfiguration(
        provider='rackspace', distribution='fedora-20'),
    AcceptanceConfiguration(
        provider='rackspace', distribution='ubuntu-14.04'),
    AcceptanceConfiguration(
        provider='rackspace', distribution='centos-7'),
    AcceptanceConfiguration(
        provider='rackspace', distribution='centos-7',
        variants={'docker-head'}),
    AcceptanceConfiguration(
        provider='rackspace', distribution='centos-7',
        variants={'zfs-testing'}),
]


rackspace_lock = MasterLock("rackspace-lock", maxCount=12)
ACCEPTANCE_LOCKS = {
    # 256000M available ram, 8192M per node, 2 nodes per test
    # We allocate slightly less to avoid using all the RAM.
    'rackspace': [rackspace_lock.access("counting")],
}


def getBuilders(slavenames):
    builders = [
        BuilderConfig(name='flocker-vagrant-dev-box',
                      slavenames=slavenames['fedora-vagrant'],
                      category='flocker',
                      factory=buildDevBox(),
                      nextSlave=idleSlave),
        BuilderConfig(name='flocker-vagrant-tutorial-box',
                      slavenames=slavenames['fedora-vagrant'],
                      category='flocker',
                      factory=buildTutorialBox(),
                      nextSlave=idleSlave),
        BuilderConfig(name='flocker/installed-package/fedora-20',
                      builddir='flocker-installed-package-fedora-20',
                      slavenames=slavenames['fedora-vagrant'],
                      category='flocker',
                      factory=test_installed_package(
                          box='tutorial'),
                      nextSlave=idleSlave),
        ]
    for configuration in ACCEPTANCE_CONFIGURATIONS:
        builders.append(BuilderConfig(
            name=configuration.builder_name,
            builddir=configuration.builder_directory,
            slavenames=slavenames[configuration.slave_class],
            category='flocker',
            factory=run_acceptance_tests(configuration),
            locks=ACCEPTANCE_LOCKS.get(configuration.provider, []),
            nextSlave=idleSlave))
    return builders

BUILDERS = [
    'flocker-vagrant-dev-box',
    'flocker-vagrant-tutorial-box',
    'flocker/installed-package/fedora-20',
] + [
    configuration.builder_name
    for configuration in ACCEPTANCE_CONFIGURATIONS
]

from ..steps import MergeForward, report_expected_failures_parameter


def getSchedulers():
    schedulers = [
        AnyBranchScheduler(
            name="flocker-vagrant",
            treeStableTimer=5,
            builderNames=['flocker-vagrant-dev-box'],
            codebases={
                "flocker": {"repository": GITHUB + b"/flocker"},
            },
            change_filter=ChangeFilter(
                branch_fn=lambda branch:
                    (MergeForward._isMaster(branch)
                        or MergeForward._isRelease(branch)),
            )
        ),
        ForceScheduler(
            name="force-flocker-vagrant",
            codebases=[
                CodebaseParameter(
                    "flocker",
                    branch=StringParameter(
                        "branch", default="master", size=80),
                    repository=FixedParameter("repository",
                                              default=GITHUB + b"/flocker"),
                ),
            ],
            properties=[
                report_expected_failures_parameter,
            ],
            builderNames=BUILDERS,
        ),
        Triggerable(
            name='trigger/built-vagrant-box/flocker-tutorial',
            builderNames=[
                'flocker/installed-package/fedora-20',
            ] + [
                configuration.builder_name
                for configuration in ACCEPTANCE_CONFIGURATIONS
                if configuration.provider == 'vagrant'
            ],
            codebases={
                "flocker": {"repository": GITHUB + b"/flocker"},
            },
        ),
    ]
    for distribution in ('fedora-20', 'centos-7', 'ubuntu-14.04'):
        builders = [
            configuration.builder_name
            for configuration in ACCEPTANCE_CONFIGURATIONS
            if configuration.provider != 'vagrant'
            and configuration.distribution == distribution
        ]
        if distribution == 'fedora-20':
            builders.append('flocker-vagrant-tutorial-box')
        schedulers.append(
            Triggerable(
                name='trigger/built-packages/%s' % (distribution,),
                builderNames=builders,
                codebases={
                    "flocker": {"repository": GITHUB + b"/flocker"},
                },
            ))
    return schedulers
