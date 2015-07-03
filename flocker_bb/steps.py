import random
from collections import Counter

from twisted.internet import defer
from twisted.python import log
from twisted.python.constants import NamedConstant, Names
from twisted.python.filepath import FilePath

from buildbot.process.properties import Interpolate
from buildbot.steps.shell import ShellCommand
from buildbot.steps.source.git import Git
from buildbot.steps.source.base import Source
from buildbot.process.factory import BuildFactory
from buildbot.status.results import SUCCESS
from buildbot.process import buildstep
from buildbot.process.properties import renderer
from buildbot.schedulers.forcesched import BooleanParameter

from os import path
import re
import json
from functools import partial

VIRTUALENV_DIR = '%(prop:workdir)s/venv'

VIRTUALENV_PY = Interpolate("%(prop:workdir)s/../dependencies/virtualenv.py")
GITHUB = b"https://github.com/ClusterHQ"

TWISTED_GIT = b'https://github.com/twisted/twisted'

flockerBranch = Interpolate("%(src:flocker:branch)s")

buildNumber = Interpolate("build-%(prop:buildnumber)s")


report_expected_failures_parameter = BooleanParameter(
    name="report-expected-failures",
    label="Report status for builders expected to fail.",
)


class BranchType(Names):
    master = NamedConstant()
    release = NamedConstant()
    maintenance = NamedConstant()
    development = NamedConstant()


def getBranchType(branch):
    """
    Given a Buildbot branch parameter, return the kind of branch it is.

    This decision is made based on Flocker branch naming conventions.

    :param branch: A string describing a branch. e.g. 'master',
        'some-feature-FLOC-1234'.
    :return: ``BranchType`` constant.
    """
    # TODO: Have MergeForward use this, rather than the other way around.
    if MergeForward._isMaster(branch):
        return BranchType.master
    if MergeForward._isRelease(branch):
        return BranchType.release
    match = MergeForward._MAINTENANCE_BRANCH_RE.match(branch)
    if match:
        return BranchType.maintenance
    return BranchType.development


@renderer
def buildbotURL(build):
    return build.getBuild().build_status.master.status.getBuildbotURL()


@renderer
def flockerRevision(build):
    """
    Get the SHA-1 of the checked-out version of flocker.
    """
    return build.getProperty('got_revision', {}).get('flocker')


def _result(kind, prefix, discriminator=buildNumber):
    """
    Build a path to results.
    """
    parts = [prefix, kind, flockerBranch, discriminator]

    @renderer
    def render(build):
        d = defer.gatherResults(map(build.render, parts))
        d.addCallback(lambda parts: path.join(*parts))
        return d
    return render

resultPath = partial(_result, prefix=path.abspath("private_html"))


def resultURL(kind, isAbsolute=False, **kwargs):
    if isAbsolute:
        # buildbotURL has a trailing slash, so don't double it here.
        prefix = Interpolate("%(kw:base)sresults/", base=buildbotURL)
    else:
        prefix = '/results/'
    return _result(kind=kind, prefix=prefix, **kwargs)


def buildVirtualEnv(python, useSystem=False):
    steps = []
    if useSystem:
        command = ['virtualenv', '-p', python]
    else:
        command = [python, VIRTUALENV_PY]
    command += ["--clear", Interpolate(VIRTUALENV_DIR)],
    steps.append(ShellCommand(
        name="build-virtualenv",
        description=["build", "virtualenv"],
        descriptionDone=["built", "virtualenv"],
        command=command,
        haltOnFailure=True,
    ))
    steps.append(ShellCommand(
        name="clean-virtualenv-builds",
        description=["cleaning", "virtualenv"],
        descriptionDone=["clean", "virtualenv"],
        command=["rm", "-rf", Interpolate(path.join(VIRTUALENV_DIR, "build"))],
        haltOnFailure=True,
    ))
    return steps


def getFactory(codebase, useSubmodules=True, mergeForward=False):
    factory = BuildFactory()

    repourl = GITHUB + b"/" + codebase
    # check out the source
    factory.addStep(
        Git(repourl=repourl,
            submodules=useSubmodules, mode='full', method='fresh',
            codebase=codebase))

    if mergeForward:
        factory.addStep(
            MergeForward(repourl=repourl, codebase=codebase))

    if useSubmodules:
        # Work around http://trac.buildbot.net/ticket/2155
        factory.addStep(
            ShellCommand(command=["git", "submodule", "update", "--init"],
                         description=["updating", "git", "submodules"],
                         descriptionDone=["update", "git", "submodules"],
                         name="update-git-submodules"))

    return factory


def virtualenvBinary(command):
    return Interpolate(path.join(VIRTUALENV_DIR, "bin", command))


def asJSON(data):
    @renderer
    def render(props):
        return (props.render(data)
                .addCallback(json.dumps, indent=2, separators=(',', ': ')))
    return render


class URLShellCommand(ShellCommand):
    renderables = ["urls"]

    def __init__(self, urls, **kwargs):
        ShellCommand.__init__(self, **kwargs)
        self.urls = urls

    def createSummary(self, log):
        ShellCommand.createSummary(self, log)
        for name, url in self.urls.iteritems():
            self.addURL(name, url)


class MasterWriteFile(buildstep.BuildStep):
    """
    Write a rendered string to a file on the master.
    """
    name = 'MasterWriteFile'
    description = ['writing']
    descriptionDone = ['write']
    renderables = ['content', 'path', 'urls']

    def __init__(self, path, content, urls, **kwargs):
        buildstep.BuildStep.__init__(self, **kwargs)
        self.content = content
        self.path = path
        self.urls = urls

    def start(self):
        path = FilePath(self.path)
        parent = path.parent()
        if not parent.exists():
            parent.makedirs()
        path.setContent(self.content)
        for name, url in self.urls.iteritems():
            self.addURL(name, url)
        self.step_status.setText(self.describe(done=True))
        self.finished(SUCCESS)


class MergeForward(Source):
    """
    Merge with master.
    """
    name = 'merge-forward'
    description = ['merging', 'forward']
    descriptionDone = ['merge', 'forward']
    haltOnFailure = True

    def __init__(self, repourl, branch='master',
                 **kwargs):
        self.repourl = repourl
        self.branch = branch
        kwargs['env'] = {
            'GIT_AUTHOR_EMAIL': 'buildbot@clusterhq.com',
            'GIT_AUTHOR_NAME': 'ClusterHQ Buildbot',
            'GIT_COMMITTER_EMAIL': 'buildbot@clusterhq.com',
            'GIT_COMMITTER_NAME': 'ClusterHQ Buildbot',
        }
        Source.__init__(self, **kwargs)
        self.addFactoryArguments(repourl=repourl, branch=branch)

    @staticmethod
    def _isMaster(branch):
        """
        Is this branch master?
        """
        return branch == 'master'

    _RELEASE_TAG_RE = re.compile(
        # <major>.<minor>.<micro>
        r'^[0-9]+\.[0-9]+\.[0-9]+'
        # plus (optionally) any of:
        r'(?:'
        # weekly release
        '\.?dev[0-9]+'
        # prerelease
        r'|(?:pre|rc)[0-9]+'
        # documentation release
        r'|(?:\+doc|\.post)[0-9]+)?'
        r'$')

    @classmethod
    def _isRelease(cls, branch):
        """
        Is this a release branch or tag?
        """
        return (branch.startswith('release/')
                or cls._RELEASE_TAG_RE.match(branch))

    _MAINTENANCE_BRANCH_RE = re.compile(
        '^release-maintenance/(?P<target>[^/]*)/(?P<branch>.*)')

    @classmethod
    def mergeTarget(cls, branch):
        """
        Determine which branch to merge against.

        :return: The branch to merge against or `None`.
        """
        # Don't merge forward on master or release branches.
        if cls._isMaster(branch) or cls._isRelease(branch):
            return None

        # If we are on a release-maintenance branch,
        # merge against the corresponding release
        match = cls._MAINTENANCE_BRANCH_RE.match(branch)
        if match:
            return "release/%(target)s" % match.groupdict()

        # Otherwise merge against master.
        return "master"

    def startVC(self, branch, revision, patch):
        self.stdio_log = self.addLog('stdio')
        self.step_status.setText(['merging', 'forward'])

        merge_branch = self.mergeTarget(branch)

        d = defer.succeed(None)
        if merge_branch is None:
            # If we aren't merging anything, just get the previous
            # version, to check coverage against (lint_revision).
            d.addCallback(lambda _: self._getPreviousVersion())
        else:
            # If we are merging, fetch that version, merge and
            # record the merge base to lint against.
            d.addCallback(lambda _: self._fetch(merge_branch))
            d.addCallback(lambda _: self._getCommitDate())
            d.addCallback(self._merge)
            d.addCallback(self._getMergeBase)

        d.addCallback(self._setLintVersion)
        d.addCallback(lambda _: SUCCESS)
        d.addCallbacks(self.finished, self.checkDisconnect)
        d.addErrback(self.failed)

    def finished(self, results):
        if results == SUCCESS:
            self.step_status.setText(['merge', 'forward'])
        else:
            self.step_status.setText(['merge', 'forward', 'failed'])
        return Source.finished(self, results)

    def _fetch(self, branch='master'):
        return self._dovccmd(['fetch', self.repourl, branch])

    def _merge(self, date):
        # We re-use the date of the latest commit from the branch
        # to ensure that the commit hash is consistent.
        self.env.update({
            'GIT_AUTHOR_DATE': date.strip(),
            'GIT_COMMITTER_DATE': date.strip(),
        })
        # Merge against the requested commit (if this is a triggered build).
        # Otherwise, merge against the tip of the merge branch.
        merge_target = self.getProperty('merge_target', 'FETCH_HEAD')
        d = self._dovccmd(['merge',
                           '--no-ff', '--no-stat',
                           '-m', 'Merge forward.',
                           merge_target])
        d.addCallback(lambda _: merge_target)
        return d

    def _getPreviousVersion(self):
        return self._dovccmd(['rev-parse', 'HEAD~1'],
                             collectStdout=True)

    def _getMergeBase(self, merge_target):
        return self._dovccmd(['rev-parse', merge_target],
                             collectStdout=True)

    def _setLintVersion(self, version):
        self.setProperty("lint_revision", version.strip(), "merge-forward")

    def _getCommitDate(self):
        return self._dovccmd(['log', '--format=%ci', '-n1'],
                             collectStdout=True)

    def _dovccmd(self, command, abandonOnFailure=True, collectStdout=False,
                 extra_args={}):
        cmd = buildstep.RemoteShellCommand(self.workdir, ['git'] + command,
                                           env=self.env,
                                           logEnviron=self.logEnviron,
                                           collectStdout=collectStdout,
                                           **extra_args)
        cmd.useLog(self.stdio_log, False)
        d = self.runCommand(cmd)

        def evaluateCommand(cmd):
            if abandonOnFailure and cmd.rc != 0:
                log.msg("Source step failed while running command %s" % cmd)
                raise buildstep.BuildStepFailed()
            if collectStdout:
                return cmd.stdout
            else:
                return cmd.rc
        d.addCallback(lambda _: evaluateCommand(cmd))
        return d


def pip(what, packages):
    """
    Installs a list of packages with pip, in the current virtualenv.

    @param what: Description of the packages being installed.
    @param packages: L{list} of packages to install
    @returns: L{BuildStep}
    """
    return ShellCommand(
        name="install-" + what,
        description=["installing", what],
        descriptionDone=["install", what],
        command=[Interpolate(path.join(VIRTUALENV_DIR, "bin/pip")),
                 "install",
                 packages,
                 ],
        haltOnFailure=True)


def isBranch(codebase, predicate):
    """
    Return C{doStepIf} function checking whether the built branch
    matches the given branch.

    @param codebase: Codebase to check
    @param predicate: L{callable} that takes a branch and returns whether
        the step should be run.
    """
    def test(step):
        sourcestamp = step.build.getSourceStamp(codebase)
        branch = sourcestamp.branch
        return predicate(branch)
    return test


def isMasterBranch(codebase):
    return isBranch(codebase, MergeForward._isMaster)


def isReleaseBranch(codebase):
    return isBranch(codebase, MergeForward._isRelease)


def idleSlave(builder, slavebuilders):
    """
    Return a slave that has the least number of running builds on it.
    """
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


def slave_environ(var):
    """
    Render a environment variable from the slave.
    """
    @renderer
    def render(properties):
        return properties.getBuild().slavebuilder.slave.slave_environ.get(var)
    return render
