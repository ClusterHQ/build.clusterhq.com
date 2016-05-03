from urllib import quote

from buildbot.steps.shell import ShellCommand, SetPropertyFromCommand
from buildbot.process.properties import Interpolate, Property, renderer
from buildbot.steps.python_twisted import Trial
from buildbot.steps.trigger import Trigger
from buildbot.steps.transfer import StringDownload
from buildbot.interfaces import IBuildStepFactory

from ..steps import (
    virtualenvBinary,
    GITHUB,
    buildbotURL,
    MasterWriteFile, asJSON,
    pip,
    flockerBranch,
    resultPath, resultURL,
    slave_environ,
    )

# FIXME
from flocker_bb.builders.flocker import (
    check_version, installDependencies, _flockerTests, getFlockerFactory)


from characteristic import attributes, Attribute


def dotted_version(version):
    @renderer
    def render(props):
        return (props.render(version)
                .addCallback(lambda v: v.replace('-', '.')
                                        .replace('_', '.')
                                        .replace('+', '.')))
    return render


def quoted_version(version):
    @renderer
    def render(props):
        return props.render(version).addCallback(quote)
    return render


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

    url = Interpolate(
            'https://s3.amazonaws.com/clusterhq-dev-archive/vagrant/'  # noqa
            '%(kw:box)s/flocker-%(kw:box)s-%(kw:quoted_version)s.box',
            box=box, quoted_version=quoted_version(Property('version')))

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
                    "url": url,
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


def run_acceptance_tests(configuration):
    factory = getFlockerFactory('python2.7')

    factory.addSteps(installDependencies())

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
            # Typicall acceptance tests runs take <30 m.
            # Assume something is wrong, if it takes more than twice that.
            'maxTime': 60*60,
            # Allow 5 minutes for acceptance test runner to shutdown gracefully
            # In particular, this allows it to clean up the VMs it spawns.
            'sigtermTime': 5*60,
            'logfiles': {
                'run-acceptance-tests.log': 'run-acceptance-tests.log',
                'remote_logs.log': 'remote_logs.log',
            },
        },
        tests=[],
        trial=[
            virtualenvBinary('python'),
            Interpolate('%(prop:builddir)s/build/admin/run-acceptance-tests'),
            '--distribution', configuration.distribution,
            '--provider', configuration.provider,
            '--dataset-backend', configuration.dataset_backend,
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
    # Vagrant doesn't take a distribution.
    Attribute('distribution', default_value=None),
    Attribute('_dataset_backend'),
    Attribute('variants', default_factory=set),
])
class AcceptanceConfiguration(object):
    """
    Configuration for an acceptance test run.

    :ivar provider: The provider to use.
    :ivar distribution: The distribution to use.
    :ivar dataset_backend: The dataset backend to use.
    :ivar variants: The variants to use.
    """

    @property
    def builder_name(self):
        return '/'.join(
            ['flocker', 'acceptance',
             self.provider,
             self.distribution,
             self.dataset_backend,
             ] + sorted(self.variants))

    @property
    def builder_directory(self):
        return self.builder_name.replace('/', '-')

    @property
    def dataset_backend(self):
        if self._dataset_backend == 'native':
            return self.provider
        return self._dataset_backend

    @property
    def slave_class(self):
        return 'aws/centos-7'


ACCEPTANCE_CONFIGURATIONS = [
    AcceptanceConfiguration(provider='aws',
                            distribution='rhel-7.2',
                            dataset_backend='native')
]


# Too many simultaneous builds will hit AWS limits, but
# too few will make tests painfully slow. We need to find
# a compromise between these two variables. See FLOC-3263.
aws_lock = MasterLock('aws-lock', maxCount=3)
ACCEPTANCE_LOCKS = {
    'aws': [aws_lock.access("counting")],
}


def getBuilders(slavenames):
    builders = []
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
    configuration.builder_name
    for configuration in ACCEPTANCE_CONFIGURATIONS
]

from ..steps import MergeForward, report_expected_failures_parameter

from .flocker import OMNIBUS_DISTRIBUTIONS


def getSchedulers():
    schedulers = [
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
    ]
    for distribution in OMNIBUS_DISTRIBUTIONS:
        builders = [
            configuration.builder_name
            for configuration in ACCEPTANCE_CONFIGURATIONS
            if configuration.provider != 'vagrant'
            and configuration.distribution == distribution
        ]
        schedulers.append(
            Triggerable(
                name='trigger/built-packages/%s' % (distribution,),
                builderNames=builders,
                codebases={
                    "flocker": {"repository": GITHUB + b"/flocker"},
                },
            ))
    return schedulers
