#!/bin/sh -eu

###
# This idempotent script a single "project/repo" argument, ensures that the
# relevant Gitlab "group/project" exists and then mirrors the git repository
# from Bitbucket.
# It also setups up a per-project webhook for the bitbucket build statuses.
# Ideally we can configure this globally at some point.
###

: ${GIT_SOURCE_URL:?GIT_SOURCE_URL}
: ${GIT_TARGET_URL:?GIT_TARGET_URL}
: ${GITLAB_URL:?GITLAB_URL}
: ${GITLAB_WEBHOOK_URL:?GITLAB_WEBHOOK_URL}
# Where git repositories are cached on this machine
: ${GIT_CACHE:?GIT_CACHE}
: ${GITLAB_TOKEN_SECRET:?GITLAB_TOKEN_SECRET}

GITLAB_TOKEN=$(cat "$GITLAB_TOKEN_SECRET")

REPO_PATH=$1
GITLAB_API_URL="${GITLAB_URL}/api/v4"
PROJECT_NAME="$(echo $REPO_PATH | cut -d '/' -f 1)"
REPO_NAME="$(echo $REPO_PATH | cut -d '/' -f 2)"

init_repo() {
  # Previous versions of the script didn't use project, which gave rise to clashes
  if [ -d "${GIT_CACHE}/${REPO_NAME}" ]; then
    mkdir -p "${GIT_CACHE}/${PROJECT_NAME}"
    mv "${GIT_CACHE}/${REPO_NAME}" "${GIT_CACHE}/${PROJECT_NAME}/${REPO_NAME}"
  else
    mkdir -p "${GIT_CACHE}/${PROJECT_NAME}/${REPO_NAME}"
  fi

  cd "${GIT_CACHE}/${PROJECT_NAME}/${REPO_NAME}"
  git init --bare
  git remote add --mirror=fetch source "" || true
  git remote set-url source "${GIT_SOURCE_URL}/${REPO_PATH}.git"

  # NOTE: Please be careful not to prune here, gitlab doesn't let us delete the default branch
  # We have a chicken-egg problem where if we need to push a new default branch first before
  # (potentially) deleting the old one, which _does_ happen usually when we start a new repo.
  git fetch source
}

git_mirror() {
  # If push fails try just one more time to avoid alerting on non-fatal "git fetch_pack: expected ACK/NAK"
  git push --mirror "${GIT_TARGET_URL}/${REPO_PATH}.git" \
    || git push --mirror "${GIT_TARGET_URL}/${REPO_PATH}.git"
}

default_branch() {
  cd "${GIT_CACHE}/${PROJECT_NAME}/${REPO_NAME}"
  # https://stackoverflow.com/questions/15227263/how-to-update-the-head-branch-in-a-mirrored-clone
  # FIXME The version of git in production is 1.8.x which doesn't support ls-remote --symref
  DEFAULT_BRANCH=$(git remote show source | grep "HEAD branch:" | sed 's/HEAD branch://g' | awk '{ print $1 }')
  if [ ! -z "$DEFAULT_BRANCH" ]; then
    curl -k -s -f \
      -H "Private-Token: $GITLAB_TOKEN" \
      -X PUT \
      -H "Content-Type: application/json" \
      -d '{"default_branch": "'$DEFAULT_BRANCH'"}' \
      "$GITLAB_API_URL/projects/${GITLAB_PROJECT_ID}" > /dev/null
  fi
}

GITLAB_PROJECT_ID=$(python "$(dirname $0)/gitlab_project_create.py" create "$REPO_PATH")

init_repo

# If this is the first push we might not have a default branch
default_branch || true

git_mirror
# Protected branches are only created _after_ you push
python "$(dirname $0)/gitlab_project_create.py" update "$GITLAB_PROJECT_ID"
default_branch
