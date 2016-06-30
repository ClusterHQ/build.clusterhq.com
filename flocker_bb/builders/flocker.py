# Copyright ClusterHQ Inc.  See LICENSE file for details.
from os import path

from characteristic import attributes, Attribute
from buildbot.steps.shell import ShellCommand, SetPropertyFromCommand
from buildbot.steps.python_twisted import Trial
from buildbot.steps.python import Sphinx
from buildbot.steps.transfer import DirectoryUpload, FileUpload
from buildbot.steps.master import MasterShellCommand
from buildbot.steps.source.git import Git
from buildbot.process.properties import Interpolate, Property
from buildbot.steps.trigger import Trigger
from buildbot.config import error
from buildbot.locks import MasterLock, SlaveLock
from buildbot.changes.filter import ChangeFilter
from buildbot.config import BuilderConfig
from buildbot.schedulers.basic import AnyBranchScheduler
from buildbot.schedulers.forcesched import (
    CodebaseParameter,
    FixedParameter,
    ForceScheduler,
    StringParameter,
)

from ..steps import (
    BranchType,
    GITHUB,
    TWISTED_GIT,
    VIRTUALENV_DIR,
    buildVirtualEnv,
    flockerRevision,
    getBranchType,
    getFactory,
    idleSlave,
    isMasterBranch,
    isReleaseBranch,
    pip,
    report_expected_failures_parameter,
    resultPath, resultURL,
    virtualenvBinary,
)

# This is where temporary files associated with a build will be dumped.
TMPDIR = Interpolate(b"%(prop:workdir)s/tmp-%(prop:buildnumber)s")


# Dictionary mapping providers for storage backend testing to a list of
# sets of variants to test on each provider.
@attributes([
    Attribute('provider'),
    Attribute('distribution'),
])
class StorageConfiguration(object):
    """
    Configuration for storage backend test run.

    :ivar provider: The storage provider to use.
    :ivar distribution: The distribution to use.
    :cvar _locks: Dictionary mapping provider names to locks.
    """

    _locks = {}

    @property
    def builder_name(self):
        return '/'.join(
            ['flocker', 'functional', self.provider, self.distribution,
             'storage-driver'])

    @property
    def builder_directory(self):
        return self.builder_name.replace('/', '-')

    @property
    def slave_class(self):
        return '/'.join([self.provider, self.distribution])

    @property
    def driver(self):
        if self.provider == 'aws':
            return 'flocker/node/agents/ebs.py'
        elif self.provider in ('rackspace', 'redhat-openstack'):
            return 'flocker/node/agents/cinder.py'
        raise NotImplementedError("Unsupported provider %s" % (self.provider,))

    @property
    def locks(self):
        # We use a shared dictionary here, since locks are compared via
        # identity, not by name.
        lock_name = '/'.join(['functional', 'api', self.provider])

        # This should be in the config file (FLOC-2025)
        # Allow up to 2 AWS functional storage driver tests to run in parallel.
        # This is a temporary fix to get around test wait time being
        # queued up to run.
        # OpenStack tests have not experienced long queued wait times.
        # So, leave the max count at 1.
        if self.provider == 'aws':
            maxCount = 2
        elif self.provider in ('rackspace', 'redhat-openstack'):
            maxCount = 1
        else:
            raise NotImplementedError("Unsupported provider %s" %
                                      (self.provider,))
        lock = self._locks.setdefault(
            self.provider, MasterLock(lock_name, maxCount=maxCount))
        return [lock.access("counting")]


def getFlockerFactory(python):
    factory = getFactory("flocker", useSubmodules=False, mergeForward=True)
    factory.addSteps(buildVirtualEnv(python, useSystem=True))
    return factory


def installDependencies():
    return [
        pip("dependencies", ["."]),
        pip("extras", ["-e", ".[dev]"]),
        ]


def _flockerTests(kwargs, tests=None, env=None, trial=None):
    if env is None:
        env = {}
    env[b"PATH"] = [Interpolate(path.join(VIRTUALENV_DIR, "bin")), "${PATH}"]
    if tests is None:
        tests = [b"flocker"]
    if trial is None:
        trial = [virtualenvBinary('trial')]
    return [
        ShellCommand(command=[b"mkdir", TMPDIR],
                     description=["creating", "TMPDIR"],
                     descriptionDone=["create", "TMPDIR"],
                     name="create-TMPDIR"),
        Trial(
            trial=trial,
            tests=tests,
            testpath=None,
            workdir=TMPDIR,
            env=env,
            **kwargs),
        ShellCommand(command=[b"rm", b"-rf", TMPDIR],
                     alwaysRun=True,
                     description=["removing", "TMPDIR"],
                     descriptionDone=["remove", "TMPDIR"],
                     name="remove-TMPDIR"),
        ]


def installTwistedTrunk():
    steps = []
    steps.append(Git(
        repourl=TWISTED_GIT,
        mode='full', method='fresh',
        codebase='twisted', workdir='Twisted',
        alwaysUseLatest=True,
        ))
    steps.append(ShellCommand(
        name='install-twisted-trunk',
        description=['installing', 'twisted', 'trunk'],
        descriptionDone=['install', 'twisted', 'trunk'],
        command=[virtualenvBinary('pip'),
                 "install",
                 "--no-index", '--use-wheel',
                 "-f", "http://data.hybridcluster.net/python/",
                 "."
                 ],
        workdir='Twisted',
        haltOnFailure=True))
    return steps


def makeFactory(python, tests=None, twistedTrunk=False, env=None):
    """
    Make a new build factory which can do a flocker build.

    @param python: The basename of the Python executable which the resulting
        build factory is to use.  For example, C{"python2.6"}.
    @type python: L{bytes}

    @param twistedTrunk: Whether twisted trunk should be installed
    @type twistedTrunk: L{bool}
    """
    factory = getFlockerFactory(python=python)

    factory.addSteps(installDependencies())

    if twistedTrunk:
        factory.addSteps(installTwistedTrunk())

    factory.addSteps(_flockerTests(kwargs={}, tests=tests, env=env))

    return factory


def makeAdminFactory():
    """
    Make a new build factory which can do an admin build.
    """
    factory = getFlockerFactory(python=b"python2.7")
    factory.addSteps(installDependencies())

    factory.addStep(Trial(
        trial=[Interpolate(path.join(VIRTUALENV_DIR, "bin/trial"))],
        tests=[b'admin'],
        testpath=None,
        env={
            b"PATH": [Interpolate(path.join(VIRTUALENV_DIR, "bin")),
                      "${PATH}"],
            },
        ))

    return factory


def makeLintFactory():
    """
    Create and return a new build factory for linting the code.
    """
    factory = getFactory("flocker", useSubmodules=False, mergeForward=True)
    factory.addStep(ShellCommand(
        name='lint',
        description=["linting"],
        descriptionDone=["lint"],
        command=["tox", "-e", "lint"],
        workdir='build',
        flunkOnFailure=True,
        ))
    return factory


def sphinxBuild(builder, workdir=b"build/docs", **kwargs):
    """
    Build sphinx documentation.

    @param builder: Sphinx builder to use.
    @param path: Location of sphinx tree.
    """
    extraArgs = {'flunkOnWarnings': True, 'haltOnFailure': True}
    extraArgs.update(kwargs)
    return Sphinx(
        name="build-%s" % (builder,),
        description=["building", builder],
        descriptionDone=["build", builder],
        sphinx_builder=builder,
        sphinx_builddir=path.join("_build", builder),
        sphinx=[virtualenvBinary('sphinx-build'),
                '-d', "_build/doctree",
                ],
        workdir=workdir,
        env={
            b"PATH": [Interpolate(path.join(VIRTUALENV_DIR, "bin")),
                      "${PATH}"],
            },
        **extraArgs)


def makeInternalDocsFactory():
    factory = getFlockerFactory(python="python2.7")
    factory.addSteps(installDependencies())
    factory.addSteps(check_version())
    factory.addStep(sphinxBuild(
        "spelling", "build/docs",
        logfiles={'errors': '_build/spelling/output.txt'},
        haltOnFailure=False))
    factory.addStep(sphinxBuild(
        "linkcheck", "build/docs",
        logfiles={'errors': '_build/linkcheck/output.txt'},
        haltOnFailure=False,
        flunkOnWarnings=False,
        flunkOnFailure=False,
        warnOnFailure=True,
        ))
    factory.addStep(sphinxBuild("html", "build/docs"))
    factory.addStep(DirectoryUpload(
        b"docs/_build/html",
        resultPath('docs'),
        url=resultURL('docs'),
        name="upload-html",
        ))
    factory.addStep(MasterShellCommand(
        name='link-release-documentation',
        description=["linking", "release", "documentation"],
        descriptionDone=["link", "release", "documentation"],
        command=[
            "ln", '-nsf',
            resultPath('docs'),
            'doc-dev',
            ],
        doStepIf=isMasterBranch('flocker'),
        ))
    factory.addStep(MasterShellCommand(
        name='upload-release-documentation',
        description=["uploading", "release", "documentation"],
        descriptionDone=["upload", "release", "documentation"],
        command=[
            "s3cmd", "sync",
            '--verbose',
            '--delete-removed',
            '--no-preserve',
            # s3cmd needs a trailing slash.
            Interpolate("%(kw:path)s/", path=resultPath('docs')),
            Interpolate(
                "s3://%(kw:bucket)s/%(prop:version)s/",
                bucket='clusterhq-dev-docs',
            ),
        ],
        doStepIf=isReleaseBranch('flocker'),
    ))
    return factory


def createRepository(distribution, repository_path):
    steps = []
    flavour, version = distribution.split('-', 1)
    if flavour in ("fedora", "centos"):
        steps.append(MasterShellCommand(
            name='build-repo-metadata',
            description=["building", "repo", "metadata"],
            descriptionDone=["build", "repo", "metadata"],
            command=["createrepo_c", "."],
            path=repository_path,
            haltOnFailure=True))
    elif flavour in ("ubuntu", "debian"):
        steps.append(MasterShellCommand(
            name='build-repo-metadata',
            description=["building", "repo", "metadata"],
            descriptionDone=["build", "repo", "metadata"],
            # FIXME: Don't use shell here.
            command="dpkg-scanpackages --multiversion . | gzip > Packages.gz",
            path=repository_path,
            haltOnFailure=True))
    else:
        error("Unknown distritubtion %s in createRepository."
              % (distribution,))

    return steps


def makeOmnibusFactory(distribution):
    factory = getFlockerFactory(python="python2.7")
    factory.addSteps(installDependencies())
    factory.addSteps(check_version())
    factory.addStep(ShellCommand(
        name='build-sdist',
        description=["building", "sdist"],
        descriptionDone=["build", "sdist"],
        command=[
            virtualenvBinary('python'),
            "setup.py", "sdist",
            ],
        haltOnFailure=True))
    factory.addStep(ShellCommand(
        command=[
            virtualenvBinary('python'),
            'admin/build-package',
            '--destination-path', 'repo',
            '--distribution', distribution,
            Interpolate('/flocker/dist/Flocker-%(prop:version)s.tar.gz'),
            ],
        name='build-package',
        description=['building', 'package'],
        descriptionDone=['build', 'package'],
        haltOnFailure=True))

    repository_path = resultPath('omnibus', discriminator=distribution)

    factory.addStep(DirectoryUpload(
        'repo',
        repository_path,
        url=resultURL('omnibus', discriminator=distribution),
        name="upload-repo",
    ))
    factory.addSteps(createRepository(distribution, repository_path))

    return factory


def check_version():
    """
    Get the version of the package and store it in the ``version`` property.
    """
    return [
        SetPropertyFromCommand(
            command=[virtualenvBinary('python'), "setup.py", "--version"],
            name='check-version',
            description=['checking', 'version'],
            descriptionDone=['check', 'version'],
            property='version',
            env={
                # Ignore warnings
                # In particular, setuptools warns about normalization.
                # Normalizing '..' to '..' normalized_version, ..
                'PYTHONWARNINGS': 'ignore',
            },
        ),
    ]


def makeHomebrewRecipeCreationFactory():
    """Create the Homebrew recipe from a source distribution.

    This is separate to the recipe testing, to allow it to be done on a
    non-Mac platform.  Once complete, this triggers the Mac testing.
    """
    factory = getFlockerFactory(python="python2.7")
    factory.addSteps(installDependencies())
    factory.addSteps(check_version())

    # Create suitable names for files hosted on Buildbot master.

    sdist_file = Interpolate('Flocker-%(prop:version)s.tar.gz')
    sdist_path = resultPath('python',
                            discriminator=sdist_file)
    sdist_url = resultURL('python',
                          discriminator=sdist_file,
                          isAbsolute=True)

    recipe_file = Interpolate('Flocker%(kw:revision)s.rb',
                              revision=flockerRevision)
    recipe_path = resultPath(
        'homebrew', discriminator=recipe_file)
    recipe_url = resultURL(
        'homebrew', discriminator=recipe_file)

    # Build source distribution
    factory.addStep(ShellCommand(
        name='build-sdist',
        description=["building", "sdist"],
        descriptionDone=["build", "sdist"],
        command=[
            virtualenvBinary('python'),
            "setup.py", "sdist",
            ],
        haltOnFailure=True))

    # Upload source distribution to master
    factory.addStep(FileUpload(
        name='upload-sdist',
        slavesrc=Interpolate('dist/Flocker-%(prop:version)s.tar.gz'),
        masterdest=sdist_path,
        url=sdist_url,
    ))

    # Build Homebrew recipe from source distribution URL
    factory.addStep(ShellCommand(
        name='make-homebrew-recipe',
        description=["building", "recipe"],
        descriptionDone=["build", "recipe"],
        command=[
            virtualenvBinary('python'), "-m", "admin.homebrew",
            # We use the Git commit SHA for the version here, since
            # admin.homebrew doesn't handle the version generated by
            # arbitrary commits.
            "--flocker-version", flockerRevision,
            "--sdist", sdist_url,
            "--output-file", recipe_file],
        haltOnFailure=True))

    # Upload new .rb file to BuildBot master
    factory.addStep(FileUpload(
        name='upload-homebrew-recipe',
        slavesrc=recipe_file,
        masterdest=recipe_path,
        url=recipe_url,
    ))

    # Trigger the homebrew-test build
    factory.addStep(Trigger(
        name='trigger/created-homebrew',
        schedulerNames=['trigger/created-homebrew'],
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


def makeHomebrewRecipeTestFactory():
    """Test the Homebrew recipe on an OS X system."""

    factory = getFlockerFactory(python="python2.7")
    factory.addSteps(installDependencies())

    # Run testbrew script
    recipe_file = Interpolate('Flocker%(kw:revision)s.rb',
                              revision=flockerRevision)
    recipe_url = resultURL('homebrew',
                           isAbsolute=True,
                           discriminator=recipe_file)
    factory.addStep(ShellCommand(
        name='run-homebrew-test',
        description=["running", "homebrew", "test"],
        descriptionDone=["run", "homebrew", "test"],
        command=[
            virtualenvBinary('python'),
            b"admin/test-brew-recipe",
            b"--vmhost", b"192.168.169.100",
            b"--vmuser", b"ClusterHQVM",
            b"--vmpath", b"/Users/buildslave/Documents/Virtual Machines.localized/OS X 10.10.vmwarevm/OS X 10.10.vmx",  # noqa
            b"--vmsnapshot", b"homebrew-clean",
            recipe_url
            ],
        haltOnFailure=True))

    return factory


# A lock to prevent multiple functional tests running at the same time
functionalLock = SlaveLock('functional-tests')

OMNIBUS_DISTRIBUTIONS = [
    'ubuntu-14.04',
    'ubuntu-15.10',
    'ubuntu-16.04',
    'centos-7',
]


def getBuilders(slavenames):
    builders = []
    for distribution in OMNIBUS_DISTRIBUTIONS:
        builders.append(
            BuilderConfig(
                name='flocker-omnibus-%s' % (distribution,),
                slavenames=slavenames['aws/ubuntu-14.04'],
                category='flocker',
                factory=makeOmnibusFactory(
                    distribution=distribution,
                ),
                nextSlave=idleSlave,
                ))

    return builders

BUILDERS = [
    'flocker-omnibus-%s' % (dist,) for dist in OMNIBUS_DISTRIBUTIONS
]


def build_automatically(branch):
    """
    See http://docs.buildbot.net/current/manual/cfg-schedulers.html#id11

    Return a bool, whether the branch should be built after a push without
    being forced.
    """
    return getBranchType(branch) in (BranchType.master, BranchType.release)


def getSchedulers():
    return [
        AnyBranchScheduler(
            name="flocker",
            treeStableTimer=5,
            builderNames=BUILDERS,
            # Only build certain branches because problems arise when we build
            # many branches such as queues and request limits.
            change_filter=ChangeFilter(branch_fn=build_automatically),
            codebases={
                "flocker": {"repository": GITHUB + b"/flocker"},
            },
        ),
        ForceScheduler(
            name="force-flocker",
            codebases=[
                CodebaseParameter(
                    "flocker",
                    branch=StringParameter(
                        "branch", default="master", size=80),
                    repository=FixedParameter(
                        "repository", default=GITHUB + b"/flocker"),
                ),
            ],
            properties=[
                report_expected_failures_parameter,
            ],
            builderNames=BUILDERS,
            ),
    ]
