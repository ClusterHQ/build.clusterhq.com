from buildbot.steps.shell import ShellCommand, SetPropertyFromCommand
from buildbot.process.properties import Interpolate

from ..steps import (
    buildVirtualEnv, virtualenvBinary,
    getFactory,
    GITHUB,
    buildbotURL,
    URLShellCommand
    )

#FIXME
from flocker_bb.builders.flocker import installDependencies

# This is where temporary files associated with a build will be dumped.
TMPDIR = Interpolate(b"%(prop:workdir)s/tmp-%(prop:buildnumber)s")

flockerBranch = Interpolate("%(src:flocker:branch)s")


def getFlockerFactory():
    factory = getFactory("flocker", useSubmodules=False, mergeForward=True)
    factory.addSteps(buildVirtualEnv("python2.7", useSystem=True))
    factory.addSteps(installDependencies())
    return factory




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
                'admin/build-vagrant-box',
                '--box', box,
                '--branch', flockerBranch,
                '--build-server', buildbotURL,
            ],
            haltOnFailure=True,
        ),
    ]

    steps.append(URLShellCommand(
        name='upload-base-box',
        description=['uploaiding', 'base', box, 'box'],
        descriptionDone=['upload', 'base', box, 'box'],
        command=[
            virtualenvBinary('gsutil'),
            'cp', '-a', 'public-read',
            Interpolate(
                'vagrant/%(kw:box)s/flocker-%(kw:box)s-%(prop:version)s.box',
                box=box),
            Interpolate(
                'gs://clusterhq-vagrant-buildbot/%(kw:box)s/',
                box=box),
        ],
        urls={
            Interpolate('%(kw:box)s box', box=box):
            Interpolate(
                'https://storage.googleapis.com/clusterhq-vagrant-buildbot/'
                '%(kw:box)s/flocker-%(kw:box)s-%(prop:version)s.box',
                box=box),
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

    factory.addSteps(buildVagrantBox('tutorial', add=True))

    factory.addStep(ShellCommand(
        name='start-tutorial-box',
        description=['starting', 'tutorial', 'box'],
        descriptionDone=['start', 'tutorial', 'box'],
        command=['vagrant', 'up'],
        workdir='build/docs/gettingstarted/tutorial',
        haltOnFailure=True,
        ))

    factory.addStep(ShellCommand(
        name='destroy-tutorial-box',
        description=['destroy', 'tutorial', 'box'],
        descriptionDone=['destroy', 'tutorial', 'box'],
        command=['vagrant', 'destroy', '-f'],
        workdir='build/docs/gettingstarted/tutorial',
        alwaysRun=True,
        ))
    return factory


from buildbot.config import BuilderConfig
from buildbot.schedulers.basic import AnyBranchScheduler
from buildbot.schedulers.forcesched import (
    CodebaseParameter, StringParameter, ForceScheduler, FixedParameter)
from buildbot.schedulers.triggerable import Triggerable
from buildbot.changes.filter import ChangeFilter


def idleSlave(builder, slaves):
    idle = [slave for slave in slaves if slave.isAvailable()]
    if idle:
        return idle[0]


def getBuilders(slavenames):
    return [
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
        ]

BUILDERS = [
    'flocker-vagrant-dev-box',
    'flocker-vagrant-tutorial-box',
    ]


def getSchedulers():
    return [
        AnyBranchScheduler(
            name="flocker-vagrant",
            treeStableTimer=5,
            builderNames=['flocker-vagrant-dev-box'],
            codebases={
                "flocker": {"repository": GITHUB + b"/flocker"},
            },
            change_filter=ChangeFilter(
                branch_re=r"(master|release/|[0-9]+\.[0-9]+\.[0-9]+((pre|dev)[0-9]+)?)",
                )
        ),
        Triggerable(
            name='trigger-flocker-vagrant',
            builderNames=['flocker-vagrant-tutorial-box'],
            codebases={
                "flocker": {"repository": GITHUB + b"/flocker"},
            },
        ),
        ForceScheduler(
            name="force-flocker-vagrant",
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
