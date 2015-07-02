from twisted.trial.unittest import TestCase
from buildbot.test.util import sourcesteps
from buildbot.status.results import SUCCESS
from buildbot.test.fake.remotecommand import ExpectShell

from ..steps import (
    MergeForward)


COMMIT_HASH = "deadbeef00000000000000000000000000000000"
COMMIT_HASH_NL = COMMIT_HASH + '\n'

COMMIT_DATE = '2014-09-28 11:13:09 +0200'
COMMIT_DATE_NL = COMMIT_DATE + '\n'


class TestMergeForward(sourcesteps.SourceStepMixin, TestCase):
    """
    Tests for L{MergeForward}.
    """

    env = {
        'GIT_AUTHOR_EMAIL': 'buildbot@clusterhq.com',
        'GIT_AUTHOR_NAME': 'ClusterHQ Buildbot',
        'GIT_COMMITTER_EMAIL': 'buildbot@clusterhq.com',
        'GIT_COMMITTER_NAME': 'ClusterHQ Buildbot',
    }
    date_env = dict(
        env,
        GIT_COMMITTER_DATE=COMMIT_DATE,
        GIT_AUTHOR_DATE=COMMIT_DATE
    )

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
            + ExpectShell.log('stdio', stdout=COMMIT_HASH_NL)
            + 0
        )
        self.expectOutcome(result=SUCCESS, status_text=['merge', 'forward'])
        self.expectProperty('lint_revision', COMMIT_HASH)
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
                        command=['git', 'log',
                                 '--format=%ci', '-n1'],
                        env=self.env)
            + ExpectShell.log('stdio', stdout=COMMIT_DATE_NL)
            + 0,
            ExpectShell(workdir='wkdir',
                        command=['git', 'merge',
                                 '--no-ff', '--no-stat',
                                 '-m', 'Merge forward.',
                                 'FETCH_HEAD'],
                        env=self.date_env)
            + 0,
            ExpectShell(workdir='wkdir',
                        command=['git', 'rev-parse', 'FETCH_HEAD'],
                        env=self.date_env)
            + ExpectShell.log('stdio', stdout=COMMIT_HASH_NL)
            + 0,
        )
        self.expectOutcome(result=SUCCESS, status_text=['merge', 'forward'])
        self.expectProperty('lint_revision', COMMIT_HASH)
        return self.runStep()

    def test_branch_with_merge_target(self):
        self.buildStep('destroy-the-sun-5000')
        self.properties.setProperty(
            'merge_target', 'merge-hash', source='test')
        self.expectCommands(
            ExpectShell(workdir='wkdir',
                        command=['git', 'fetch',
                                 'git://twisted', 'master'],
                        env=self.env)
            + 0,
            ExpectShell(workdir='wkdir',
                        command=['git', 'log',
                                 '--format=%ci', '-n1'],
                        env=self.env)
            + ExpectShell.log('stdio', stdout=COMMIT_DATE_NL)
            + 0,
            ExpectShell(workdir='wkdir',
                        command=['git', 'merge',
                                 '--no-ff', '--no-stat',
                                 '-m', 'Merge forward.',
                                 'merge-hash'],
                        env=self.date_env)
            + 0,
            ExpectShell(workdir='wkdir',
                        command=['git', 'rev-parse', 'merge-hash'],
                        env=self.date_env)
            + ExpectShell.log('stdio', stdout=COMMIT_HASH_NL)
            + 0,
        )
        self.expectOutcome(result=SUCCESS, status_text=['merge', 'forward'])
        self.expectProperty('lint_revision', COMMIT_HASH)
        return self.runStep()

    def test_releaseBranch(self):
        self.buildStep('release/flocker-1.2.3')
        self.expectCommands(
            ExpectShell(workdir='wkdir',
                        command=['git', 'rev-parse', 'HEAD~1'],
                        env=self.env)
            + ExpectShell.log('stdio', stdout=COMMIT_HASH_NL)
            + 0
        )
        self.expectOutcome(result=SUCCESS, status_text=['merge', 'forward'])
        return self.runStep()

    def test_maintenance_branch(self):
        self.buildStep('release-maintenance/flocker-1.2.3/destroy-the-sun-500')
        self.expectCommands(
            ExpectShell(workdir='wkdir',
                        command=['git', 'fetch',
                                 'git://twisted', 'release/flocker-1.2.3'],
                        env=self.env)
            + 0,
            ExpectShell(workdir='wkdir',
                        command=['git', 'log',
                                 '--format=%ci', '-n1'],
                        env=self.env)
            + ExpectShell.log('stdio', stdout=COMMIT_DATE_NL)
            + 0,
            ExpectShell(workdir='wkdir',
                        command=['git', 'merge',
                                 '--no-ff', '--no-stat',
                                 '-m', 'Merge forward.',
                                 'FETCH_HEAD'],
                        env=self.date_env)
            + 0,
            ExpectShell(workdir='wkdir',
                        command=['git', 'rev-parse', 'FETCH_HEAD'],
                        env=self.date_env)
            + ExpectShell.log('stdio', stdout=COMMIT_HASH_NL)
            + 0,
        )
        self.expectOutcome(result=SUCCESS, status_text=['merge', 'forward'])
        self.expectProperty('lint_revision', COMMIT_HASH)
        return self.runStep()


class VersionTests(TestCase):

    def test_isRelease(self):
        releases = [
            b'0.3.2',
            b'0.3.2dev1',
            b'0.3.2pre1',
            b'0.3.2.post11',
        ]
        non_releases = [
            b'0.3.2+1.gf661a6a',
            b'0.3.2dev1+1.gf661a6a',
            b'0.3.2pre1+1.gf661a6a',
            b'0.3.2.post1+1.gf661a6a',
        ]
        for version in releases:
            self.assertTrue(MergeForward._isRelease(version))
        for version in non_releases:
            self.assertFalse(MergeForward._isRelease(version))
