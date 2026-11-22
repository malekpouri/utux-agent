# The data policy

`data_policy` in `utux.yaml` says what may be sent to external services. It
is `external_allowed` or `local_only` and has no default
([`utux.yaml` reference](utux-yaml.md)). A service is external when its
`is_external` is true: content sent to it leaves the machine.

## Under `local_only`

| Call | Under `local_only` | Why |
| --- | --- | --- |
| A model call to an external provider | Refused before anything is sent | The request carries project text ([Logged model calls](model-calls.md)) |
| A literature **search** on an external source | Refused before any request | A query can carry project text, such as the words of a claim |
| A literature **fetch** or **resolve** by identifier | Allowed | It sends only the identifier of a cited work |

A refused call writes its event with status `refused` and `status_reason`
`data_policy_local_only`: a `model_call` event, or a `literature_call` event
with the operation `search` ([The event log](event-log.md)). The call raises
`ModelCallRefusedError` or `LiteratureCallRefusedError`, and the service is
never asked. A literature search is refused even when the shared cache holds
its answer, so that the rule does not depend on what was asked before.

**Fetch and resolve still tell the outside service which works the project
cites.** Under `local_only`, every DOI, arXiv id or PubMed id the project
looks up is sent to OpenAlex or arXiv, and those services can see, and may
log, which works were asked for from your address. The identifiers are not
the project's text, but together they can say a good deal about it. If that
is not acceptable, do not run the checks that resolve references on that
project.

## What is never sent

- No literature request carries an `Authorization` header or a key: utux
  uses no key for OpenAlex or arXiv.
- The only personal value ever sent to a literature service is the optional
  contact email of `literature.contact_email`, and only when it is set (rule 8
  of [the M2 plan](plan/M2.md)). It goes to OpenAlex as `mailto`, and nowhere
  else.
- Source text is never sent to a literature service.
