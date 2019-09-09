#!/usr/bin/env python

import json, httplib, os, sys, urlparse
# https://stackoverflow.com/questions/31827012/python-importing-urllib-quote
try:
  from urllib import quote
except ImportError:
  from urllib.parse import quote

gitlab_api_url = os.getenv("GITLAB_URL") + "/api/v4"
gitlab_token = open(os.getenv("GITLAB_TOKEN_SECRET")).read().rstrip()
gitlab_webhook_url = os.getenv("GITLAB_WEBHOOK_URL")

# https://docs.python.org/2/library/httplib.html
def http(method, url, headers = {}, body = None):
    o = urlparse.urlparse(gitlab_api_url)
    c = httplib.HTTPSConnection(o.hostname) if o.scheme == "https" else httplib.HTTPConnection(o.hostname, o.port)
    headers["Private-Token"] = gitlab_token
    c.request(method, o.path + url, body, headers)
    return c

def http_get_json(url, headers = {}):
    req = http("GET", url, headers)
    resp = req.getresponse()
    if resp.status != 200:
        raise ValueError("Invalid response code: {}\n  {}".format(resp.status, resp.read()))
    return json.loads(resp.read())

def http_post_json(url, body, headers = {}):
    headers["Content-Type"] = "application/json"
    req = http("POST", url, headers, json.dumps(body))
    resp = req.getresponse()
    if resp.status != 201:
        raise ValueError("Invalid response code: {}\n  {}".format(resp.status, resp.read()))

def http_put_json(url, body, headers = {}):
    headers["Content-Type"] = "application/json"
    req = http("PUT", url, headers, json.dumps(body))
    resp = req.getresponse()
    if resp.status != 200:
        raise ValueError("Invalid response code: {}\n  {}".format(resp.status, resp.read()))

def http_delete_json(url, headers = {}):
    req = http("DELETE", url, headers)
    resp = req.getresponse()
    if resp.status != 204:
        raise ValueError("Invalid response code: {}\n  {}".format(resp.status, resp.read()))

# NOTE: We both search _and_ then check the path because searching can be fuzzy
# ie. searching for a group 'REL' return anything with that prefix
# We also need to search because there is a default limit of 20 results and otherwise
# we would need to fully paginate results.
# https://docs.gitlab.com/ee/api/#pagination-link-header
# We're assuming that searching _should_ always return < 20 results

def get_groups_by_path(project_name):
  return [
    g["id"] for g in http_get_json("/groups?search=" + project_name)
    if g["path"].lower() == project_name.lower()
  ]

def get_projects_by_key(group_id):
  return [
    p["id"] for p in http_get_json("/projects?search=" + repo_name)
    # NOTE We need to filter by namespace (ie project) for repositories with the same name
    if p["path"].lower() == repo_name.lower() and p["namespace"]["id"] == group_id
  ]

def create_group(project_name):
  groups = get_groups_by_path(project_name)
  if not groups:
      http_post_json("/groups", {
          "name": project_name
        , "path": project_name
        , "visibility": "internal"
        })
      groups = get_groups_by_path(project_name)

  return groups[0]

def create_project(group_id, repo_name):
  projects = get_projects_by_key(group_id)
  if not projects:
      http_post_json("/projects", {
          "name": repo_name
        , "path": repo_name
        , "namespace_id": group_id
        # https://docs.gitlab.com/ee/api/projects.html#project-visibility-level
        , "visibility": "internal"
        })
      projects = get_projects_by_key(group_id)

  return projects[0]

def update_hooks(project_id):
  # FIXME This is stupid, we can't create group (or system) level integrations
  hooks = http_get_json("/projects/{}/hooks".format(project_id))
  if not [h for h in hooks if h["url"] == gitlab_webhook_url]:
      http_post_json("/projects/{}/hooks".format(project_id), {
          "url": gitlab_webhook_url
        , "push_events": False
        , "job_events": True
        , "pipeline_events": True
        })

  # NOTE: Previously we created these hooks with just job_events, but we want jobs and pipelines now
  for h in hooks:
      if h["url"] == gitlab_webhook_url:
          http_put_json("/projects/{}/hooks/{}".format(project_id, h["id"]), {
              "url": gitlab_webhook_url
            , "push_events": False
            , "job_events": True
            , "pipeline_events": True
            })

def unprotect_branch(project_id):
  # Unfortunately default branches are protected by default and there isn't a way to disable
  # them globally. It's not what we want in this mirror setting. Always turn it off.
  # https://gitlab.com/gitlab-org/gitlab-ce/issues/34155
  ps = http_get_json("/projects/{}/protected_branches".format(project_id))
  for b in ps:
    http_delete_json("/projects/{}/protected_branches/{}".format(project_id, quote(b["name"], safe="")))


if len(sys.argv) == 3 and sys.argv[1] == "create":
  repo_path = sys.argv[2]
  project_name = repo_path.split("/")[0]
  repo_name = repo_path.split("/")[1]

  group_id = create_group(project_name)
  project_id = create_project(group_id, repo_name)
  update_hooks(project_id)

  # Print so callers can re-use in subsequent api calls after we have updated the repository
  print(project_id)

elif len(sys.argv) == 3 and sys.argv[1] == "update":
  project_id = sys.argv[2]
  unprotect_branch(project_id)

else:
  sys.stderr.write("""Unknown arguments. Usage:
  create GROUP/PROJECT
  update PROJECT_ID
""")
  sys.exit(1)
