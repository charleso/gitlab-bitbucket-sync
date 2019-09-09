#!/usr/bin/env python

from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
import json
import os

def project_is_valid(s):
    return [] == [c for c in s if not (c.isalpha() or c == '-')]

def repo_is_valid(s):
    return [] == [c for c in s if not (c.isalpha() or c.isdigit() or c == '.' or c == '-' or c == '_')]

def newHttpRequestHandler(queue):
  # https://stackoverflow.com/questions/31371166/reading-json-from-simplehttpserver-post-data
  class HttpRequestHandler(BaseHTTPRequestHandler):
      def do_POST(self):
          data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
          # https://confluence.atlassian.com/bitbucketserver/post-service-webhook-for-bitbucket-server-776640367.html
          project = data["repository"]["project"]["key"]
          repo = data["repository"]["slug"]

          if not project_is_valid(project):
            self.send_response(400)
            self.end_headers()
            return

          if not repo_is_valid(repo):
            self.send_response(400)
            self.end_headers()
            return

          with open(queue, "a+") as f:
             f.write("{}/{}\n".format(project, repo))
          self.send_response(200)
          self.end_headers()
          return
  return HttpRequestHandler

def run(port):
    q = os.getenv("QUEUE")
    httpd = HTTPServer(("", port), newHttpRequestHandler(q))
    print "Starting httpd..."
    httpd.serve_forever()

if __name__ == "__main__":
    from sys import argv
    if len(argv) == 2:
        run(port=int(argv[1]))
    else:
        run(port=9000)
