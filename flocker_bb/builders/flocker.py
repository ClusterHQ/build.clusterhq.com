from buildbot.steps.shell import ShellCommand, SetPropertyFromCommand
from buildbot.steps.python_twisted import Trial
from buildbot.steps.python import Sphinx
from buildbot.steps.transfer import (
    DirectoryUpload, FileUpload, StringDownload)
from buildbot.steps.master import MasterShellCommand
from buildbot.steps.source.git import Git
from buildbot.process.properties import Interpolate, Property
from buildbot.steps.trigger import Trigger
from buildbot.config import error
from buildbot.locks import MasterLock

from os import path

from characteristic import attributes, Attribute

from ..steps import (
    VIRTUALENV_DIR, buildVirtualEnv, virtualenvBinary,
    getFactory,
    GITHUB,
    TWISTED_GIT,
    pip,
    isMasterBranch, isReleaseBranch,
    resultPath, resultURL,
    flockerRevision,
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
        lock = self._locks.setdefault(
            self.provider, MasterLock(lock_name, maxCount=1))
        return [lock.access("counting")]


STORAGE_CONFIGURATIONS = [
    StorageConfiguration(
        provider='aws', distribution='ubuntu-14.04'),
    StorageConfiguration(
        provider='aws', distribution='centos-7'),
    StorageConfiguration(
        provider='rackspace', distribution='centos-7'),
    StorageConfiguration(
        provider='redhat-openstack', distribution='centos-7'),
]


def getFlockerFactory(python):
    factory = getFactory("flocker", useSubmodules=False, mergeForward=True)
    factory.addSteps(buildVirtualEnv(python, useSystem=True))
    return factory


def installDependencies():
    return [
        pip("dependencies", ["."]),
        pip("extras", ["Flocker[doc,dev,release]"]),
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


def _flockerCoverage():
    steps = _flockerTests({
        'python': [
            # Buildbot flattens this for us.
            # Unfortunately, Trial assumes that 'python' is a list of strings,
            # and checks for spaces in them. Interpolate isn't iterable, so
            # make it a list (which is, and doesn't have a " " in it.
            [virtualenvBinary('coverage')],
            b"run",
            b"--branch",
            b"--source", b"flocker",
            b"--rcfile", b"../build/.coveragerc",
            ]
        })
    # This needs to be before we delete the temporary directory.
    steps.insert(len(steps)-1,
        ShellCommand(  # noqa
            name='move-coverage',
            description=["moving", "coverage"],
            descriptionDone=["move", "coverage"],
            command=['cp', '.coverage', '../build/.coverage.original'],
            workdir=TMPDIR,
            haltOnFailure=True))
    steps += [
        StringDownload(
            '\n'.join([
                '[paths]',
                'sources =',
                '    flocker',
                '    /*/site-packages/flocker',
                '']),
            '.coveragerc-combine',
            name="download-coveragerc"),
        ShellCommand(
            command=[
                virtualenvBinary('coverage'),
                'combine',
                '--rcfile=.coveragerc-combine',
                ],
            name='rewrite-coverage',
            description=[b'Rewriting', b'coverage'],
            descriptionDone=[b'Rewrite', 'coverage'],
            ),
        ShellCommand(
            command=Interpolate(
                b"git diff --no-prefix %(prop:lint_revision)s..HEAD | "
                + path.join(VIRTUALENV_DIR, "bin/coverage-reporter")
                + b" --patch=stdin "
                + b"--coverage flocker"
                + b" --patch-level=0 "
                b"--coverage-file=.coverage --summarize "
                b"--annotate --annotate-dir change-coverage-annotations"),
            workdir=b"build",
            description=[b"Computing", b"change", b"coverage"],
            descriptionDone=[b"Compute", b"change", b"coverage"],
            name="change-coverage",
            ),
        DirectoryUpload(
            b"change-coverage-annotations",
            resultPath('change-coverage'),
            url=resultURL('change-coverage'),
            name="upload-coverage-annotations",
            ),
        ShellCommand(
            command=[
                virtualenvBinary('coverage'),
                b"html", b"-d", b"html-coverage",
                ],
            description=[b"generating", b"html", b"report"],
            descriptionDone=[b"generate", b"html", b"report"],
            name="coverage-report",
            ),
        DirectoryUpload(
            b"html-coverage",
            resultPath('complete-coverage'),
            url=resultURL('complete-coverage'),
            name="upload-coverage-html",
            ),
        ShellCommand(
            command=[
                virtualenvBinary('coveralls'),
                "--coveralls_yaml",
                Interpolate("%(prop:workdir)s/../coveralls.yml")],
            description=[b"uploading", b"to", b"coveralls"],
            descriptionDone=[b"upload", b"to", b"coveralls"],
            name="coveralls-upload",
            ),
        ]
    return steps


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


def installCoverage():
    return pip("coverage", [
         "coverage==3.7.1",
         "http://data.hybridcluster.net/python/coverage_reporter-0.01_hl0-py27-none-any.whl",  # noqa
         "python-coveralls==2.4.2",
    ])


def makeCoverageFactory():
    """
    Create and return a new build factory for checking test coverage.
    """
    factory = getFlockerFactory(python="python2.7")
    factory.addSteps(installDependencies())
    factory.addStep(installCoverage())
    factory.addSteps(_flockerCoverage())
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
    factory.addStep(SetPropertyFromCommand(
        command=["python", "setup.py", "--version"],
        name='check-version',
        description=['checking', 'version'],
        descriptionDone=['checking', 'version'],
        property='version'
    ))
    factory.addSteps(installDependencies())
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
    factory.addStep(SetPropertyFromCommand(
        command=["python", "setup.py", "--version"],
        name='check-version',
        description=['checking', 'version'],
        descriptionDone=['checking', 'version'],
        property='version'
    ))
    factory.addSteps(installDependencies())
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
    factory.addStep(Trigger(
        name='trigger/built-packages',
        schedulerNames=['trigger/built-packages/%s' % (distribution,)],
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


def makeHomebrewRecipeCreationFactory():
    """Create the Homebrew recipe from a source distribution.

    This is separate to the recipe testing, to allow it to be done on a
    non-Mac platform.  Once complete, this triggers the Mac testing.
    """
    factory = getFlockerFactory(python="python2.7")
    factory.addStep(SetPropertyFromCommand(
        command=["python", "setup.py", "--version"],
        name='check-version',
        description=['checking', 'version'],
        descriptionDone=['check', 'version'],
        property='version'
    ))
    factory.addSteps(installDependencies())

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


from buildbot.config import BuilderConfig
from buildbot.schedulers.basic import AnyBranchScheduler
from buildbot.schedulers.forcesched import (
    CodebaseParameter, StringParameter, ForceScheduler, FixedParameter)
from buildbot.schedulers.triggerable import Triggerable
from buildbot.locks import SlaveLock

from ..steps import report_expected_failures_parameter
from ..steps import idleSlave

# A lock to prevent multiple functional tests running at the same time
functionalLock = SlaveLock('functional-tests')

OMNIBUS_DISTRIBUTIONS = [
    'fedora-20',
    'ubuntu-14.04',
    'centos-7',
]


def getBuilders(slavenames):
    builders = [
        BuilderConfig(name='flocker-fedora-20',
                      builddir='flocker',
                      slavenames=slavenames['aws/fedora-20'],
                      category='flocker',
                      factory=makeFactory(b'python2.7'),
                      locks=[functionalLock.access('counting')],
                      nextSlave=idleSlave),
        BuilderConfig(name='flocker-ubuntu-14.04',
                      slavenames=slavenames['aws/ubuntu-14.04'],
                      category='flocker',
                      factory=makeFactory(b'python2.7'),
                      locks=[functionalLock.access('counting')],
                      nextSlave=idleSlave),
        BuilderConfig(name='flocker-centos-7',
                      slavenames=slavenames['aws/centos-7'],
                      category='flocker',
                      factory=makeFactory(b'python2.7'),
                      locks=[functionalLock.access('counting')],
                      nextSlave=idleSlave),
        BuilderConfig(name='flocker-osx-10.10',
                      slavenames=slavenames['osx'],
                      category='flocker',
                      factory=makeFactory(
                          b'python2.7', tests=[
                              b'flocker.cli',
                              b'flocker.common',
                              b'flocker.ca',
                          ],
                      ),
                      nextSlave=idleSlave),
        BuilderConfig(name='flocker-zfs-head',
                      slavenames=slavenames['aws/fedora-20/zfs-head'],
                      category='flocker',
                      factory=makeFactory(b'python2.7'),
                      locks=[functionalLock.access('counting')],
                      nextSlave=idleSlave),
        BuilderConfig(name='flocker-twisted-trunk',
                      slavenames=slavenames['aws/fedora-20'],
                      category='flocker',
                      factory=makeFactory(b'python2.7', twistedTrunk=True),
                      locks=[functionalLock.access('counting')],
                      nextSlave=idleSlave),
        BuilderConfig(name='flocker-coverage',
                      slavenames=slavenames['aws/fedora-20'],
                      category='flocker',
                      factory=makeCoverageFactory(),
                      locks=[functionalLock.access('counting')],
                      nextSlave=idleSlave),
        BuilderConfig(name='flocker-lint',
                      slavenames=slavenames['aws/fedora-20'],
                      category='flocker',
                      factory=makeLintFactory(),
                      nextSlave=idleSlave),
        BuilderConfig(name='flocker-docs',
                      slavenames=slavenames['aws/fedora-20'],
                      category='flocker',
                      factory=makeInternalDocsFactory(),
                      nextSlave=idleSlave),
        BuilderConfig(name='flocker-admin',
                      slavenames=slavenames['aws/fedora-20'],
                      category='flocker',
                      factory=makeAdminFactory(),
                      nextSlave=idleSlave),
        BuilderConfig(name='flocker/homebrew/create',
                      builddir='flocker-homebrew-create',
                      slavenames=slavenames['aws/fedora-20'],
                      category='flocker',
                      factory=makeHomebrewRecipeCreationFactory(),
                      nextSlave=idleSlave),
        BuilderConfig(name='flocker/homebrew/test',
                      builddir='flocker-homebrew-test',
                      slavenames=slavenames['osx'],
                      category='flocker',
                      factory=makeHomebrewRecipeTestFactory(),
                      nextSlave=idleSlave),
        ]
    for distribution in OMNIBUS_DISTRIBUTIONS:
        builders.append(
            BuilderConfig(
                name='flocker-omnibus-%s' % (distribution,),
                slavenames=slavenames['aws/fedora-20'],
                category='flocker',
                factory=makeOmnibusFactory(
                    distribution=distribution,
                ),
                nextSlave=idleSlave,
                ))

    # Storage backend builders
    for configuration in STORAGE_CONFIGURATIONS:
        builders.extend([
            BuilderConfig(
                name=configuration.builder_name,
                builddir=configuration.builder_directory,
                slavenames=slavenames[configuration.slave_class],
                category='flocker',
                factory=makeFactory(
                    b'python2.7',
                    tests=[
                        "--testmodule",
                        Interpolate("%(prop:builddir)s/build/" +
                                    configuration.driver),
                    ],
                    env={'FLOCKER_FUNCTIONAL_TEST': 'TRUE'},
                ),
                locks=configuration.locks,
            )
        ])

    return builders

BUILDERS = [
    'flocker-fedora-20',
    'flocker-ubuntu-14.04',
    'flocker-centos-7',
    'flocker-osx-10.10',
    'flocker-twisted-trunk',
    'flocker-coverage',
    'flocker-lint',
    'flocker-docs',
    'flocker-zfs-head',
    'flocker-admin',
    'flocker/homebrew/create',
] + [
    'flocker-omnibus-%s' % (dist,) for dist in OMNIBUS_DISTRIBUTIONS
] + [
    configuration.builder_name for configuration in STORAGE_CONFIGURATIONS
]


def getSchedulers():
    return [
        AnyBranchScheduler(
            name="flocker",
            treeStableTimer=5,
            builderNames=BUILDERS,
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
        Triggerable(
            name='trigger/created-homebrew',
            builderNames=['flocker/homebrew/test'],
            codebases={
                "flocker": {"repository": GITHUB + b"/flocker"},
            },
        ),
    ]
