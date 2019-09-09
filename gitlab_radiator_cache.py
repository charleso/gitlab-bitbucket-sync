#!/usr/bin/env python

"""
This module is a _very_ simple Gitlab radiator dashboard.

It also supports a rudimentary "investigation" for removing individual builds
from the radiator to avoid "red build fatigue".

## HTTP Query parameters:

branch: [optional, list, default: master and develop branches]
  A list of branches to check for broken builds.

refresh: [optional, default: 60]
  Number of seconds before refreshing the page
"""

import cgi, json, os, urlparse, re
from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
from SocketServer import ThreadingMixIn

gitlab_builds_file = os.getenv("GITLAB_PIPELINE_CACHE")
port = os.getenv("GITLAB_RADIATOR_PORT") or "9004"
investigations_file = os.getenv("GITLAB_RADIATOR_INVESTIGATIONS") or "/tmp/gitlab_radiator_investigations"
# Regex on the full `PROJECT/repository`
default_project_filters = []

###### Gitlab API ######

def load_builds():
    try:
      builds = json.loads(open(gitlab_builds_file, 'r').read())
    except:
      builds = {}
    return builds

# https://docs.gitlab.com/ce/user/project/integrations/webhooks.html#build-events
def get_builds(builds, filterBuild):
    projects = [
      { "project": {
          "name": project.split("/")[1],
          "namespace": { "name": project.split("/")[0] },
        },
        "pipeline": [ {
            "id": branch["object_attributes"]["id"],
            "status": branch["object_attributes"]["status"],
            "web_url": branch["project"]["web_url"] + "/pipelines/" + str(branch["object_attributes"]["id"])
          }
          for branch in builds[project].values()
          if filterBuild(branch)
        ],
      }
      for project in builds
    ]
    return {
        "projects": projects,
        "running": build_status_count(builds, "running"),
        "pending": build_status_count(builds, "created") + build_status_count(builds, "pending"),
      }

def filter_by_branch_status(branches, tags):
  return lambda build: all([
      build["object_attributes"]["status"] in ["failed"],
      any([
        build["object_attributes"]["ref"] in branches,
        tags and build["object_attributes"]["tag"],
      ]),
    ])

def filter_by_project_name(projects, regexs):
    for regex in regexs:
        projects = [
          p for p in projects
          if re.search(regex, p['project']['namespace']['name'] + "/" + p['project']['name']) is None
          ]
    return projects

###### Radiator #######

def read_investigations():
  try:
      with open(investigations_file, "r") as f:
          investigations = set(f.read().splitlines())
  except IOError:
      investigations = []
  return investigations

def append_investigation(g, p, i):
    with open(investigations_file, "a+") as f:
        f.write("{} {} {}\n".format(g, p, i))

def build_html(redirect, x):
    p = x["project"]
    y = ["""
            <div class="status {}">
                <a href="{}">{} / {}</a>
                <form method="POST" action="/ignore">
                    <input type="hidden" name="group" value="{}" />
                    <input type="hidden" name="project" value="{}" />
                    <input type="hidden" name="id" value="{}" />
                    <input type="hidden" name="redirect" value="{}" />
                    <button type="submit">X</button>
                </form>
            </div>
        """.strip().format(
            b["status"],
            b["web_url"],
            p["namespace"]["name"],
            p["name"],
            p["namespace"]["name"],
            p["name"],
            b["id"],
            redirect,
        )
        for b in x["pipeline"]
    ]
    return "".join(y)

def filter_builds_by_investigation(i, ps):
    ps2 = []
    for x in ps:
        p = x["project"]
        b2 = { "project": p, "pipeline": [] }
        for b in x["pipeline"]:
            line = "{} {} {}".format(p["namespace"]["name"], p["name"], b["id"])
            if line not in i:
                b2["pipeline"].append(b)
        if len(b2["pipeline"]) > 0:
          ps2.append(b2)
    return ps2

def pipeline_success(ps):
    return sum(sum(1 for y in p["pipeline"] if y["status"] == "failed") for p in ps) == 0

def build_status_count(ps, s):
    return sum(
        sum(
          sum(1 for b in (ps[p][r]["builds"] or []) if b["status"] == s)
          for r in ps[p]
        ) for p in ps
    )

def html_pipelines(path, refresh, ps, bs):
    return """
        <html>
          <head>
            <meta http-equiv="refresh" content="{}">
            <link rel="icon" href="https://gitlab.com/gitlab-org/gitlab-ee/raw/1e12989a39709d764d720907534d66769ba170ac/app/assets/images/ci_favicons/canary/favicon_status_{}.ico" ref="shortcut icon" />
            <style>
              body.success {{
                background-color: #30b030;
              }}
              form {{
                margin-block-end: 0px;
                display: inline;
              }}
              .running-count {{
		position: fixed;
		top: 50%;
		left: 50%;
                transform: translate(-50%, -50%);
                font-size: 128px;
              }}
              .running-count td {{
                text-align: center;
              }}
              #timer {{
                font-size: 46px;
                position: fixed;
                bottom: 0px;
                right: 0px;
              }}
              .status {{
                margin: 10px;
                padding: 10px;
                font-size: 72px;
              }}
              .status a {{
                text-decoration: none;
              }}
              .failed {{
                background-color: #d9534f;
              }}
              .failed a {{
                color: white;
              }}
              .status button {{
                display: none;
              }}
              .status.failed button {{
                display: inline;
              }}
              .running {{
                background-color: #1f78d1;
              }}
              .running a {{
                color: white;
              }}
              .pending {{
                background-color: #fc9403;
              }}
              .pending a {{
                color: white;
              }}
            </style>
            <script type="text/javascript">
              var time = 0
              var updateTimer = function() {{
                time = time + 1;
                document.getElementById("timer").innerHTML = time.toString() + "s"
              }}
              setInterval(updateTimer, 1000)
            </script>
          </head>
          <body class="{}">
            {}
            <table class="running-count">
              <tr><td>{}</td><td style="color: #1f78d1;">&#x25b6;</span></td></tr>
              <tr><td>{}</td><td style="color: #fc9403;">&#10073;&#10073;</span></td></tr>
            </div>
            <div id="timer"></div>
          </body>
        </html>
    """.strip().format(
      refresh,
      "success" if pipeline_success(ps) else "failed",
      "success" if pipeline_success(ps) else "",
      "".join(map(lambda x: build_html(path, x), ps)),
      bs["running"],
      bs["pending"],
    )

class RadiatorRequestHandler(BaseHTTPRequestHandler):

    def do_POST(self):
        form = cgi.FieldStorage(fp = self.rfile, headers = self.headers, environ = {
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": self.headers["Content-Type"],
        })

        append_investigation(form.getvalue("group"), form.getvalue("project"), form.getvalue("id"))

        self.send_response(302)
        self.send_header("Location", form.getvalue("redirect", "/"))
        self.end_headers()

    def do_GET(self):
        url = urlparse.urlparse(self.path)
        query = urlparse.parse_qs(url.query)

        if url.path == "/":

            branches = query.get("branch") or ["master", "develop"]
            tags = query.get("tags") != ["false"]
            project_filter = query.get("project_filter") or default_project_filters

            lb = load_builds()
            bs = get_builds(lb, filter_by_branch_status(branches, tags))
            ps = filter_by_project_name(bs["projects"], project_filter)

            self.send_response(200 if pipeline_success(ps) else 400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()

            self.wfile.write(html_pipelines(
                self.path,
                "".join(query.get("refresh") or ["60"]),
                filter_builds_by_investigation(read_investigations(), ps),
                bs,
            ))
            self.wfile.close()

        # FIXME Same as "/", we should use Accept headers instead
        elif url.path == "/status":

            branches = query.get("branch") or ["master", "develop"]
            tags = query.get("tags") != ["false"]
            project_filter = query.get("project_filter") or default_project_filters

            lb = load_builds()
            builds = get_builds(lb, filter_by_branch_status(branches, tags))
            fp = filter_by_project_name(builds["projects"], project_filter)
            ps = filter_builds_by_investigation(read_investigations(), fp)

            self.send_response(200 if pipeline_success(ps) else 400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()

            self.wfile.write(json.dumps(ps, indent=2))
            self.wfile.close()

        elif url.path == "/current":

            statuses = query.get("status") or ["running", "pending"]
            project_filter = query.get("project_filter") or default_project_filters

            lb = load_builds()
            bs = get_builds(lb, lambda build:
              build["object_attributes"]["status"] in statuses
            )
            ps = filter_by_project_name(bs["projects"], project_filter)

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()

            self.wfile.write(html_pipelines(
                self.path,
                "".join(query.get("refresh") or ["60"]),
                ps,
                bs,
            ))
            self.wfile.close()

        elif url.path == "/all":
            lb = load_builds()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(lb, indent=2))
            self.wfile.close()

        elif url.path == "/investigations":

            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()

            self.wfile.write("\n".join(read_investigations()))
            self.wfile.close()

        else:

            self.send_response(404)
            self.end_headers()
            return



# https://pymotw.com/2/BaseHTTPServer/index.html#module-BaseHTTPServer
# https://stackoverflow.com/questions/43146298/http-request-from-chrome-hangs-python-webserver
class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in a separate thread."""

httpd = ThreadedHTTPServer(("", int(port)), RadiatorRequestHandler)
print("serving at port", port)
httpd.serve_forever()
