from twisted.trial.unittest import TestCase
from buildbot.test.util import sourcesteps
from buildbot.status.results import SUCCESS
from buildbot.test.fake.remotecommand import ExpectShell

from ..steps import (
        MergeForward)


class TestMergeForward(sourcesteps.SourceStepMixin, TestCase):
    """
    Tests for L{MergeForward}.
    """

    env = {
        'GIT_AUTHOR_EMAIL': 'buildbot@hybridcluster.net',
        'GIT_AUTHOR_NAME': 'HybridCluster Buildbot',
        'GIT_COMMITTER_EMAIL': 'buildbot@hybridcluster.net',
        'GIT_COMMITTER_NAME': 'HybridCluster Buildbot',
    }


    def setUp(self):
        return self.setUpSourceStep()

    def tearDown(self):
        return self.tearDownSourceStep()


    def buildStep(self, branch):
        self.setupStep(MergeForward(repourl='git://twisted'),
                       {'branch': branch})

    def test_master(self):
        self.buildStep('master')
        self.expectCommands(
                ExpectShell(workdir='wkdir',
                            command=['git', 'rev-parse', 'HEAD~1'],
                            env=self.env)
                + ExpectShell.log('stdio', stdout="deadbeef00000000000000000000000000000000\n")
                + 0
        )
        self.expectOutcome(result=SUCCESS, status_text=['merge', 'forward'])
        self.expectProperty('lint_revision', 'deadbeef00000000000000000000000000000000')
        return self.runStep()


    def test_branch(self):
        self.buildStep('destroy-the-sun-5000')
        self.expectCommands(
                ExpectShell(workdir='wkdir',
                            command=['git', 'fetch',
                                'git://twisted', 'master'],
                            env=self.env)
                + 0,
                ExpectShell(workdir='wkdir',
                            command=['git', 'merge',
                                '--no-ff', '--no-stat',
                                'FETCH_HEAD'],
                            env=self.env)
                + 0,
                ExpectShell(workdir='wkdir',
                            command=['git', 'merge-base', 'HEAD', 'FETCH_HEAD'],
                            env=self.env)
                + ExpectShell.log('stdio', stdout="deadbeef00000000000000000000000000000000\n")
                + 0
        )
        self.expectOutcome(result=SUCCESS, status_text=['merge', 'forward'])
        self.expectProperty('lint_revision', 'deadbeef00000000000000000000000000000000')
        return self.runStep()


    def test_releaseBranch(self):
        self.buildStep('release-23.2-12345')
        self.expectCommands(
                ExpectShell(workdir='wkdir',
                            command=['git', 'fetch',
                                'git://twisted', 'master'],
                            env=self.env)
                + 0,
                ExpectShell(workdir='wkdir',
                            command=['git', 'merge-base', 'HEAD', 'FETCH_HEAD'],
                            env=self.env)
                + ExpectShell.log('stdio', stdout="deadbeef00000000000000000000000000000000\n")
                + 0
        )
        self.expectOutcome(result=SUCCESS, status_text=['merge', 'forward'])
        self.expectProperty('lint_revision', 'deadbeef00000000000000000000000000000000')
        return self.runStep()
