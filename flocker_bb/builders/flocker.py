from zope.interface import implementer

from buildbot.steps.shell import ShellCommand, SetPropertyFromCommand
from buildbot.steps.python_twisted import Trial
from buildbot.steps.python import PyFlakes, Sphinx
from buildbot.steps.transfer import DirectoryUpload, FileUpload
from buildbot.steps.master import MasterShellCommand
from buildbot.steps.source.git import Git
from buildbot.process.properties import Interpolate, renderer, Property
from buildbot.steps.package.rpm import RpmLint

from os import path

from ..steps import (
        VIRTUALENV_DIR, buildVirtualEnv,
        getFactory,
        GITHUB,
        TWISTED_GIT,
        )

from ..mock import MockBuildSRPM, MockRebuild

# This is where temporary files associated with a build will be dumped.
TMPDIR = Interpolate(b"%(prop:workdir)s/tmp-%(prop:buildnumber)s")


def getFlockerFactory(python):
    factory = getFactory("flocker", useSubmodules=False, mergeForward=True)
    factory.addSteps(buildVirtualEnv(python, useSystem=True))
    return factory


def pip(what, packages):
    return ShellCommand(
        name="install-" + what,
        description=["installing", what],
        descriptionDone=["install", what],
        command=[Interpolate(path.join(VIRTUALENV_DIR, "bin/pip")),
                 "install",
                 packages,
                 ],
        haltOnFailure=True)



def installDependencies():
    return pip("dependencies", ["-e", ".[doc,dev]"])


def installMetaTools():
    return pip("coverage", ["coverage==3.7", "http://data.hybridcluster.net/python/coverage_reporter-0.01_hl0-py27-none-any.whl"])


def _flockerTests(kwargs, tests=None):
    if tests is None:
        tests = [b"flocker"]
    return [
        ShellCommand(command=[b"mkdir", TMPDIR],
                     description=["creating", "TMPDIR"],
                     descriptionDone=["create", "TMPDIR"],
                     name="create-TMPDIR"),
        Trial(
            trial=[Interpolate(path.join(VIRTUALENV_DIR, "bin/trial"))],
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
                [Interpolate(path.join(VIRTUALENV_DIR, "bin/coverage"))],
                b"run",
                b"--branch",
                b"--source", "../build/flocker",
                ]
            })
    steps.insert(len(steps)-1,
        ShellCommand(
            name='move-coverage',
            description=["moving", "coverage"],
            descriptionDone=["move", "coverage"],
            command=['cp', '.coverage', '../build'],
            workdir=TMPDIR,
            haltOnFailure=True))
    steps += [
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
                b"http://build.hybridcluster.net/private/%s/%s/change" % (
                    branch, revision)),
            name="upload-coverage-annotations",
            ),
        ShellCommand(
            command=[
                Interpolate(path.join(VIRTUALENV_DIR, "bin/coverage")),
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
                b"http://build.hybridcluster.net/private/%s/%s/complete" % (
                    branch, revision)),
            name="upload-coverage-html",
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
        command=[Interpolate(path.join(VIRTUALENV_DIR, "bin/pip")),
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

    factory.addStep(installDependencies())

    if twistedTrunk:
        factory.addSteps(installTwistedTrunk())

    factory.addSteps(_flockerTests(kwargs={}, tests=tests))

    return factory



def makeMetaFactory():
    """
    Create and return a new build factory for doing reporting *about* the code.

    XXX Stupid function name.
    """
    factory = getFlockerFactory(python="python2.7")
    factory.addStep(installDependencies())
    factory.addStep(installMetaTools())
    factory.addStep(PyFlakes(
        command=[Interpolate(path.join(VIRTUALENV_DIR, "bin/pyflakes")),
                 "flocker"],
        workdir='build',
        flunkOnFailure=True,
        ))
    factory.addSteps(_flockerCoverage())
    return factory





def sphinxBuild(builder, workdir=b"build/docs"):
    """
    Build sphinx documentation.

    @param builder: Sphinx builder to use.
    @param path: Location of sphinx tree.
    """
    return Sphinx(
        name="build-%s" % (builder,),
        description=["building", builder],
        descriptionDone=["build", builder],
        sphinx_builder=builder,
        sphinx_builddir=path.join("_build", builder),
        sphinx=[Interpolate(path.join(VIRTUALENV_DIR, "bin/sphinx-build")),
                '-d', "_build/doctree",
                ],
        workdir=workdir,
        defines={
            },
        env={
            b"PATH": [Interpolate(path.join(VIRTUALENV_DIR, "bin")), "${PATH}"],
            },
        flunkOnWarnings=True,
        haltOnFailure=True)


def isBranch(codebase, branchName, prefix=False):
    """
    Return C{doStepIf} function checking whether the built branch
    matches the given branch.

    @param codebase: Codebase to check
    @param branchName: Target branch
    @param prefix: L{bool} indicating whether to check against a prefix
    """
    def test(step):
        sourcestamp = step.build.getSourceStamp(codebase)
        branch = sourcestamp.branch
        if prefix:
            return branch.startswith(branchName)
        else:
            return branch == branchName
    return test

def isReleaseBranch(codebase):
    return isBranch(codebase, 'release-', prefix=True)

def isMasterBranch(codebase):
    return isBranch(codebase, 'master')


def makeInternalDocsFactory():
    branch = "%(src:flocker:branch)s"
    revision = "flocker-%(prop:buildnumber)s"

    factory = getFlockerFactory(python="python2.7")
    factory.addStep(installDependencies())
    factory.addStep(sphinxBuild("html", "build/docs"))
    factory.addStep(DirectoryUpload(
        b"docs/_build/html",
        Interpolate(b"private_html/%s/%s/docs" % (branch, revision)),
        url=Interpolate(
            b"http://build.hybridcluster.net/private/%s/%s/docs" % (
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


@renderer
def underscoreVersion(props):
    return props.getProperty('version').replace('-', '_')

def makeRPMFactory():
    branch = "%(src:flocker:branch)s"
    revision = "flocker-%(prop:buildnumber)s"
    factory = getFlockerFactory(python="python2.7")
    factory.addStep(ShellCommand(
        name='build-sdist',
        description=["building", "sdist"],
        descriptionDone=["build", "sdist"],
        command=[
            Interpolate(path.join(VIRTUALENV_DIR, "bin/python")),
            "setup.py", "sdist",
            ],
        haltOnFailure=True))
    factory.addStep(SetPropertyFromCommand(
        command=[
            Interpolate(path.join(VIRTUALENV_DIR, "bin/python")),
            "setup.py", "--version",
            ],
        name='check-version',
        description=['checking', 'version'],
        descriptionDone=['checking', 'version'],
        property='version'
        ))
    factory.addStep(MockBuildSRPM(
        root='fedora-20-x86_64',
        resultdir='dist',
        spec='python-flocker.spec',
        sources='dist',
        extraOptions=["-D", Interpolate('flocker_version %(prop:version)s')],
        ))
    factory.addStep(FileUpload(
        Interpolate('dist/%(prop:srpm)s', version=underscoreVersion),
        Interpolate(b"private_html/%s/%s/%%(prop:srpm)s" % (branch, revision)),
        url=Interpolate(
            b"/private/%s/%s/%%(prop:srpm)s" % (
                branch, revision)),
        name="upload-srpm",
        ))
    factory.addStep(MockRebuild(
        root='fedora-20-x86_64',
        resultdir='dist',
        srpm=Interpolate('dist/%(prop:srpm)s'),
        extraOptions=["-D", Interpolate('flocker_version %(prop:version)s')],
        ))
    factory.addStep(FileUpload(
        Interpolate('dist/%(prop:rpm)s', version=underscoreVersion),
        Interpolate(b"private_html/%s/%s/%%(prop:rpm)s" % (branch, revision)),
        url=Interpolate(
            b"/private/%s/%s/%%(prop:rpm)s" % (
                branch, revision),
            version=underscoreVersion
            ),
        name="upload-rpm",
        ))
    factory.addStep(RpmLint([
        Interpolate('dist/%(prop:srpm)s', version=underscoreVersion),
        Interpolate('dist/%(prop:rpm)s', version=underscoreVersion),
        ]))

    return factory



from buildbot.config import BuilderConfig
from buildbot.schedulers.basic import AnyBranchScheduler
from buildbot.schedulers.forcesched import (
    CodebaseParameter, StringParameter, ForceScheduler, FixedParameter)

def idleSlave(builder, slaves):
    idle = [slave for slave in slaves if slave.isAvailable()]
    if idle:
        return idle[0]

def getBuilders(slavenames):
    return [
        BuilderConfig(name='flocker',
                      slavenames=slavenames,
                      category='flocker',
                      factory=makeFactory(b'python2.7'),
                      nextSlave=idleSlave),
        BuilderConfig(name='flocker-twisted-trunk',
                      slavenames=slavenames,
                      category='flocker',
                      factory=makeFactory(b'python2.7', twistedTrunk=True),
                      nextSlave=idleSlave),
        BuilderConfig(name='flocker-coverage',
                      slavenames=slavenames,
                      category='flocker',
                      factory=makeMetaFactory(),
                      nextSlave=idleSlave),
        BuilderConfig(name='flocker-docs',
                      slavenames=slavenames,
                      category='flocker',
                      factory=makeInternalDocsFactory(),
                      nextSlave=idleSlave),
        BuilderConfig(name='flocker-rpms',
                      slavenames=slavenames,
                      category='flocker',
                      factory=makeRPMFactory(),
                      nextSlave=idleSlave),
        ]

BUILDERS = [
    'flocker',
    'flocker-twisted-trunk',
    'flocker-coverage',
    'flocker-docs',
    'flocker-rpms',
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
