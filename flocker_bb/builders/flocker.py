from buildbot.steps.shell import ShellCommand
from buildbot.steps.python_twisted import Trial
from buildbot.steps.python import Sphinx
from buildbot.steps.transfer import DirectoryUpload, StringDownload
from buildbot.steps.master import MasterShellCommand
from buildbot.steps.source.git import Git
from buildbot.process.properties import Interpolate, Property
from buildbot.steps.package.rpm import RpmLint
from buildbot.steps.trigger import Trigger

from os import path

from ..steps import (
        VIRTUALENV_DIR, buildVirtualEnv, virtualenvBinary,
        getFactory,
        GITHUB,
        TWISTED_GIT,
        pip,
        isMasterBranch,
        )

from ..mock import MockBuildSRPM, MockRebuild

# This is where temporary files associated with a build will be dumped.
TMPDIR = Interpolate(b"%(prop:workdir)s/tmp-%(prop:buildnumber)s")


def getFlockerFactory(python):
    factory = getFactory("flocker", useSubmodules=False, mergeForward=True)
    factory.addSteps(buildVirtualEnv(python, useSystem=True))
    return factory



def installDependencies():
    return [
        pip("dependencies", ["."]),
        pip("extras", ["Flocker[doc,dev]"]),
        ]


def _flockerTests(kwargs, tests=None):
    if tests is None:
        tests = [b"flocker"]
    return [
        ShellCommand(command=[b"mkdir", TMPDIR],
                     description=["creating", "TMPDIR"],
                     descriptionDone=["create", "TMPDIR"],
                     name="create-TMPDIR"),
        Trial(
            trial=[virtualenvBinary('trial')],
            tests=tests,
            testpath=None,
            workdir=TMPDIR,
            env={
                b"PATH": [Interpolate(path.join(VIRTUALENV_DIR, "bin")), "${PATH}"],
                },
            **kwargs),
        ShellCommand(command=[b"rm", b"-rf", TMPDIR],
                     alwaysRun=True,
                     description=["removing", "TMPDIR"],
                     descriptionDone=["remove", "TMPDIR"],
                     name="remove-TMPDIR"),
        ]


def _flockerCoverage():
    branch = "%(src:flocker:branch)s"
    revision = "flocker-%(prop:buildnumber)s"
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
        ShellCommand(
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
            Interpolate(b"private_html/%s/%s/change" % (branch, revision)),
            url=Interpolate(
                b"/results/%s/%s/change" % (
                    branch, revision)),
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
            Interpolate(b"private_html/%s/%s/complete" % (branch, revision)),
            url=Interpolate(
                b"/results/%s/%s/complete" % (
                    branch, revision)),
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



def makeFactory(python, tests=None, twistedTrunk=False):
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

    factory.addSteps(_flockerTests(kwargs={}, tests=tests))

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
         "http://data.hybridcluster.net/python/coverage_reporter-0.01_hl0-py27-none-any.whl",
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
            b"PATH": [Interpolate(path.join(VIRTUALENV_DIR, "bin")), "${PATH}"],
            },
        **extraArgs)




def makeInternalDocsFactory():
    branch = "%(src:flocker:branch)s"
    revision = "flocker-%(prop:buildnumber)s"

    factory = getFlockerFactory(python="python2.7")
    factory.addSteps(installDependencies())
    factory.addStep(sphinxBuild("spelling", "build/docs",
                                logfiles={'errors': '_build/spelling/output.txt'},
                                haltOnFailure=False))
    factory.addStep(sphinxBuild("linkcheck", "build/docs",
                                logfiles={'errors': '_build/linkcheck/output.txt'},
                                haltOnFailure=False))
    factory.addStep(sphinxBuild("html", "build/docs"))
    factory.addStep(DirectoryUpload(
        b"docs/_build/html",
        Interpolate(b"private_html/%s/%s/docs" % (branch, revision)),
        url=Interpolate(
            b"/results/%s/%s/docs" % (
                branch, revision)),
        name="upload-html",
        ))
    factory.addStep(MasterShellCommand(
        name='link-release-documentation',
        description=["linking", "release", "documentation"],
        descriptionDone=["link", "release", "documentation"],
        command=[
            "ln", '-nsf',
            Interpolate('%s/%s/docs' % (branch, revision)),
            'docs',
            ],
        path="private_html",
        haltOnFailure=True,
        doStepIf=isMasterBranch('flocker'),
        ))
    return factory




def makeNativeRPMFactory():
    branch = "%(src:flocker:branch)s"
    factory = getFlockerFactory(python="python2.7")
    factory.addStep(ShellCommand(
        name='build-sdist',
        description=["building", "sdist"],
        descriptionDone=["build", "sdist"],
        command=[
            virtualenvBinary('python'),
            "setup.py", "sdist", "generate_spec",
            ],
        haltOnFailure=True))
    factory.addStep(MockBuildSRPM(
        root='fedora-20-x86_64',
        resultdir='dist',
        spec='python-flocker.spec',
        sources='dist',
        ))
    factory.addStep(MockRebuild(
        root='fedora-20-x86_64',
        resultdir='dist',
        srpm=Interpolate('dist/%(prop:srpm)s'),
        ))
    factory.addStep(ShellCommand(
        name="create-repo-directory",
        description=["creating", "repo", "directory"],
        descriptionDone=["create", "repo", "directory"],
        command=["mkdir", "repo"],
        haltOnFailure=True))
    factory.addStep(ShellCommand(
        name="populate-repo",
        description=["populating", "repo"],
        descriptionDone=["populate", "repo"],
        command=["cp", "-t", "../repo", Property('srpm'), Property('rpm')],
        workdir='build/dist',
        haltOnFailure=True))
    factory.addStep(ShellCommand(
        name='build-repo-metadata',
        description=["building", "repo", "metadata"],
        descriptionDone=["build", "repo", "metadata"],
        command=["createrepo_c", "repo"], # Fix this to use createrepo
        haltOnFailure=True))
    factory.addStep(DirectoryUpload(
        Interpolate('repo'),
        Interpolate(b"private_html/fedora/20/x86_64/%s/" % (branch,)),
        url=Interpolate(
            b"/results/fedora/20/x86_64/%s/" % (branch,),
            ),
        name="upload-repo",
        ))
    factory.addStep(Trigger(
        name='trigger-flocker-vagrant',
        schedulerNames=['trigger-flocker-vagrant'],
        updateSourceStamp=True,
        waitForFinish=False,
        ))
    factory.addStep(RpmLint([
            Property('srpm'),
            Property('rpm'),
            ],
        workdir="build/dist",
        ))

    return factory



from buildbot.config import BuilderConfig
from buildbot.schedulers.basic import AnyBranchScheduler
from buildbot.schedulers.forcesched import (
    CodebaseParameter, StringParameter, ForceScheduler, FixedParameter)
from buildbot.locks import SlaveLock

# A lock to prevent multiple functional tests running at the same time
functionalLock = SlaveLock('functional-tests')


def idleSlave(builder, slaves):
    idle = [slave for slave in slaves if slave.isAvailable()]
    if idle:
        return idle[0]

def getBuilders(slavenames):
    return [
        BuilderConfig(name='flocker',
                      slavenames=slavenames['fedora'],
                      category='flocker',
                      factory=makeFactory(b'python2.7'),
                      locks=[functionalLock.access('counting')],
                      nextSlave=idleSlave),
        BuilderConfig(name='flocker-zfs-head',
                      slavenames=slavenames['fedora-zfs-head'],
                      category='flocker',
                      factory=makeFactory(b'python2.7'),
                      locks=[functionalLock.access('counting')],
                      nextSlave=idleSlave),
        BuilderConfig(name='flocker-twisted-trunk',
                      slavenames=slavenames['fedora'],
                      category='flocker',
                      factory=makeFactory(b'python2.7', twistedTrunk=True),
                      locks=[functionalLock.access('counting')],
                      nextSlave=idleSlave),
        BuilderConfig(name='flocker-coverage',
                      slavenames=slavenames['fedora'],
                      category='flocker',
                      factory=makeCoverageFactory(),
                      locks=[functionalLock.access('counting')],
                      nextSlave=idleSlave),
        BuilderConfig(name='flocker-lint',
                      slavenames=slavenames['fedora'],
                      category='flocker',
                      factory=makeLintFactory(),
                      nextSlave=idleSlave),
        BuilderConfig(name='flocker-docs',
                      slavenames=slavenames['fedora'],
                      category='flocker',
                      factory=makeInternalDocsFactory(),
                      nextSlave=idleSlave),
        BuilderConfig(name='flocker-native-fedora20-rpms',
                      builddir='flocker-rpms',
                      slavenames=slavenames['fedora'],
                      category='flocker',
                      factory=makeNativeRPMFactory(),
                      nextSlave=idleSlave),
        BuilderConfig(name='flocker-admin',
                      slavenames=slavenames['fedora'],
                      category='flocker',
                      factory=makeAdminFactory(),
                      nextSlave=idleSlave),
        ]

BUILDERS = [
    'flocker',
    'flocker-twisted-trunk',
    'flocker-coverage',
    'flocker-lint',
    'flocker-docs',
    'flocker-native-fedora20-rpms',
    'flocker-zfs-head',
    'flocker-admin',
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
                    branch=StringParameter("branch", default="master"),
                    repository=FixedParameter("repository", default=GITHUB + b"/flocker"),
                    ),
                ],
            properties=[],
            builderNames=BUILDERS,
            ),
        ]
