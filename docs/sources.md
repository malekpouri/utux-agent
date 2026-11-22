# Stored sources and the cache

Task M2-03. A project keeps each literature source it checks claims against
in `sources/`; a machine-wide cache keeps API responses and source texts so
that projects share them.

## Files in `sources/`

A source has a record, `sources/<stem>.json` ([Source record](contracts.md#source-record)),
and, when its text is stored, the text beside it, `sources/<stem>.txt`. The
stem is:

1. the source id lowercased, with every character other than `a`-`z` and
   `0`-`9` replaced by `-`, cut to 60 characters;
2. `-` and the first eight hexadecimal digits of the SHA-256 hash of the
   source id.

`doi:10.0000/example` is stored as `doi-10-0000-example-c13671bc.json` and
`.txt`. The hash keeps two ids apart that give the same slug, such as ones
that differ only in letter case. The record keeps the real source id (rule
17 of [the M2 plan](plan/M2.md)).

**Passages are computed, not stored**: they come from the stored text by
the shared splitter ([Passages](passages.md)).

`utux.sources.store` writes and reads sources:

- `write_source(project, record, text)` writes the text first and the record
  last, so a record never names a text that is not there. It refuses a text
  whose hash is not the record's `text_hash`, a text for a source whose
  licence does not permit storing it, and a record that names a stored text
  when none is given.
- `read_source(project, source_id)` reads both and checks the text against
  its hash; a text changed on disk is refused.
- `source_text(project, source_id)` gives the text to check claims against,
  or the reason `no_text` (RFC-001, S2).
- `stored_passages(project, source_id)` gives the passages of the stored
  text.

## Sources that may not be stored

A source whose licence does not permit storing its text has
`storage_permitted` false. It is recorded with its metadata only: no text,
no hash, no extraction fields (`text_not_permitted` otherwise). Its claims
are checked against nothing, `no_text`.

## What `utux validate` checks

| Problem | File | Code |
| --- | --- | --- |
| A record whose file name is not the stem of its source id | the record | `name_mismatch` |
| A record that names a stored text, with no `<stem>.txt` beside it | the record | `missing_text` |
| A stored text whose hash is not the record's `text_hash` | the text | `text_hash_mismatch` |
| A text beside a record that stores none | the text | `text_not_stored` |
| A `.txt` file with no record of its stem | the text | `text_without_record` |

A duplicate source id is reported as `duplicate_id`, on the later file, and
the file checks above apply to the first.

## The cache

`utux.sources.cache.ContentCache` keeps source texts and API responses by
their content hash, shared across projects (specification, section 9). It
lives in `UTUX_CACHE_DIR` if that is set, and otherwise in the platform's
user cache directory:

| Platform | Directory |
| --- | --- |
| Linux | `$XDG_CACHE_HOME/utux`, or `~/.cache/utux` |
| macOS | `~/Library/Caches/utux` |

- A response is found by its request, which maps to the response's hash.
- Every entry is checked against its hash when read. An entry that does not
  match is removed and counts as a miss.
- **The cache never holds keys.** A request or a body that contains the
  value of an environment variable whose name ends in `KEY`, `TOKEN`,
  `SECRET` or `PASSWORD` (8 characters or more) is refused, and the error
  names the variable, never its value. Requests are built from URLs and
  parameters without credentials.

```bash
uv run utux cache clear
```

removes every entry. It takes a lock on the cache, `.lock` in the cache
directory, not on a project, and refuses while another process holds it.
