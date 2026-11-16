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
```

These are the paths marked `[init]` in the specification, section 7. The
outputs of stages (`idea.md`, `method.md` and so on), `reproduce.sh` and
`.utux/checkpoints.sqlite` are created later by the stage or component that
owns them.

The first event is `project_created`, with the actor `system:utux`.

The project holds no absolute path and nothing else that depends on the
machine: two projects created with the same options have the same files.

### Before anything is created

`utux init` checks everything it can first, and creates nothing if a check
fails:

- The options make a valid `utux.yaml`. A budget of zero, for example, is
  refused with the field and the reason.
- The directory is empty or does not exist.
- git is installed.
- git has a user name and a user email. If one is missing, the command
  prints the two commands that set them:

  ```bash
  git config --global user.name "Your Name"
  git config --global user.email "you@example.org"
  ```

  There is no fallback identity. Only git's configuration is read; the
  settings of a repository that surrounds the new project do not count,
  because the project is its own repository.

If a later step fails, for example the commit, what was created is removed
again.

## `.gitignore`

```text
.DS_Store
__pycache__/
*.pyc
.utux/checkpoints.sqlite
.*.tmp
```

`.*.tmp` covers the temporary files of the atomic writer.

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
track.

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
