Gitlab Scripts
==============

This repositories contains a number of scripts and programs to
aid in using Gitlab CI in conjunction with Bitbucket.

These are the use-cases we are currently concerned with:

- [Mirroring Bitbucket repositories in Gitlab](#git-mirror)
- [Showing Build Statuses in Bitbucket](#build-status)
- [Gitlab Radiator](#gitlab-radiator)

See [troubleshooting](#troubleshooting) if you have any problems.


## <a name="git-mirror" href="#git-mirror">Mirroring Bitbucket repositories in Gitlab</a>

Gitlab natively supports building from external repositories. Unfortunely it's
not included in the free version.

- https://docs.gitlab.com/ee/ci/ci_cd_for_external_repos/
- https://about.gitlab.com/pricing/

For now it's fairly simple to listen to push events from Bitbucket and mirror
any changes in a local/readonly Gitlab copy.

NOTE: The scripts assumed a 1:1 with Bitbucket project to Gitlab group and
Bitbucket repository to Gitlab project. This is to simplify the integration and
not require a canonical mapping between the two.

To mirror repositories there are actually two parts to this process.
The first is a Bitbucket webhook that sends every push events to a separate
process.

https://bitbucket/projects/PRJ/settings/hooks

The server in question receives those hooks and appends a "PRJ/repo" pari
to a queue file.

```sh
export QUEUE=/tmp/bitbucket_queue
python ./bitbucket_git_mirror.py
```

Separately there is a daemon process that reads from this queue and does the
actual (slower) mirrors, creating the relative Gitlab group/project and then
mirrors the entire git repository.

```
export QUEUE=/tmp/bitbucket_queue
export QUEUE_INDEX=/tmp/bitbucket_queue.index
export GIT_SOURCE_URL=https://username:password@bitbucket/scm
export GIT_TARGET_URL=https://username:password@gitlab
export GITLAB_URL=https://gitlab
# https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html
export GITLAB_TOKEN_SECRET=/secrets/gitlab_token
export GIT_CACHE=/tmp/git_cache
export GITLAB_WEBHOOK_URL="http://gitlab_sync:9001"
./queue.sh ./git_mirror.sh
```


## <a name="build-status" href="#build-status">Showing Build Statuses in Bitbucket</a>

Slightly less critically, but still very important, is showing the green/red
build status icons. This ensures timely feedback on Pull Requests.

![bitbucket build statuses](https://i.stack.imgur.com/lIZN4.png)

Gitlab has support for a number of "integrations", such as Slack.
Unfortunately Bitbucket Server isn't natively supported.

https://docs.gitlab.com/ee/user/project/integrations/project_services.html

To enable support this repository contains a simple webhook to forward build
events from Gitlab to Bitbucket.

https://docs.gitlab.com/ee/security/webhooks.html

```
export GITLAB_URL=https://gitlab
export BITBUCKET_HOST="bitbucket"
export BITBUCKET_PORT=443
export BITBUCKET_TOKEN_SECRET=/secrets/bitbucket_token
python ./bitbucket_build_status.py
```


## <a name="gitlab-radiator" href="#gitlab-radiator">Gitlab Radiator</a>

Gitlab doesn't provide a build raditor/dashboard out-of-the-box.
So we have rolled out own. It's easy to run locally:

This is intended as replacement for Radiator V1 which has to scan _every_
project for each type of pipeline, which can take some time and will only
slow down over time with more queries we might want to run (ie tags).

This version uses a "cache" json file built from a stream of pipeline/build
events from gitlab.

```sh
export GITLAB_PIPELINE_CACHE=pipeline_events.json
export GITLAB_RADIATOR_INVESTIGATIONS=investigations.txt # optional
export GITLAB_RADIATOR_PORT=9004 # default

python ./gitlab_radiator_cache.py
```

And then open http://localhost:9004 in your browser.


## <a name="troubleshooting" href="#troubleshooting">Troubleshooting<a>


### `git fetch_pack: expected ACK/NAK`

```
fatal: git fetch_pack: expected ACK/NAK, got 'A ref was requested that is no longer valid. The ref may have been updated while the git-upload-pack request was received. Please try again.'
```

The cause of this still unknown. The automatic service restart should recover just fine.


### `deny updating a hidden ref`

```
! [remote rejected] me/release/1.0.2 -> me/release/1.0.2 (deny updating a hidden ref)
error: failed to push some refs to 'https://gitlab/PRJ/repo.git'
queue_mirror.service: main process exited, code=exited, status=1/FAILURE
```

I have noticed some repositories very occassionally contain stray "remote" refs.
I'm assuming someone has run the wrong `git push` command but I can't be sure,
I would have to catch them in the act...

Firstly check that the commit is contained in a "real" branch:

```
git branch -r --contains \
  $(git ls-remote origin refs/remotes/me/release/1.0.2)
# This should return something under `refs/heads`, otherwise create one
```

And then delete it.

```
git push origin :refs/remotes/me/release/1.0.2
```

The mirror can then be restart.

### `The default branch of a project cannot be deleted.`

```
error: failed to push some refs to 'https://gitlab/ABC/def.git'
remote: GitLab: The default branch of a project cannot be deleted.
To https://gitlab/ABC/def.git
! [remote rejected] develop (pre-receive hook declined)
error: failed to push some refs to 'https://gitlab/ABC/def.git'
```

This mostly occurs when the default branch in Bitbucket is changed.
The sync should now (in theory) handle this but otherwise the default
branch in Gitlab can be changed manually and the mirror restarted.

### `You are not allowed to force push code to a protected branch on this project`

```
Reinitialized existing Git repository in /var/opt/gitlab_cache/PROJ/util.xyz/
fatal: remote source already exists.
From https://bitbucket/scm/PROJ/util.xyz
+ 15bd51c...b4cd4c8 master     -> master  (forced update)
remote: GitLab: You are not allowed to force push code to a protected branch on this project.
To https://gitlab/PROJ/util.xyz.git
! [remote rejected] master -> master (pre-receive hook declined)
error: failed to push some refs to 'https://gitlab/PROJ/util.xyz.git'
```

By default when you create a new Gitlab repository and push it "protects" the default
branch.

https://docs.gitlab.com/ee/user/project/protected_branches.html

This error means that the protected branch hasn't been removed correctly as part of
the git mirroring. When removed (just once) the push should work as expected.

### `The requested repository does not exist, or you do not have permission to access it.`

This is most likely caused by the `mattermost` user not having read access to Bitbucket.
It should be added as `read` to the Bitbucket group.

```
Reinitialized existing Git repository in /var/opt/gitlab_cache/DS/test.repo/
fatal: remote error: Repository not found
The requested repository does not exist, or you do not have permission to access it.
```
