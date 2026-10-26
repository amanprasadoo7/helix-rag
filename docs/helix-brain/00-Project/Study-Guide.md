---
type: guide
status: active
day: 2
tags: [docs, obsidian, markdown, tooling]
related: ["[[Start-Here]]", "[[Checklist]]", "[[2026-10-24]]", "[[2026-10-27]]"]
---

# Vault and study-guide pipeline

The Obsidian vault is the source of truth. `docs/theory.html` is a generated,
self-contained study guide for reading, searching, printing, and sharing. Edit
the Markdown, never the HTML. Start at [[Start-Here]].

## Vault layout

| Folder | Purpose |
|---|---|
| `00-Project` | roadmap, process, vault guide, entry point |
| `01-Architecture` | concepts and architecture decisions |
| `02-Evaluation` | evals, tracing, golden-set notes |
| `03-Journal` | dated build log |
| `_templates` | Obsidian note templates |

The generator skips `.obsidian` and `_templates`. Everything else becomes a
section in the guide.

## Folder policy

Keep notes flat inside the four top-level folders for now. Use links, tags, and
maps of content instead of deeper folders.

Add architecture subfolders only when `01-Architecture` reaches roughly 15–20
notes or has three stable subdomains. When that happens:

1. Introduce subfolders such as `Ingestion/`, `Platform/`, and `Retrieval/`.
2. Update the generator so the HTML sidebar still groups notes sensibly.
3. Move notes with `git mv`, update relative links, and run `make docs` and
   `make ci`.

Two current generator constraints drive that decision:

- Notes are grouped by the first folder only, so a subfolder does not create a
  new guide section.
- Wikilinks resolve by note stem or title, so duplicate note names across
  folders are ambiguous.

## Note contract

Every note starts with YAML frontmatter:

```yaml
---
type: concept
status: active
day: 2
tags: [retrieval, security]
related: ["[[Corpus]]", "[[Evaluation-101]]"]
---
```

- `type`: `concept`, `guide`, `process`, `architecture`, `journal`, `decision`
- `status`: `draft`, `active`, `implemented`, `verified`, `done`
- `tags`: used for chips and search
- `related`: rendered as links at the bottom of the note

The first `# Heading` becomes the page title. The generator removes it from the
body so the title is not duplicated. Use descriptive kebab-case filenames and
avoid duplicate stems across folders.

## Tag conventions

Tags are lowercase, singular, and hyphenated. Prefer a small vocabulary:

- Domain: `ingestion`, `retrieval`, `security`, `evaluation`, `platform`
- Note kind: `process`, `journal`, `interview`, `docs`, `navigation`
- Specific tools: `postgres`, `redis`, `qdrant`, `minio`, `docling`, `unstructured`

Avoid synonyms and one-off tags. Normalize an existing tag when you are already
editing that note; do not mass-rename tags just to make them match.

## Templates

Open the command palette in Obsidian and choose **Templates: Insert template**.
The templates folder is configured in `.obsidian/templates.json` as
`_templates`.

- `Concept.md` for explanations and interview notes
- `Journal.md` for the dated build log
- `Decision.md` for ADR-style decisions

Templates use Obsidian placeholders such as `{{title}}`, `{{date}}`, and
`{{time}}`.

## Generator

```bash
make docs
```

The command runs `scripts/build_theory.py`, which calls
`packages/helix/docs.py`:

1. Walk the vault and skip hidden, template, and nested-vault folders.
2. Parse frontmatter and the first H1.
3. Resolve `[[wikilinks]]` and `[[Note#Heading|labels]]` to page-scoped anchors.
4. Render Markdown with tables, fenced code, TOCs, and callouts.
5. Wrap everything in one HTML file with a sidebar, search, and print styles.

Output: `docs/theory.html`.

## What is supported

- YAML frontmatter (simple scalars and inline lists)
- Markdown headings, lists, links, tables, and fenced code
- Obsidian wikilinks, including heading anchors and aliases
- Obsidian callouts such as `> [!warning]`
- A generated table of contents per note
- Client-side search; press `/` to focus it
- Light and dark color schemes
- Mobile and print layouts

## What is not supported

This is deliberately a small generator, not a full Obsidian renderer:

- Dataview, Templater, or other plugin syntax
- Transclusions (`![[Note]]`) and embedded images
- Canvas files
- Backlink graphs and hover previews
- Incremental rendering

The guide is a build artifact, not a replacement for Obsidian. If a note needs a
feature the generator does not understand, either keep that feature in Obsidian
or add a focused extension with a test.

## Why not a static-site framework?

A framework such as MkDocs, Docusaurus, or Astro would add a Node toolchain,
configuration, themes, and a build pipeline. The goal here is a single offline
file with no runtime dependency. The current generator is a few hundred lines
and is tested as part of `make ci`.

The trade-off is that the Markdown subset is intentionally small. If the vault
starts using many Obsidian plugins, a real static-site generator becomes the
better choice.

## Add a note

1. Create the note in the right top-level folder.
2. Insert the matching template.
3. Fill in frontmatter, title, and links.
4. Run `make docs`.
5. Open `docs/theory.html` and check navigation, search, and anchors.
6. Commit the Markdown and the regenerated HTML together.

## Interview angle

- "The vault is the source of truth; the HTML is a reproducible build artifact."
- "I keep the renderer small and tested instead of adopting a framework for one
  page."
- "Wikilinks are resolved before Markdown rendering, and anchors are prefixed per
  page so headings cannot collide."
- "The generator fails closed on a missing vault and marks missing links instead
  of silently dropping them."
