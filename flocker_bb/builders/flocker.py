import random
from itertools import groupby
from collections import Counter
from buildbot.steps.shell import ShellCommand, SetPropertyFromCommand
from buildbot.steps.python_twisted import Trial
from buildbot.steps.python import Sphinx
from buildbot.steps.transfer import (
    DirectoryUpload, FileDownload, FileUpload, StringDownload)
from buildbot.steps.master import MasterShellCommand
from buildbot.steps.source.git import Git
from buildbot.process.properties import Interpolate, Property
from buildbot.steps.trigger import Trigger
from buildbot.config import error

from os import path

from ..steps import (
    VIRTUALENV_DIR, buildVirtualEnv, virtualenvBinary,
    getFactory,
    GITHUB,
    TWISTED_GIT,
    pip,
    isMasterBranch, isReleaseBranch,
    resultPath, resultURL,
    )

# This is where temporary files associated with a build will be dumped.
TMPDIR = Interpolate(b"%(prop:workdir)s/tmp-%(prop:buildnumber)s")


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
            # We use s3cmd instead of gsutil here because of
            # https://github.com/GoogleCloudPlatform/gsutil/issues/247
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
            command="dpkg-scanpackages . | gzip > Packages.gz",
            path=repository_path,
            haltOnFailure=True))
    else:
        error("Unknown distritubtion %s in createRepository."
              % (distribution,))

    return steps


def makeOmnibusFactory(distribution, triggerSchedulers=()):
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
    if distribution == 'fedora-20':
        factory.addStep(FileUpload(
            slavesrc=Interpolate(
                '/flocker/dist/Flocker-%(prop:version)s.tar.gz'),
            masterdest=Interpolate(
                '~/public_html/flocker/dist/Flocker-%(prop:version)s.tar.gz')))
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
    if triggerSchedulers:
        factory.addStep(Trigger(
            name='trigger/built-rpms',
            schedulerNames=triggerSchedulers,
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
    factory = getFlockerFactory(python="python2.7")
    factory.addStep(SetPropertyFromCommand(
        command=["python", "setup.py", "--version"],
        name='check-version',
        description=['checking', 'version'],
        descriptionDone=['checking', 'version'],
        property='version'
    ))

    # Run admin/homebrew.py with BuildBot sdist URL as argument
    # XXX - how do we know the BuildBot master URL?
    #
    # XXX - version of make-homebrew-recipe that can handle URL argument
    # XXX - is in ClusterHQ/flocker PR #1192
    dist_url = "{0}{1}".format(
        resultURL('omnibus', discriminator='fedora-20'),
        'Flocker-%(prop:version)s.tar.gz'
    )
    factory.addStep(ShellCommand(
        name='make-homebrew-recipe',
        description=["building", "recipe"],
        descriptionDone=["build", "recipe"],
        command=[
            "VERSION=Dev", "admin/make-homebrew-recipe", dist_url, ">",
            "FlockerDev.rb"],
        haltOnFailure=True))

    # Upload new .rb file to BuildBot master
    factory.addStep(FileUpload(
        slavesrc="FlockerDev.rb",
        masterdest=Interpolate("~/Flocker%(prop:buildnumber)s.rb")))

    # Trigger the homebrew-test build
    factory.addStep(Trigger(
        name='trigger-homebrew-test',
        schedulerNames=['trigger/homebrew-test'],
        set_properties={
            'master_recipe': Interpolate("~/Flocker%(prop:buildnumber)s.rb")
            },
        waitForFinish=False,
        ))

    # XXX - maybe the above should be waitForFinish=True, and then this
    # XXX - build deletes the sdist and Homebrew files on master?

    return factory


def makeHomebrewRecipeTestFactory():
    factory = getFlockerFactory(python="python2.7")
    factory.addStep(SetPropertyFromCommand(
        command=["python", "setup.py", "--version"],
        name='check-version',
        description=['checking', 'version'],
        descriptionDone=['checking', 'version'],
        property='version'
    ))

    # Download Homebrew recipe - XXX or use URL on Build master?
    factory.addStep(FileDownload(
        mastersrc=Property('master_recipe'), slavedest="FlockerDev.rb"))

    # Run testbrew script
    factory.addStep(ShellCommand(
        name='run-homebrew-test',
        description=["running", "recipe"],
        descriptionDone=["runn", "recipe"],
        command=[
            "python", "admin/testbrew.py", "FlockerDev.rb"],
        haltOnFailure=True))

    return factory


from buildbot.config import BuilderConfig
from buildbot.schedulers.basic import AnyBranchScheduler
from buildbot.schedulers.forcesched import (
    CodebaseParameter, StringParameter, ForceScheduler, FixedParameter)
from buildbot.schedulers.triggerable import Triggerable
from buildbot.locks import SlaveLock

# A lock to prevent multiple functional tests running at the same time
functionalLock = SlaveLock('functional-tests')

OMNIBUS_DISTRIBUTIONS = {
    'fedora-20': {
        'triggers': [
            'trigger/built-rpms/fedora-20', 'trigger/homebrew-create'
        ],
    },
    'ubuntu-14.04': {},
    'centos-7': {}
}


def idleSlave(builder, slavebuilders):
    # Count the builds on each slave
    builds = Counter([
        slavebuilder
        for slavebuilder in slavebuilders
        for sb in slavebuilder.slave.slavebuilders.values()
        if sb.isBusy()
    ])

    if not builds:
        # If there are no builds, then everything is idle.
        idle = slavebuilders
    else:
        min_builds = min(builds.values())
        idle = [
            slavebuilder
            for slavebuilder in slavebuilders
            if builds[slavebuilder] == min_builds
        ]
    if idle:
        return random.choice(idle)


def getBuilders(slavenames):
    builders = [
        BuilderConfig(name='flocker-fedora-20',
                      builddir='flocker',
                      slavenames=slavenames['fedora'],
                      category='flocker',
                      factory=makeFactory(b'python2.7'),
                      locks=[functionalLock.access('counting')],
                      nextSlave=idleSlave),
        BuilderConfig(name='flocker-ubuntu-14.04',
                      slavenames=slavenames['ubuntu-14.04'],
                      category='flocker',
                      factory=makeFactory(b'python2.7'),
                      locks=[functionalLock.access('counting')],
                      nextSlave=idleSlave),
        BuilderConfig(name='flocker-centos-7',
                      slavenames=slavenames['centos-7'],
                      category='flocker',
                      factory=makeFactory(b'python2.7'),
                      locks=[functionalLock.access('counting')],
                      nextSlave=idleSlave),
        BuilderConfig(name='flocker-osx-10.10',
                      slavenames=slavenames['osx'],
                      category='flocker',
                      factory=makeFactory(b'python2.7'),
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
        BuilderConfig(name='flocker-admin',
                      slavenames=slavenames['fedora'],
                      category='flocker',
                      factory=makeAdminFactory(),
                      nextSlave=idleSlave),
        BuilderConfig(name='flocker-homebrew-creation',
                      slavenames=slavenames['fedora'],
                      category='flocker',
                      factory=makeHomebrewRecipeCreationFactory(),
                      nextSlave=idleSlave),
        BuilderConfig(name='flocker-homebrew-test',
                      slavenames=slavenames['osx-10'],  # Slave name?
                      category='flocker',
                      factory=makeHomebrewRecipeTestFactory(),
                      nextSlave=idleSlave),
        ]
    for distribution, config in OMNIBUS_DISTRIBUTIONS.items():
        builders.append(
            BuilderConfig(
                name='flocker-omnibus-%s' % (distribution,),
                slavenames=slavenames['fedora'],
                category='flocker',
                factory=makeOmnibusFactory(
                    distribution=distribution,
                    triggerSchedulers=config.get('triggers'),
                ),
                nextSlave=idleSlave,
                ))

    # Distribute builders that have locks accross slaves.
    # This assumes there is only a single type of lock.
    locked_builders = sorted([b for b in builders if b.locks],
                             key=lambda b: b.slavenames)
    for slavenames, slave_builders in groupby(locked_builders,
                                              key=lambda b: b.slavenames):
        for builder, slavename in zip(slave_builders, slavenames):
            builder.slavenames = [slavename]

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
] + [
    'flocker-omnibus-%s' % (dist,) for dist in OMNIBUS_DISTRIBUTIONS.keys()
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
            properties=[],
            builderNames=BUILDERS,
            ),
        Triggerable(
            name='trigger/homebrew-create',
            builderNames=['flocker-homebrew-creation'],
            codebases={
                "flocker": {"repository": GITHUB + b"/flocker"},
            },
        ),
        Triggerable(
            name='trigger/homebrew-test',
            builderNames=['flocker-homebrew-test'],
            codebases={
                "flocker": {"repository": GITHUB + b"/flocker"},
            },
        ),

        ]
