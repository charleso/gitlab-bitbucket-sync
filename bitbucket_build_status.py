#!/usr/bin/env python

from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
import json
import os
import httplib

def newHttpRequestHandler(bitbucketHost, bitbucketPort, bitbucketToken, queue):
  # https://stackoverflow.com/questions/31371166/reading-json-from-simplehttpserver-post-data
  # https://docs.gitlab.com/ce/user/project/integrations/webhooks.html#build-events
  class HttpRequestHandler(BaseHTTPRequestHandler):
      def do_POST(self):
          data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))

          object_kind = data.get("object_kind")

          # NOTE: Previously we just handled build events, but now we want to track all pipelines now too
          if object_kind == "pipeline" or object_kind == "build" :
              if queue:
                  with open(queue, "a+") as f:
                      # NOTE We want this to only be on a single line
                      f.write(json.dumps(data, indent=None) + "\n")

          if object_kind != "build":
              self.send_response(200)
              self.end_headers()
              return

          # https://developer.atlassian.com/server/bitbucket/how-tos/updating-build-status-for-commits/
          if data["build_status"] == "failed" or data["build_status"] == "canceled":
              state = "FAILED"
          elif data["build_status"] == "success":
              state = "SUCCESSFUL"
          else:
              state = "INPROGRESS"
          dataOut = {
            "state": state,
            "key": data["build_name"],
            "url": "{}/-/jobs/{}".format(data["repository"]["homepage"], data["build_id"]),
          }

          # https://docs.python.org/2/library/httplib.html
          c = httplib.HTTPSConnection(bitbucketHost) if bitbucketPort == 443 else httplib.HTTPConnection(bitbucketHost, bitbucketPort)
          c.request("POST", "/rest/build-status/1.0/commits/{}".format(data["commit"]["sha"]), body=json.dumps(dataOut), headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + bitbucketToken,
          })
          self.send_response(c.getresponse().status)
          self.end_headers()
          return
  return HttpRequestHandler

def run(port):
    b = os.getenv("BITBUCKET_HOST")
    p = int(os.getenv("BITBUCKET_PORT"))
    t = open(os.getenv("BITBUCKET_TOKEN_SECRET"), 'r').read().rstrip()
    q = os.getenv("GITLAB_PIPELINE_QUEUE")
    httpd = HTTPServer(("", port), newHttpRequestHandler(b, p, t, q))
    print("Starting httpd...")
    httpd.serve_forever()

if __name__ == "__main__":
    from sys import argv

if len(argv) == 2:
    run(port=int(argv[1]))
else:
    run(port=9001)
