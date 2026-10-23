---
type: guide
status: active
day: 1
tags: [corpus, tracing, evaluation, golden-set]
related: ["[[Corpus]]", "[[Checklist]]", "[[2026-10-23]]"]
---

# Tracing a document and seeding the golden set

Use this when you want to answer two questions:

1. Where did this text come from?
2. What question can I trust it to answer later?

The example is
`content/handbook/business-technology/enterprise-applications/guides/zuora-collect.md`.
It is in the selected corpus: **24,786 bytes, 4,011 words**.

## The chain to verify

```text
pinned commit  ->  manifest entry  ->  Git blob  ->  raw Markdown  ->  seed question
```

Each arrow is checkable. If one does not match, the corpus is not what we think
it is.

## Step 1 - Find the file in the manifest

```bash
python3 - <<'PY'
import json

target = "content/handbook/business-technology/enterprise-applications/guides/zuora-collect.md"
manifest = json.load(open("data/manifest.json"))

for source in manifest["sources"]:
    for entry in source["files"]:
        if entry["path"] == target:
            print("source:", source["name"])
            print("commit:", source["commit"])
            print("entry:", entry)
PY
```

Expected:

```text
source: handbook
commit: 438cdf82c3002b933fba36ba0c3a969d49dc52fe
entry: {'path': '.../zuora-collect.md', 'bytes': 24786, 'words': 4011}
```

If the file is not in `files`, it is **not** in the selected 2,500, even if it
exists on disk. The checkout contains more files than the corpus.

## Step 2 - Confirm the snapshot commit

```bash
git -C data/corpus/handbook rev-parse HEAD
```

Expected:

```text
438cdf82c3002b933fba36ba0c3a969d49dc52fe
```

This is the same SHA as the manifest source. A branch name would move; this SHA
does not.

## Step 3 - Confirm the file is the Git version

```bash
git -C data/corpus/handbook ls-tree HEAD -- \
  content/handbook/business-technology/enterprise-applications/guides/zuora-collect.md

git -C data/corpus/handbook hash-object \
  content/handbook/business-technology/enterprise-applications/guides/zuora-collect.md
```

Expected:

```text
100644 blob 40c7ba6c57577442230929e8805a0c7370d3179e	content/handbook/.../zuora-collect.md
40c7ba6c57577442230929e8805a0c7370d3179e
```

`ls-tree` asks Git "what is stored at this commit for this path?" `hash-object`
asks "what is the content hash of the file on disk?" Same hash means the file on
disk is exactly the committed file.

## Step 4 - Read the raw Markdown

```bash
git -C data/corpus/handbook show HEAD:content/handbook/business-technology/enterprise-applications/guides/zuora-collect.md | head -40
```

You will see the real raw file, including:

- YAML frontmatter (`title`, `description`),
- HTML and Hugo shortcodes (for example the video `<figure>` blocks),
- Markdown links,
- headings that become chunk boundaries.

The file on disk is the same content; `git show` proves it came from the commit.

## Step 5 - See the document shape

```bash
grep -n '^#' data/corpus/handbook/content/handbook/business-technology/enterprise-applications/guides/zuora-collect.md
```

The main sections are:

- `Business Need`
- `Business Solution`
- `What is Zuora Collect`
- `How to access Zuora Collect`
- `Collections Window` (Dashboard, Accounts, Invoices, Tasks, Settings)
- `Notes` (Users, Export)
- `FAQ`
- `Zuora Collect Support`

This shape matters because the M1 chunker should keep a heading with its text,
and because citations should point at a heading, not just a file.

At ~200 words per child chunk, this 4,011-word document will produce roughly
`ceil(4011 / 200) = 21` child chunks. That is an estimate; the real chunker will
decide.

## A note on history

The checkout is shallow: `git fetch --depth 1` fetched one commit. So
`git log -- path` only sees the pinned snapshot. To inspect older changes, use
the GitLab history page or API:

```text
https://gitlab.com/gitlab-com/content-sites/handbook/-/commits/main/content/handbook/business-technology/enterprise-applications/guides/zuora-collect.md
```

The manifest's job is to pin the snapshot, not to replace Git history.

## From document to seed questions

A **golden set** is a small, manually verified list of questions with known
answers and known source passages. It is the ruler you use to measure retrieval
and generation. If the ruler is wrong, every score is wrong.

Do not start by asking an LLM to generate 100 questions. Start by reading one
document and writing questions whose answers you can point to.

### The method

1. Read one section at a time, not the whole file.
2. Write a question whose answer is fully inside that section.
3. Write the expected answer in one or two sentences, using the document's terms.
4. Record the source path and heading.
5. Label the type and the role that should be allowed to ask it.
6. Add at least one question the document **cannot** answer.
7. Repeat until you have 3-5 good questions from this document.

### Question types

| Type | What it tests | Example |
|---|---|---|
| `lookup` | one fact | What are the benefits of Zuora Collect? |
| `procedural` | ordered steps | How do I assign an agent to an account? |
| `conditional` | rules with AND/OR | When is an account considered "In Collections"? |
| `constraint` | limits and prohibitions | Can comments be edited? |
| `multi_hop` | two sections together | Where does auto escalation reassign a task? |
| `unanswerable` | abstention | What is the guaranteed support SLA? |
| `permission` | ACL behavior, added later | Can a contractor see Finance docs? |

### Rules for a good seed question

- One fact or one procedure per question.
- The answer must be verifiable in the source at the pinned commit.
- Use exact product terms: `Collections Window`, `Notes`, `Accounts`.
- Prefer "how" and "when" questions over trivia.
- Do not require general knowledge that is not in the corpus.
- Include negative questions: the bot must say "I don't know" instead of inventing.
- Include a citation target: path plus heading.
- Do not include the answer in the question.

### Worked examples from the Zuora page

| ID | Question | Expected answer | Source heading | Type |
|---|---|---|---|---|
| `zuora-001` | What are the main benefits of Zuora Collect? | It tracks unpaid invoices and delinquent accounts, manages automated processes and retry logic, and customizes payment runs. | What is Zuora Collect | lookup |
| `zuora-002` | How do you assign a collections agent to an account? | Accounts tab -> open the account -> click the agent or Unassigned -> select an agent -> Update; refresh to see changes. | How to assign Agents to an account? | procedural |
| `zuora-003` | When is an account considered "In Collections"? | The invoice balance must be positive and above the configured amount, and days overdue must be above the configured number. If either fails, it is not In Collections. | Accounts / Edit conditions | conditional |
| `zuora-004` | Can comments on an invoice be edited or deleted? | No. Comments cannot be edited or deleted by design. | How to edit a comment? | constraint |
| `zuora-005` | If auto escalation is enabled, where is a task reassigned on its due date? | To the escalation point of the agent; escalation points are configured in Notes. | Tasks + How to add an escalation point to a user | multi_hop |
| `zuora-006` | What is the guaranteed response SLA for the Zuora support channel? | The document does not state an SLA. It only says to ask in the channel with `@here`. | Zuora Collect Support | unanswerable |
| `zuora-007` | Who should Finance users contact first for Zuora Collect issues? | Finance Admins; if needed, message `#proj-zuora_collect_implementation` and add `@here`. | GitLab Internal Escalation Process | lookup |

These are seeded in `evals/seed_questions.jsonl`.

### JSONL shape

Each line is one JSON object:

```json
{"id":"zuora-001","question":"...","expected_answer":"...","source":{"path":"...","heading":"...","commit":"438cdf..."},"type":"lookup","answerable":true,"role":"billing","notes":"..."}
```

Why JSONL: one question per line is easy to diff, append, and load in Python.
It avoids a huge nested JSON array and keeps each case independent.

### Verify a seed before trusting it

```bash
python3 - <<'PY'
import json
for line in open("evals/seed_questions.jsonl"):
    case = json.loads(line)
    print(case["id"], case["type"], case["source"]["heading"])
PY
```

Then open the source heading in the raw Markdown and confirm the answer is
actually there. If it is not, either remove the case or mark
`"answerable": false` with a note explaining why.

### What this becomes later

This is a **seed**, not the final golden set. In M5 we will:

- expand to roughly 110 cases across handbook and product docs,
- balance lookup, procedural, multi-hop, unanswerable, and permission cases,
- add expected citations and forbidden sources,
- measure recall@10, faithfulness, citation validity, and abstention,
- use the same seed for ablation runs and the final demo.

## Interview angle

- "Every answer is traceable to a commit, a path, a heading, and a blob hash."
- "The golden set is manual before it is automated, because an automatically
  generated question can encode a hallucinated answer."
- "I include unanswerable questions to measure whether the system abstains
  instead of guessing."
- "The manifest is the boundary between data engineering and evaluation: if the
  snapshot changes, the golden set and the baseline must be revisited."
