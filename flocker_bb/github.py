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

from buildbot.status.builder import SUCCESS

from flocker_bb.buildset_status import BuildsetStatusReceiver


import re
_re_github = re.compile("(?:git@github.com:|https://github.com/)(?P<repo_user>[^/]*)/(?P<repo_name>[^/]*)(?:\.git)?")

class GitHubStatus(object):
    """
    Send build status to GitHub.
    """

    def __init__(self, token):
        """
        Token for GitHub API.
        """
        self._token = token
        self._github = GitHubAPI(oauth2_token=self._token)


    def _getSourceStampData(self, sourceStamps):
        request = {}
        for sourceStamp in sourceStamps:
            if sourceStamp['codebase'] == "flocker":
                m = _re_github.match(sourceStamp['repository'])
                request.update(m.groupdict())

                if sourceStamp['revision']:
                    request['sha'] = sourceStamp['revision']

                branch = sourceStamp['branch']

                break

        return request, branch

    @staticmethod
    def _simplifyBuilderName(name):
        name = name.rpartition('flocker-')[2]
        return name

    def _shouldReportBuild(self, buildRequests):
        for buildRequest in buildRequests:
            for prop, value, source in buildRequest['properties']:
                if prop == 'github-status' and not value:
                    return False
        return True

    def buildsetStarted(self, (sourceStamps, buildRequests), status):
        if not self._shouldReportBuild(buildRequests):
            log.msg(format="Ignoring build because of github-status.")

        request, branch = self._getSourceStampData(sourceStamps)

        if not request.has_key('sha'):
            return

        request.update({
            'state': 'pending',
            'target_url': status.getBuildbotURL() + 'boxes-flocker?branch=' + branch,
            'description': 'Starting build.'
            })

        log.msg("github request %(request)s", request=request)
        d = self._sendStatus(request)
        d.addErrback(
            log.err,
            'While sending start status to GitHub: ' + repr(request))

    def _sendStatus(self, request):
        request.update({k: v.encode('utf-8') for k, v in request.iteritems() if isinstance(v, unicode)})
        return self._github.repos.createStatus(**request)


    def buildsetFinished(self, (sourceStamps, buildRequests), status):
        if not self._shouldReportBuild(buildRequests):
            log.msg(format="Ignoring build because of github-status.")

        request, branch = self._getSourceStampData(sourceStamps)

        failed = []
        revisions = set()
        for buildRequest in buildRequests:
            build = max(buildRequest['builds'], key=lambda build: build['number'])
            builderName = self._simplifyBuilderName(build['builderName'])
            revisions.add([
                v['flocker'] for (k, v, _) in build['properties']
                    if k == 'got_revision'][0])

            if build['results'] != SUCCESS:
                failed.append(builderName)

        if not request.has_key('sha'):
            if len(revisions) == 1:
                request['sha'] = revisions.pop()
            else:
                return

        if failed:
            request['state'] = 'failure'
            request['description'] = 'Build failed: ' + ', '.join(failed)
        else:
            request['state'] = 'success'
            request['description'] = 'Build succeeded'

        request['target_url'] = status.getBuildbotURL() + 'boxes-flocker?branch=' + branch

        d = self._sendStatus(request)
        d.addErrback(
            log.err,
            'While sending start status to GitHub: ' + repr(request))

def codebaseStatus(codebase, token):
    writer = GitHubStatus(token=token)
    status = BuildsetStatusReceiver(
            started=writer.buildsetStarted,
            finished=writer.buildsetFinished)
    return status
