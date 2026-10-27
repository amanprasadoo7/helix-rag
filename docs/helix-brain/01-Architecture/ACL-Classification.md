---
type: architecture
status: active
day: 4
tags: [acl, security, rbac, ingestion, interview]
related: ["[[Ingestion-M1]]", "[[Checklist]]", "[[Project-Map]]", "[[Storage-Layers]]", "[[Evaluation-101]]", "[[Roadmap-Review]]", "[[2026-10-27]]"]
---

# ACL classification: who may see each document

**Short answer:** Before a document is chunked, Helix assigns it a
`classification` and a list of `allowed_roles`. The rule is based on the
document's source and path, not on its content or tags. At query time the same
metadata becomes a Qdrant payload filter, so forbidden chunks never enter the
candidate set.

The classifier is implemented in `packages/helix/acl.py`. This note records the
1.2 design conversation and the behavior that shipped.

## The simple picture

Think of a company library:

- The public product manuals are on the open shelf.
- The engineering runbooks need an engineering badge.
- HR, finance, legal, and security each have a locked room.
- An unknown box does not get a label that says "public". It stays locked until
  someone classifies it.

The classifier is the librarian writing the label. It does not decide whether a
particular person is trustworthy; it only says which badges open which room.
Authentication later proves the badge.

## Classification and roles are different

| Idea | Question it answers | Example |
|---|---|---|
| Classification | How sensitive is this document? | `confidential:hr` |
| Allowed roles | Which badges may open it? | `hr`, `legal`, `security`, `admin` |

A classification is a human-readable label. The role list is the machine-checked
permission. Keeping both makes the audit trail readable and the authorization
check simple.

## Role model

Roles are **additive sets**, not a hierarchy with one winner:

- `authenticated` is a sentinel for any logged-in user. It is how public docs are
  expressed without special-casing "anonymous".
- `employee` is the baseline for internal staff. Every employee identity receives
  it; functional roles are added on top.
- `engineer`, `support`, `hr`, `finance`, `legal`, `security` are functional
  roles.
- `contractor` is deliberately not an employee by default. It can be granted
  specific project access later.
- `admin` is a break-glass role. It appears in every allow list so local
  administration is possible, but every admin read should still be audited.

`billing` is an alias for `finance`, not a separate ACL role. Identity resolution
normalizes it before the matcher runs. The seed data can keep `billing` until 1.7
normalizes the file, but the authorization decision always uses `finance`.

A user can have several roles. For example, a finance employee might be
`["authenticated", "employee", "finance"]`. The matcher allows the document if
the user's roles intersect the document's `allowed_roles`.

There is no "highest role wins" rule. If an engineer also has `security`, they
get the union of both sets. That is simpler to reason about and avoids a role
hierarchy that nobody can audit.

## Path rules

The source is part of the rule. A path that looks the same in two different
repositories should not accidentally inherit the other repository's policy.

| Source and path | Classification | Allowed roles |
|---|---|---|
| `gitlab-docs:doc/**` | `public:docs` | `authenticated` |
| `handbook:content/handbook/security/**` | `restricted:security` | `security`, `admin` |
| `handbook:.../people-group/**`, `people-policies/**`, `hiring/**`, `total-rewards/**`, `labor-and-employment-notices/**` | `confidential:hr` | `hr`, `legal`, `security`, `admin` |
| `handbook:.../finance/**`, `acquisitions/**` | `confidential:finance` | `finance`, `legal`, `security`, `admin` |
| `handbook:.../legal/**`, `board-meetings/**` | `confidential:legal` | `legal`, `security`, `admin` |
| `handbook:.../engineering/**`, `support/**`, `product/**`, `product-development/**`, `solutions-architects/**`, `it/**`, `tools-and-tips/**` | `internal:eng` | `engineer`, `support`, `security`, `admin` |
| `handbook:.../marketing/**`, `sales/**`, `customer-experience/**`, `eta/**`, `company/**`, `leadership/**`, `communication/**`, `upstream-studios/**`, `enterprise-data/**`, `resellers/**`, `about/**`, `entity/**`, `values/**`, `business-technology/**`, `_index.md` | `internal:company` | `employee`, `admin` |
| anything unmatched | `restricted:unknown` | none, deny |

The five paths that the first draft missed are now explicit:
`content/handbook/_index.md`, `acquisitions/`, `board-meetings/_index.md`,
`labor-and-employment-notices/_index.md`, and `values/_index.md`.

`project:atlas` is **not** a 1.2 rule. It stays a future example of a tag-based
override until a real project collection needs it.

## Matching and precedence

The matcher is deliberately boring:

1. Filter rules by `source`.
2. Compare the document path against each rule's prefix using a boundary-safe
   check. `content/handbook/legal` matches `content/handbook/legal/x.md` but not
   `content/handbook/legalish/x.md`.
3. The longest matching prefix wins. This lets a future narrow rule override a
   broad one without reordering the table.
4. Ties use rule order, which is fixed in code and recorded as `rule_id`.
5. No match means `restricted:unknown` with `allowed_roles: []`. Never default to
   public.

Boundary safety matters. A naive `startswith("content/handbook/legal")` would
also match a path such as `content/handbook/legal-ops/`, which may have a
different policy.

## Output contract

The classifier writes a sidecar index, not a mutation of the parsed JSON:

```text
data/acl/index.json
data/acl/summary.json
```

Each index entry looks like this:

```json
{
  "source": "handbook",
  "path": "content/handbook/engineering/architecture/_index.md",
  "classification": "internal:eng",
  "allowed_roles": ["engineer", "support", "security", "admin"],
  "rule_id": "acl-path-engineering-v1",
  "matched_prefix": "content/handbook/engineering",
  "reason": "source=handbook path starts with content/handbook/engineering"
}
```

`policy_version` is stored once at the top of the file, for example `acl-v1`.
`summary.json` records counts by classification and by rule, the unknown count,
and the manifest hash the run used. It does **not** contain a wall-clock
timestamp, because two runs over the same manifest should produce identical
files.

Two fields are more useful than they look:

- `rule_id` answers "which policy made this decision?"
- `matched_prefix` answers "which part of the path triggered it?"

Without those, a permission bug is hard to debug after the fact.

The sidecar design also means we can reclassify the corpus without re-parsing it.
Parsed JSON stays a pure parsing artifact.

## Why not classify another way?

### Why not ask an LLM?

The rule is cheap, deterministic, testable, and has no model cost. An LLM might
be useful later for suggesting a label on a genuinely ambiguous document, but it
must not be the enforcement path. A probabilistic classifier is not an ACL.

### Why not tag frontmatter?

Most selected documents have no owner or sensitivity tag. Tags are free-form,
easy to forget, and easy to spoof. They are a good future override for a specific
project collection, not the baseline. This is why `project:atlas` is deferred.

### Why not copy the source ACL?

That would be the best answer if the source repository exposed the same
permissions. It does not expose a usable per-document ACL for this synthetic
corpus. The path table is a stand-in that makes the security behavior real and
testable.

### Why not classify manually?

2,500 documents would drift immediately, and a manual spreadsheet is not a
policy. The path table is the reviewed policy; the classifier applies it.

## Corpus coverage

With `business-technology` under `internal:company`, the final table classifies
all 2,500 selected files:

| Classification | Documents |
|---|---:|
| `public:docs` | 1,500 |
| `internal:eng` | 439 |
| `internal:company` | 383 |
| `restricted:security` | 103 |
| `confidential:hr` | 28 |
| `confidential:legal` | 28 |
| `confidential:finance` | 19 |
| `restricted:unknown` | 0 |
| **Total** | **2,500** |

No unknown paths remain. The unknown branch still exists and is tested because a
future corpus refresh will add paths.

## Doubts and answers

### Should MinIO come after 1.5?

Yes. The checkpoint is `1.5b`, after Qdrant and Postgres are working. MinIO is
useful but not on the critical path to a searchable index. Moving it after 1.5
keeps 1.5 focused on retrieval storage and gives 1.5b a clear job: archive the
raw corpus and manifest with checksums.

See [[Storage-Layers]] for the bucket layout.

### Why prefix the classification with `public`, `internal`, `confidential`, or `restricted`?

The prefix makes the sensitivity obvious at a glance and gives the UI a stable
color/label. It also avoids a flat vocabulary where `hr` and `internal:hr` look
like the same kind of thing.

### Why store three audit fields instead of one `reason` string?

`rule_id` identifies the policy, `matched_prefix` identifies the path that
matched, and `reason` explains the decision in words. If a document is
misclassified, you can tell whether the cause was rule order, a bad prefix, or a
missing rule. A single prose string loses that structure.

### Why can a user have multiple roles?

People wear several hats. A finance employee may also be an admin; a security
engineer may also be an engineer. Additive sets model that without inventing a
role hierarchy. The authorization check is a set intersection, which is easy to
test.

### What about duplicate documents?

The parser writes one deterministic path per source document, so a duplicate
input path overwrites the same parsed file. There is no content-level dedup in
1.1 or 1.2. If the same bytes appear at two different paths, they are two
documents until 1.6 adds content hashes and tombstones. The ACL index rejects
duplicate `(source, path)` keys rather than merging them silently.

### Why not store the ACL inside the parsed document?

Separation of concerns. Parsing and classification have different inputs and
different reasons to change. A sidecar lets us reclassify without re-parsing, and
it keeps the parser's output stable for tests and future formats.

## Confirmed correction

The seed questions use roles `billing` and `finance` on the Zuora guide under
`content/handbook/business-technology/`. The first taxonomy draft put that path
under `internal:eng`, whose roles did not include either role. The user resolved
the conflict on 2026-10-27:

1. `billing` is an alias for `finance`. Identity resolution normalizes it before
   matching; the canonical ACL role stays `finance`.
2. `business-technology/**` moves from `internal:eng` to `internal:company`,
   because its enterprise-application guides are used by finance, HR, and
   support, not only engineers. Employees still reach it through the `employee`
   baseline.

The resulting counts are `internal:eng` 439 and `internal:company` 383. The seed
file can keep `billing` until 1.7 normalizes it, but the classifier and matcher
use `finance`.

## Implementation in 1.2

Built as designed:

- `packages/helix/acl.py`: `Role`, `Classification`, `Rule`, `AclPolicy`, and
  `AclDecision`, plus `normalize_role` and `DEFAULT_POLICY`.
- `scripts/classify_corpus.py`: reads `data/manifest.json`, classifies each
  `(source, path)` pair, rejects duplicate keys, and writes the sidecar files.
- `make classify` for the full manifest and `make classify-sample` for five
  evenly spaced entries with verbose output.
- Tests for source distinction, prefix boundaries, longest-prefix precedence,
  tie order, the role matrix, `billing` -> `finance` normalization, unknown
  deny, duplicate keys, deterministic output, and full-corpus coverage when the
  manifest is present.
- Manual check: all 2,500 files classified, summary inspected, zero unknown
  paths, and the classification counts match the table above.
- Docs: [[Ingestion-M1]], [[Checklist]], [[Storage-Layers]], the journal, and
  this note.

The run is deterministic. The index and summary contain no wall-clock
timestamp, record the manifest SHA-256, and sort entries by `(source, path)`.
Two consecutive full runs produced identical SHA-256 hashes for both files.

`AclDecision.allows` canonicalizes the user's roles and intersects them with the
document's allow list. That is the function the retrieval layer will call before
applying the Qdrant payload filter at 2.2.
