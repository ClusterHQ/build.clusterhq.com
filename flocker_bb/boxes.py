import os
import time

from buildbot.status.web.base import HtmlResource, map_branches, build_get_class, path_to_builder, path_to_build
from buildbot.status.builder import SUCCESS, WARNINGS, FAILURE, SKIPPED, EXCEPTION, RETRY
from buildbot.status import html
from buildbot.util import formatInterval
from twisted.internet import defer

from twisted.web.template import tags, flattenString
from twisted.web.vhost import NameVirtualHost
from twisted.web.static import File


_backgroundColors = {
    SUCCESS: "green",
    WARNINGS: "orange",
    FAILURE: "red",
    SKIPPED: "blue",
    EXCEPTION: "purple",
    RETRY: "purple",

    # This is a buildbot bug or something.
    None: "yellow",
    }

# /boxes[-things]
#  accepts builder=, branch=, num_builds=
class TenBoxesPerBuilder(HtmlResource):
    """This shows a narrow table with one row per build. The leftmost column
    contains the builder name. The next column contains the results of the
    most recent build. The right-hand column shows the builder's current
    activity.

    builder=: show only builds for this builder. Multiple builder= arguments
              can be used to see builds from any builder in the set.
    """

    title = "Latest Build"

    def __init__(self, categories=None):
        HtmlResource.__init__(self)
        self.categories = categories


    @defer.inlineCallbacks
    def content(self, req, context):
        body = yield self.body(req)
        context['content'] = body
        template = req.site.buildbot_service.templates.get_template("empty.html")
        defer.returnValue(template.render(**context))


    @defer.inlineCallbacks
    def body(self, req):
        status = self.getStatus(req)
        authz = self.getAuthz(req)

        builders = req.args.get("builder", status.getBuilderNames(categories=self.categories))
        branches = [b for b in req.args.get("branch", []) if b]
        if not branches:
            branches = ["master"]
        if branches and "master" not in branches:
            defaultCount = "1"
        else:
            defaultCount = "10"
        num_builds = int(req.args.get("num_builds", [defaultCount])[0])

        tag = tags.div()

        tag(tags.script(src="hlbb.js"))
        tag(tags.h2(style="float:left; margin-top:0")("Latest builds: ", ", ".join(branches)))

        form = tags.form(method="get", action="", style="float:right",
                         onsubmit="return checkBranch(branch.value)")
        form(tags.input(type="test", name="branch", placeholder=branches[0], size="40"))
        form(tags.input(type="submit", value="View"))
        if (yield authz.actionAllowed('forceAllBuilds', req)):
            # XXX: Unsafe interpolation
            form(tags.button(type="button",
                onclick="forceBranch(branch.value || %r, %r)"
                        % (branches[0], self.categories,)
                )("Force"))
        tag(form)


        table = tags.table(style="clear:both")
        tag(table)

        for bn in builders:
            builder = status.getBuilder(bn)
            state = builder.getState()[0]
            if state == 'building':
                state = 'idle'
            row = tags.tr()
            table(row)
            builderLink = path_to_builder(req, builder)
            row(tags.td(class_="box %s" % (state,))(tags.a(href=builderLink)(bn)))

            builds = sorted([
                    build for build in builder.getCurrentBuilds()
                    if set(map_branches(branches)) & builder._getBuildBranches(build)
                    ], key=lambda build: build.getNumber(), reverse=True)

            builds.extend(builder.generateFinishedBuilds(map_branches(branches),
                                                         num_builds=num_builds))
            if builds:
                for b in builds:
                    url = path_to_build(req, b)
                    try:
                        label = b.getProperty("got_revision")
                    except KeyError:
                        label = None
                    # Label should never be "None", but sometimes
                    # buildbot has disgusting bugs.
                    if not label or label == "None" or len(str(label)) > 20:
                        label = "#%d" % b.getNumber()
                    if b.isFinished():
                        text = b.getText()
                    else:
                        when = b.getETA()
                        if when:
                            text = [
                                "%s" % (formatInterval(when),),
                                "%s" % (time.strftime("%H:%M:%S", time.localtime(time.time() + when)),)
                                ]
                        else:
                            text = []

                    row(tags.td(
                            align="center",
                            bgcolor=_backgroundColors[b.getResults()],
                            class_=("LastBuild box ", build_get_class(b)))([
                                (element, tags.br)
                                for element
                                in [tags.a(href=url)(label)] + text]) )
            else:
                row(tags.td(class_="LastBuild box")("no build"))
        defer.returnValue((yield flattenString(req, tag)))



class FlockerWebStatus(html.WebStatus):
    def __init__(self, **kwargs):
        html.WebStatus.__init__(self, **kwargs)
        self.putChild("boxes-flocker", TenBoxesPerBuilder(categories=['flocker']))

    def setupSite(self):
        html.WebStatus.setupSite(self)
        resource = self.site.resource

        docdevPath = os.path.join(self.master.basedir, "private_html", "docs")
        docdev = File(docdevPath)

        File.contentTypes[".py,cover"] = "text/plain"
        File.contentTypes[".svg"] = "image/svg+xml"

        # Historical name
        resultsPath = os.path.join(self.master.basedir, "private_html")
        results = File(resultsPath)
        resource.putChild(b'results', results)
        # Keep this around so old links work.
        resource.putChild(b'private', results)

        vhost = NameVirtualHost()
        vhost.default = resource
        vhost.addHost('doc-dev.clusterhq.com', docdev)
        # Keep this around so old links work
        vhost.addHost('doc.flocker.hybridcluster.net', docdev)
        self.site.resource = vhost
