#!/usr/bin/env python

import datetime
import json
import os
import sys

"""
This module takes a single argument of json in the gitlab pipeline _or_ build event format

- https://docs.gitlab.com/ce/user/project/integrations/webhooks.html#pipeline-events
- https://docs.gitlab.com/ce/user/project/integrations/webhooks.html#job-events

NOTE: In the documentation everything has the word "job" in it, but for the version of gitlab
we have deployed they are still called "build" events and have json elements with "build_" in them.
I'm not 100% sure if this because we're not running the latest version, or the documentation is just wrong.

And updates a single GITLAB_PIPELINE_CACHE file cached per-project/per-branch.
This can file can then be used for the gitlab-radiator cache.

Another way of thinking about this is we are "event sourcing" the current state of gitlab
based on the pipeline/build events.

For just displaying the currently "broken" pipelines for a given branch things are quite straightforward.
However, Gitlab also doesn't give a good way of seeing how many _jobs_ are running and pending,
which helps give a sense for how long we might have to wait for our builds to start at any given time.

Originally we just used the pipeline events, which contain both the overall status
as well as an individual build status. Unfortunately there turned out to be a major problem,
the events are only fired when the _pipeline_ status "changes", not each build.
So as the pipeline goes from pending to running you can see what happens, but there
isn't always an event as each build goes from pending to running until the whole pipeline finishes.

We then augmented the cache with data from build events. However, unfortunately the events are
not entirely consistent. In particular the pipeline builds have "pending" and "created" builds,
but the builds themselves don't distinguish between the two. Unfortunately that means we can't
get a 100% accurate count of _actually_ pending builds due to lack of resources because we
also include the "created" builds that are in a later, waiting stages a pipeline (and don't need
a resource just yet). There doesn't appear to be _any_ tell tail sign from the build event
which is which.
"""

build_file = os.getenv("GITLAB_PIPELINE_CACHE")

build = json.loads(sys.argv[1])

try:
  builds = json.loads(open(build_file, 'r').read())
except:
  builds = {}

if build["object_kind"] == "pipeline":

  if not builds.get(build["project"]["path_with_namespace"]):
      builds[build["project"]["path_with_namespace"]] = {}

  job = builds[build["project"]["path_with_namespace"]].get(build["object_attributes"]["ref"])
  if job:
    old_builds = build["builds"]

    # Pipelines only keep track of the "latest" build for each name,
    # we want them _all_ to track all the pending/running builds
    # Instead we rely on build_events to update them correctly

    build["builds"] = job.get("builds") or []

    # Update build statues based on the pipeline event, this may be the last time we see it
    # Can happen for cancelled pipelines
    for b1 in build["builds"]:
      for b2 in old_builds:
        if b1["id"] == b2["id"]:
          b1["status"] = b2["status"]

    # Only update the pipeline if it's the "latest" one for this branch
    # Otherwise we accidentally hide "running" pipelines when someone updates a branch and the first build passes
    # We're relying on the fact that the pipeline IDs increase each time
    update = build["object_attributes"]["id"] >= job["object_attributes"]["id"]
  else:
    update = True

  if update:
    builds[build["project"]["path_with_namespace"]][build["object_attributes"]["ref"]] = build

elif build["object_kind"] == "build":

  project_name = build["project_name"].replace(' / ', '/')

  # Only update what we know about, no partial pipeline data please
  if builds.get(project_name):
    ref = builds[project_name].get(build["ref"])
    if ref:
      # Initially we didn't keep refs, make sure we add it now
      if not ref.get("builds"):
        ref["builds"] = []
      if not any(job["id"] == build["build_id"] for job in ref["builds"]):
        ref["builds"].append({"id": build["build_id"]})
      for job in ref["builds"]:
        if job["id"] == build["build_id"]:
          job["status"] = build["build_status"]
          job["started_at"] = build["build_started_at"]
          job["finished_at"] = build["build_finished_at"]

else:
  raise Exception("Unknown object_kind: {}".format(build["object_kind"]))


with open(build_file, 'w') as f:
  f.write(json.dumps(builds, indent=2))
