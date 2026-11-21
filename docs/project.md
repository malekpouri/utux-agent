# Creating a project

A project is a directory that holds everything about one piece of research:
its configuration, its files, its event log and its git history. Nothing
about a project is kept outside its directory.

## `utux init`

```bash
uv run utux init my-project --budget-usd 20 --data-policy local_only
```

| Argument or option | Meaning |
| --- | --- |
| `DIRECTORY` | Where to create the project. It must be empty or not exist yet. Missing parent directories are created |
| `--budget-usd` | Total budget of the project in US dollars. Required; there is no default |
| `--data-policy` | `external_allowed` or `local_only`: what may be sent to external services. Required; there is no default |
| `--profile` | The profile. Optional; without it, the default of the `utux.yaml` schema (`default`) |
| `--domain-pack` | The domain pack. Optional; without it, the default of the `utux.yaml` schema (`generic`) |

The command prints the project directory and exits with 0. On failure it
prints one message, exits with 1 and leaves nothing behind.

### What it creates

```text
my-project/
  .git/                 the project's own git repository, with one commit
  .gitignore
  utux.yaml             the configuration, with every default written out
  events.jsonl          the event log, with the project_created event
  claims.jsonl          the claim ledger, empty
  results.jsonl         the result records, empty
  inputs/               each of these directories holds a .gitkeep file,
  sources/              so that the first commit contains the whole tree
  code/
  runs/
  figures/
  paper/
  approvals/
  .utux/meta/
  .utux/settings-snapshot.yaml   a copy of utux.yaml, the first settings snapshot
```

These are the paths marked `[init]` in the specification, section 7. The
outputs of stages (`idea.md`, `method.md` and so on), `reproduce.sh`,
`.utux/checkpoints.sqlite` and the project lock `.utux/lock` are created
later by the stage or component that owns them.

The first event is `project_created`, with the actor `system:utux` and the
version of utux that created the project in `data.utux_version`.

The project holds no absolute path and nothing else that depends on the
machine: two projects created with the same options have the same files.

### Requirements

- Linux. utux is tested on Linux. macOS should work but is not tested in CI.
  Windows is not supported: the project lock checks whether its holder is
  still running with a POSIX process call.
- git 2.28 or newer. `utux init` creates the repository with
  `git init --initial-branch=main`, which older versions do not have. With an
  older git the command fails at that step with git's message and leaves
  nothing behind.

### Before anything is created

`utux init` checks everything it can first, and creates nothing if a check
fails:

- The options make a valid `utux.yaml`. A budget of zero, for example, is
  refused with the field and the reason.
- The directory is empty or does not exist. If it is not empty, the message
  says: "if it is left over from an interrupted utux init, remove it and run
  the command again".
- git is installed.
- git has an author and a committer identity: a name and an email for each.
  git takes them from its configuration (`user.name`, `user.email`) or from
  the environment (`GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`,
  `GIT_COMMITTER_NAME`, `GIT_COMMITTER_EMAIL`), as it does for any commit.
  If git has none, the command prints the two commands that set them:

  ```bash
  git config --global user.name "Your Name"
  git config --global user.email "you@example.org"
  ```

  There is no fallback identity, and an identity that git would only guess
  from the account and host name is refused: the check and the commit run
  git with `user.useConfigOnly`. The settings of a repository that surrounds
  the new project do not count, because the project is its own repository.

If a later step fails, for example the commit, what was created is removed
again, and the command exits with 1 and git's reason.

### The first commit and signing

The first commit follows your git configuration. If you have configured
commit signing (`commit.gpgsign`), the commit is signed, and your signing
program may ask for a passphrase. If signing fails, `utux init` fails with
git's reason and leaves nothing behind. utux does not switch signing off.

## `.gitignore`

```text
.DS_Store
__pycache__/
*.pyc
.utux/checkpoints.sqlite*
.utux/lock
.utux/staging/
.*.tmp
inputs/**
!inputs/**/
!inputs/**/*.md
!inputs/.gitkeep
runs/*/outputs/
```

`.utux/checkpoints.sqlite*` covers the checkpoint database and the `-wal`,
`-shm` and `-journal` files SQLite keeps beside it while it is open and
after a crash. `.utux/lock` is the project lock (below), and `.utux/staging/` the staging area of a node that has not finished ([How a run works](run.md)). `.*.tmp` covers the
temporary files of the atomic writer. The last five
lines are those of ADR-0009: every file under `inputs/` except `*.md` files,
and everything under `runs/<run_id>/outputs/`, stays out of git. Their
content hashes in sidecars and run manifests are the record. The directories
under `inputs/` are taken back so that git still finds `*.md` files in them,
and `inputs/.gitkeep` so that the directory is in the first commit.

The lines are the constant `GITIGNORE_LINES` in `utux.workspace.layout`.
`ignored_by_git(path)` applies the same lines, and `utux validate` uses it
to tell a missing file kept out of git from a missing tracked file
([Validating a project](validate.md)). A project created before these lines
existed needs them added by hand.

## Commands that write to a project

Every command that writes to a project holds the project lock while it
runs, and records changes of `utux.yaml` before it acts. These are
`utux run`, `utux approve`, `utux model ping` and `utux log repair`.
Read-only commands (`utux validate`, `utux cost`, `utux status`,
`utux schema export`) do neither. The code is in `utux.workspace.writer`.

### The project lock

The lock is the file `.utux/lock`. It is created only if it does not exist,
holds the process id, host, command and start time of its holder, and is
removed when the command ends, also when it fails. While it exists, a second
writing command is refused and the message names the holder:

```text
error: the project is locked by process 4242 on host-a (model ping, since 2026-11-18T09:00:00Z); wait for it to finish and run the command again
```

The lock file is one JSON object:

```json
{"pid": 4242, "host": "host-a", "command": "model ping", "started_at": "2026-11-18T09:00:00Z"}
```

- **A lock left by a process that is no longer running** (after a crash or
  a kill) is reported, not taken over. Check the project with
  `utux validate`, then remove the lock with `utux unlock`, which removes
  only a lock whose holder on this host is no longer running and records a
  `lock_removed` event ([Running a project from the command line](cli-runs.md)),
  and run the command again.
- **A lock of another host**, on a shared file system, cannot be checked;
  it is treated as held.
- **A lock that cannot be read** is reported with the same advice.

Settings are compared on their validated values, not on the text of the
file: a comment, the order of keys or spacing is no change.

The lock is not in git.

### Setting changes

`.utux/settings-snapshot.yaml` is a copy of `utux.yaml` as last recorded.
`utux init` writes the first one. Before a writing command acts, it reads
both files and, for every setting whose value differs, writes one
`setting_changed` event with the dotted key and the old and new value, for
example `budget.total_usd` from `20.0` to `30.0`. It then copies `utux.yaml`
over the snapshot. This is how a hand edit of the budget, of verification or
of any other setting enters the log; there is no separate command to change
a setting (ADR-0011).

- Defaults are filled in before comparing, so writing a default out or
  leaving it away is no change. `schema_version` is not a setting.
- A key that appears has `old_value` null, and one that disappears has
  `new_value` null.
- If `utux.yaml` is invalid, nothing is recorded, the snapshot is kept, and
  the command fails.
- If there is no snapshot, the current file becomes the snapshot and nothing
  is recorded. A project created before this rule starts recording from its
  first writing command.
- `utux log repair` records the changes after the repair, since nothing can
  be appended to a log whose last line is incomplete.

The snapshot is tracked by git, so that a clone records changes from the
same starting point.

## The exclude list for directory hashes

A directory hash of project content leaves out four kinds of entry, at every
depth:

| Entry | Why |
| --- | --- |
| `.gitkeep` | Only keeps an empty directory in git |
| `.DS_Store` | Written by a file manager |
| `__pycache__/` | Python's cache |
| `*.pyc` | Compiled Python |

The list is the constant `HASH_EXCLUDE_ENTRIES` in `utux.workspace.layout`,
and `hash_project_directory(directory)` applies it. Nothing else is left
out. The list is fixed: changing it changes directory hashes, which needs a
new `schema_version` of the artifact metadata sidecar.

The `.gitignore` holds the same entries except `.gitkeep`, which git must
track, and adds the lines above.

## The atomic writer

`utux.workspace.atomic` provides `atomic_write_text` and
`atomic_write_bytes`. Every contract file that is replaced as a whole is
written through them: the content goes to a temporary file in the same
directory, is forced to disk, and is renamed over the target.

- A reader sees either the complete old file or the complete new one.
- If the write fails or is interrupted, the target is unchanged and the
  temporary file is removed. A failure raises `AtomicWriteError`.
- The target itself is never opened for writing.

`events.jsonl` is the exception: it is only ever appended to, by the event
log.
