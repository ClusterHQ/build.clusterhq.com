# Copyright ClusterHQ Inc.  See LICENSE file for details.
from urllib import quote

from buildbot.config import BuilderConfig
from buildbot.schedulers.forcesched import (
    CodebaseParameter,
    FixedParameter,
    ForceScheduler,
    StringParameter,
)
from buildbot.schedulers.triggerable import Triggerable
from buildbot.process.properties import Interpolate, renderer
from buildbot.locks import MasterLock
from characteristic import attributes, Attribute

from flocker_bb.builders.flocker import (
    _flockerTests,
    getFlockerFactory,
    installDependencies,
)
from .flocker import OMNIBUS_DISTRIBUTIONS
from ..steps import (
    GITHUB,
    buildbotURL,
    flockerBranch,
    idleSlave,
    report_expected_failures_parameter,
    slave_environ,
    virtualenvBinary,
)


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


def run_acceptance_tests(configuration):
    factory = getFlockerFactory('python2.7')

    factory.addSteps(installDependencies())

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


def getSchedulers():
    schedulers = [
        ForceScheduler(
            name="force-flocker-acceptance",
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
            if configuration.distribution == distribution
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
