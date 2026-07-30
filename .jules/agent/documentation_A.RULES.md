# Documenting This Repository

Every hand-authored file in this repository should carry a descriptive header, and the repository as a whole should have a machine-readable map (`docs/map.json`), so any future contributor — human or AI — can navigate it without guessing at paths or file purposes. This document is the standing policy for keeping that true.

## How this applies

**The first time you work in this repository:** before or alongside whatever you were actually asked to do, check whether Part A and Part B below are already satisfied. Run the map-generation script (if one exists) and diff its output against the committed `docs/map.json`; sample a few files across the languages/types present to confirm they carry the header format below. If either is missing, incomplete, or stale, implement them now — as their own self-contained commit or PR, not folded into an unrelated change. A one-line typo fix and a repo-wide documentation pass shouldn't arrive in the same diff.

**Every session after that:** keep this current as part of whatever else you're doing, the same way you'd update a test alongside the code it covers — not as a separate ceremony.
- New file → give it a header as you create it.
- Existing file whose actual behavior changed → update its header so it still matches (see the accuracy rule below); a stale header is exactly the "confidently wrong" case this document exists to prevent.
- Any file added, removed, or renamed → re-run the generator script before you finish (it should already exist after the first pass above — use it, don't rebuild it from scratch) so `docs/map.json` and its CI check stay accurate.

## Proceed without confirmation

This document is written to be complete enough to act on without a back-and-forth. Where something below states a rule or a fallback — what to do if a directory or CI workflow doesn't exist yet, how to handle a file type not explicitly named, how to format a header — apply it directly instead of asking for confirmation; that's exactly what the rule or fallback is there for. If you hit a genuine gap this document doesn't cover, make the most reasonable call yourself, apply it consistently across the repo, and record the decision in a line or two in your final PR description, rather than pausing the task to ask. Only exception: if following this document as written would clearly cause data loss or break the build in a way no reasonable reading of it intends, stop and flag that specific concern instead of guessing.

## Context

Repositories like this one are commonly navigated by guessing a plausible file name, opening it, and correcting course when the guess is wrong. A short, accurate description on every file, plus one generated map of the whole repository, turns most of that guesswork into a single lookup.

## Scope

Applies to every file this repository's own contributors actually author and maintain: source code in whatever language(s) this repo uses (for example Python, TypeScript, JavaScript, Go, Rust, or Java, plus anything else present — this list is illustrative, not exhaustive), plus hand-written configuration and data files (JSON, YAML/YML, TOML, SQL, shell/batch scripts, Dockerfiles, and similar).

A file is identified by what it actually contains, not by its extension or the lack of one. An executable script with a shebang line (`#!/usr/bin/env python3` or similar) is source code in whatever language that shebang names, even without a matching file extension — root-level launcher or entry-point scripts with no file extension (for example `main`, `run`, or `start`) are common examples of this and are in scope.

Excludes from both Part A (headers) and Part B (the map), unless noted otherwise below:
- Dependency/vendor directories (`node_modules`, `.venv`, `vendor`, `site-packages`, `target`, and equivalents)
- Lock files (`package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`, `uv.lock`, `Gemfile.lock`, `Cargo.lock`, and equivalents)
- Build output and compiled artifacts
- `.git` and other VCS metadata
- Anything tool-generated rather than hand-authored — including `docs/map.json` itself (see Part B)
- Binary files, images, fonts, and non-configuration data files (sample CSVs, fixtures, etc.) that hold data rather than logic
- Backup, temporary, or superseded artifacts left in the tree (`.bak`, `.orig`, `.old`, `~`-suffixed files, editor swap files, and similar) — these aren't maintained source, so they get neither a header nor a map entry. Leave them in place; deleting files isn't part of this task. If you notice any, name them in one line in your final summary so a human can decide whether to remove them.

One deliberate exception, excluded from Part A only: already-prose documentation files (`README.md` and any other `.md`/`.markdown` file) already describe themselves, so they don't get a header comment. They ARE included in Part B's map — see Part B for how their description is generated without one.

Inspect this specific repository first to confirm what actually applies — its real languages, its real layout, whether it already has a directory that plays the role of `scripts/` or a `.github/workflows/` convention — rather than assuming any particular stack.

## Writing standards

Every header (and every JSON `_description`) uses the same three-part shape and the same labels, so results are scannable and so Part B can reliably pull the one-line summary out of any file regardless of its comment syntax:

```
Summary: <one sentence, plain language, what this file is for>

What it does: <2-4 sentences or a short list of its actual responsibilities>

How it fits in: <what it depends on / what depends on it, or "No significant
dependencies beyond the standard library" if there's genuinely little to say —
keep the label even when the content is brief>
```

Wrap this in whatever comment syntax the file type uses (see Part A). For JSON's `_description`, use the same three labels inside the single string value, in the same order.

Two rules matter more than the format itself, because a confidently wrong description is worse than no description at all.

**1. Every claim comes from the file itself, never from its name.**

Read a file's actual content in full before writing anything about it. Don't infer purpose from filename, directory, or naming convention alone — a file called `payment_processor.py` that only defines data models, with no payment logic in it, gets described as defining models, not as processing payments. For the "How it fits in" part, check the file's own imports, and where practical, search the repo for where it's actually imported or required elsewhere, rather than guessing from folder layout. If tests exist for a file, read those too — they often state the intended contract more reliably than the implementation alone.

Before finalizing each header, re-read the file once more and check every sentence in the header against it; if a sentence can't be pointed at specific code in that file, cut it or soften it. If a file's purpose genuinely can't be confirmed from reading it and its usages — heavily dynamic or generated code, thin config with no self-evident purpose — say what can be confirmed and note the uncertainty directly in the header (for example, "Exact purpose unclear from static reading; confirm with recent commit history or the file's author before relying on this") rather than presenting a guess as settled fact.

When you write or touch a header, re-open the file against it once more before moving on. Treat this as part of the work, not an optional nice-to-have.

**2. Write for two audiences at once: engineers, and people who will never open the code.**

Assume some readers are product managers, support staff, or leadership who need to understand what a file does and why it matters without reading it. Lead the "Summary" and "What it does" lines with a plain-language explanation of purpose and effect — what capability this enables, what problem it solves — before or alongside technical specifics. Avoid unexplained jargon and acronyms; gloss anything non-obvious on first use within that header. "How it fits in" can be more technical (file paths, function/class/module names, since it's inherently about code structure) but should still say what a dependency is *for*, not just name it. This isn't about writing two versions or dumbing anything down — it's writing one version that works for both audiences.

Example, for a file that renews login tokens in the background:

Not this (developer-only, jargon-first, and skips the format above):
```
Handles JWT refresh token rotation via Redis-backed blacklist with exponential backoff.
```

This (accessible, precise, and in the standard shape):
```
Summary: Keeps users logged in without asking for their password too often, by
quietly renewing their login token in the background.

What it does: Checks a shared blocklist (stored in Redis) so an old token can't
be reused, issues a new short-lived token before the old one expires, and retries
with longer waits if that blocklist check briefly fails.

How it fits in: Called by the auth middleware on every request; depends on the
Redis client shared with the rest of this codebase.
```

## Part A — File header comments

### Requirements
- Every applicable file gets a header, in whatever comment syntax that file type supports, following the format and standards defined above.
- Place the header at the very top of the file, before imports/includes/requires. If the file has a shebang line (`#!...`), that must stay the first line of the file — place the header immediately below it instead. The one exception to "top of file" is where a language has a strong idiomatic convention otherwise (for example, Go package doc comments sit immediately above the `package` line); follow that convention instead where one exists.
- Use each language's native comment syntax: module-level docstring for Python (before imports, or below the shebang for executable scripts), `//` or `/* */` for C-family languages, `#` for shell/Ruby/similar, native SQL comment syntax (`--` or `/* */`) for `.sql`, and so on.
- Already-prose `.md`/`.markdown` files: no header here (skip) — per Scope, these still get a map entry in Part B, just not an in-file header.
- JSON files (config/data, not lock files) have no native comment syntax: add a reserved top-level key, `"_description"`, whose value is the same three-part summary as one string. Use this exact key name everywhere. Before doing this, confirm nothing in the codebase does strict schema validation on these files that would reject an unrecognized key; if something does, either allowlist the key there or use whatever metadata mechanism that validator already supports instead.
- Apply the same reserved-key approach to any other structured, comment-less file format in this repo that permits arbitrary top-level keys — same validation-safety check applies.
- If a file's format has neither comment syntax nor a safe way to add a metadata key (strict CSV, binary formats, etc.), skip the in-file header but still include the file in `docs/map.json` (Part B), with a description written from directly inspecting the file — the map doesn't require modifying the file itself.

### Constraints
- Comments and one metadata key only — no behavior changes to any file.
- Don't touch excluded paths.

### Acceptance criteria
- Every non-excluded file has a header matching the three-part structure, written to the standards above.
- Every non-excluded JSON file has a `_description` key, and the project's existing build, tests, and/or runtime still succeed with it present.
- No header states a capability, endpoint, parameter, or behavior that doesn't actually appear in that file's code.
- Any reader outside engineering could read a header's "Summary" and "What it does" lines and understand what the file is for, with no unexplained jargon.

## Part B — docs/map.json

### Requirements
- Add a script, written in whatever language best matches this repo's existing primary language and tooling (so it fits naturally rather than introducing an unrelated runtime dependency). Put it in whichever existing directory already plays the role of a scripts/tooling home — whatever it's actually named (`scripts/`, `tools/`, `bin/`, etc.) — matching that directory's existing style. Only create a new top-level directory for it if nothing resembling this convention exists at all.
- The script walks the repo, applies Part A's exclusion list, and generates `docs/map.json` as a flat list, one entry per file:
  ```json
  {
    "path": "src/example/module.py",
    "raw_url": "https://raw.githubusercontent.com/<owner>/<repo>/refs/heads/<branch>/src/example/module.py",
    "description": "<the Summary line from that file's Part A header>"
  }
  ```
  (Illustrative only — every value above is derived at runtime, never hardcoded.) Extract the description by finding the "Summary:" label in that file's header (after stripping comment markers) and taking the text that follows it — this is exactly why every header uses that label consistently.
- For every file that gets a Part A header, Part A must run first, since `description` is pulled directly from what it wrote — sequence these two parts in that order, not in parallel. The one exception is `.md`/`.markdown` files (per Scope, included in the map but with no Part A header): for these, use the file's own title as the description — the text of its first Markdown heading (a line starting with `#`), or if there is none, its first non-blank line. This still needs no comprehension step inside the script itself, keeping the whole map mechanically regenerable in one fresh pass.
- Derive `<owner>`, `<repo>`, and `<branch>` from git itself, rather than hardcoding this repo's current name, so the map keeps regenerating correctly if this repo is renamed, moved, or forked:
  - Owner/repo: read `git remote get-url origin` (falling back to the first configured remote if `origin` doesn't exist), and parse both the SSH form (`git@github.com:owner/repo.git`) and the HTTPS form (`https://github.com/owner/repo.git`), stripping any trailing `.git`.
  - Branch: always use the repository's default branch, never whatever branch happens to be checked out. Task/feature branches are typically deleted after merging, which would silently break every `raw_url` in the map the moment that happens. Read `git symbolic-ref refs/remotes/origin/HEAD` and strip the `refs/remotes/origin/` prefix; if that ref isn't set (common after a shallow clone), run `git remote set-head origin --auto` once and re-read it.
  - This defaults to GitHub's raw-content URL pattern (`raw.githubusercontent.com`), the most common host by far. If this particular repo's remote points somewhere else (GitLab, Bitbucket, a self-hosted git server), adapt to that host's own raw-file URL convention instead — the owner/repo parsing above already reveals the host, so branch on that rather than assuming.
- Rebuild `docs/map.json` from a full, fresh walk of the working tree on every run, rather than patching the previous file — this is what guarantees added, removed, and renamed files are reflected correctly, with no stale or duplicate entries.
- Add a check to whichever CI workflow already exists in `.github/workflows/` (inspect first) that fails if `docs/map.json` is out of date relative to the actual file tree. If no workflow exists yet, create one whose only job is this check — a descriptive name like `verify-docs-map.yml` is fine, or match this repo's naming convention if one exists from elsewhere in the org. Concretely: re-run the generation script (into a temp location or a clean checkout) and fail the check if the result differs at all from the committed `docs/map.json`.

### Constraints
- `docs/map.json` is itself generated output — exclude it from Part A's header requirement and from its own listing.

### Acceptance criteria
- `docs/map.json` exists, includes every non-excluded file with a correct path, a correctly-formed raw URL pointing at the default branch, and a non-empty description. (A URL for a file only added in this same PR won't resolve until the PR merges — that's expected, not something to fix.)
- `.md`/`.markdown` files (READMEs and similar) appear in the map too, per the Scope exception above — not just code and config files.
- Deleting a file and re-running the script removes it from the map; adding a file and re-running adds it, with a description pulled from that file's own Part A header (or its own title, for `.md` files).
- The CI check fails against a deliberately stale map and passes once regenerated.

## Before finishing

Whether this was a first pass at Part A/B or a small update along the way:
- Spot-check a sample of headers you wrote or touched against the actual code one more time — the single most effective way to catch an invented or overstated description before it ships.
- If you created or modified the CI check itself, confirm it actually fails against a deliberately stale map and passes once regenerated, rather than assuming the logic is correct.
- Confirm the project's existing tests/build still pass.
