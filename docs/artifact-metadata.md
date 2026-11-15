# Artifact metadata and content hashes

Every stage output has a metadata sidecar, so the system always knows what an
output was built from (specification, section 7). The schema is
`utux.schemas.artifact_metadata.ArtifactMetadata`. It follows the
[schema conventions](schema-conventions.md).

## Sidecar

A sidecar is a JSON file. Every field is required.

| Field | Form | Meaning |
| --- | --- | --- |
| `schema_version` | integer | Version of this schema. Currently `1` |
| `artifact_id` | name, `-v`, and at least three digits, for example `method-v003` | The artifact version the sidecar describes |
| `stage` | `ideation`, `literature`, `methodology`, `implementation`, `experiment` or `writing` | The stage that owns the artifact |
| `created_by` | `agent:<role>` or `human:<id>` | Who produced the artifact |
| `created_at` | UTC timestamp, ISO 8601, ending in `Z` | When it was produced |
| `input_artifacts` | list of artifact ids; may be empty | The exact versions it was built from |
| `content_hash` | `sha256:` and 64 lower-case hexadecimal digits | Hash of the content |
| `state` | `valid` or `stale` | Whether the artifact may still be used |

Timestamps are kept as text, so a sidecar that is read and written again
keeps the exact timestamp it had.

## Content hashes

`utux.workspace.hashing` provides `hash_bytes`, `hash_file` and
`hash_directory`. Each returns `sha256:` followed by 64 hexadecimal digits.

- **File.** The SHA-256 of the file's bytes. Nothing is translated, so the
  result is the same on every platform.
- **Directory.** The SHA-256 of one entry per regular file below the
  directory. An entry is the path relative to the directory, with `/` as
  separator and encoded as UTF-8, then a zero byte, then the 64 hexadecimal
  digits of the file's SHA-256, then a newline. Entries are sorted by the
  bytes of the path, so the order in which the file system lists files has no
  effect.

Directories that contain no file do not change a directory hash. Symbolic
links and special files are refused with a `HashingError`, so a hash never
depends on content outside the directory.

A directory hash can be checked without utux. For a directory with `a.txt`
and `sub/b.txt`:

```bash
printf 'a.txt\0%s\nsub/b.txt\0%s\n' \
  "$(sha256sum < a.txt | cut -d' ' -f1)" \
  "$(sha256sum < sub/b.txt | cut -d' ' -f1)" | sha256sum
```
