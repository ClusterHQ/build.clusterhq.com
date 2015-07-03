from buildbot.sourcestamp import SourceStamp
from buildbot.status.build import BuildStatus
from buildbot.status.builder import BuilderStatus
from twisted.trial.unittest import TestCase

from flocker_bb.util import getBranch


class TestGetBranch(TestCase):

    def makeBuildStatus(self, branches):
        """
        Make an IBuildStatus that has source stamps for the given branches.
        """
        sourceStamps = [SourceStamp(branch=branch) for branch in branches]
        # This is the bare minimum we can specify to construct a
        # `BuildStatus`.
        build = BuildStatus(BuilderStatus(None, None, None, None), None, None)
        build.setSourceStamps(sourceStamps)
        return build

    def test_singleBranch(self):
        """
        If a build has only one source stamp, getBranch returns its branch.
        """
        status = self.makeBuildStatus(['destroy-the-sun-floc-1234'])
        self.assertEqual('destroy-the-sun-floc-1234', getBranch(status))

    def test_manyBranches(self):
        """
        If a build has more than one source stamp, getBranch returns the
        branch of the first one.
        """
        status = self.makeBuildStatus(['destroy-the-sun-floc-1234', 'another'])
        self.assertEqual('destroy-the-sun-floc-1234', getBranch(status))

    def test_noBranch(self):
        """
        If a build has no source stamps, getBranch raises a ValueError.

        This is a pathological case. If buildbot is functioning correctly then
        it will never happen.
        """
        status = self.makeBuildStatus([])
        self.assertRaises(ValueError, getBranch, status)
