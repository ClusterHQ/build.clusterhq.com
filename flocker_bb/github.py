# This file is part of Buildbot.  Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright Buildbot Team Members

from __future__ import absolute_import

from twisted.python import log
from txgithub.api import GithubApi as GitHubAPI

from buildbot.status.results import (
    SUCCESS, EXCEPTION, FAILURE, WARNINGS, RETRY)

from flocker_bb.buildset_status import BuildsetStatusReceiver


import re
_re_github = re.compile("(?:git@github.com:|https://github.com/)(?P<repo_user>[^/]*)/(?P<repo_name>[^/]*)(?:\.git)?")  # noqa


class GitHubStatus(BuildsetStatusReceiver):
    """
    Send build status to GitHub.

    - When buildset is submitted, report status pending, for all builders in
      the buildset.
    - When a build start, report status building.
    - When a build stops, report status finished.
    """

    def __init__(self, token):
        """
        :param token: Token for GitHub API.
        """
        self._github = GitHubAPI(oauth2_token=token)
        BuildsetStatusReceiver.__init__(self, started=self.buildsetStarted)

    def _sendStatus(self, request):
        """
        Send commit status to github.

        Also logs the request and any errors from submitted.

        :param requests: the arguments to pass to github.
        """
        request.update({k: v.encode('utf-8') for k, v in request.iteritems()
                        if isinstance(v, unicode)})
        log.msg(format="github request %(request)s", request=request)
        d = self._github.repos.createStatus(**request)
        d.addErrback(
            log.err,
            'While sending start status to GitHub: ' + repr(request))

    @staticmethod
    def _simplifyBuilderName(name):
        """
        If the builder name starts with the codebase, remove it to avoid
        cluttering the status display with many redundant copies of the name.
        """
        name = name.rpartition('flocker-')[2]
        return name

    def builderAdded(self, builderName, builder):
        """
        Notify this receiver of a new builder.

        :return StatusReceiver: An object that should get notified of events on
            the builder.
        """
        return self

    def buildStarted(self, builderName, build):
        """
        Notify this receiver that a build has started.

        Reports to github that a build has started, along with a link to the
        build.
        """
        sourceStamps = [ss.asDict() for ss in build.getSourceStamps()]
        request, branch = self._getSourceStampData(sourceStamps)
        if 'sha' not in request:
            return

        request.update({
            'state': 'pending',
            'target_url': self.parent.getURLForThing(build),
            'description': 'Build started.',
            'context': self._simplifyBuilderName(builderName)
            })

        self._sendStatus(request)

    def buildFinished(self, builderName, build, results):
        """
        Notify this receiver that a build has started.

        Reports to github that a build has finished, along with a link to the
        build, and the build result.
        """
        sourceStamps = [ss.asDict() for ss in build.getSourceStamps()]
        request, branch = self._getSourceStampData(sourceStamps)

        got_revision = build.getProperty('got_revision', {})
        sha = got_revision.get('flocker') or request.get('sha')
        if not sha:
            return
        request['sha'] = sha

        STATE = {
            SUCCESS: "success",
            WARNINGS: "success",
            FAILURE: "failure",
            EXCEPTION: "error",
            RETRY: "pending",
        }

        request.update({
            'state': STATE[build.getResults()],
            'target_url': self.parent.getURLForThing(build),
            'description': " ".join(build.getText()),
            'context': self._simplifyBuilderName(builderName)
            })

        self._sendStatus(request)

    def _getSourceStampData(self, sourceStamps):
        """
        Extract the repository and revision of the codebase this
        reciever reports on.

        :param list sourceStamps: List of source stamp dictionaries.

        :return: Dictionary with keys `'repository'` and `'sha'` suitable
            for passing to github to report status for this source stamp.
        """
        request = {}
        for sourceStamp in sourceStamps:
            if sourceStamp['codebase'] == "flocker":
                m = _re_github.match(sourceStamp['repository'])
                request.update(m.groupdict())

                if sourceStamp['revision']:
                    request['sha'] = sourceStamp['revision']

                branch = sourceStamp['branch']

                break
        else:
            return {}, ''

        return request, branch

    def buildsetStarted(self, (sourceStamps, buildRequests), status):
        """
        Notify this receiver that a buildset has been submitted.

        Reports to github that builds are pending, for each build
        request comprising this buildset.
        """
        request, branch = self._getSourceStampData(sourceStamps)

        if 'sha' not in request:
            return

        request.update({
            'state': 'pending',
            'description': 'Build pending.'
            })

        for buildRequest in buildRequests:
            r = request.copy()
            r.update({
                'context': self._simplifyBuilderName(
                    buildRequest['builderName']),
            })
            self._sendStatus(r)


def createGithubStatus(codebase, token):
    return GitHubStatus(token=token)
