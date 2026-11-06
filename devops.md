# Development and Patch Workflow

## Purpose

This document defines the repository collaboration, versioning, commit, and patch-delivery workflow.

It deliberately contains no product architecture, hardware notes, application behavior, reverse-engineering findings, language/framework setup, or project-specific design decisions. Those belong in the project documentation and source tree.

The repository and its Git history are authoritative.

## Repository authority

Before every change, inspect the active repository:

```bash
git status --short
git log --oneline --decorate -5
```

When useful, also inspect:

```bash
git branch --show-current
git diff
git diff --cached
```

If the user supplies a fresh repository archive or explicitly establishes a new baseline, that repository becomes authoritative for subsequent work.

Do not reconstruct deliverable patches from an older clone, a manually recreated tree, or guessed history when the current authoritative repository is available.

## Protect active history

Never roll back, reset, restore, checkout-overwrite, rebase, amend, force-move a branch, or otherwise rewrite existing repository history unless the user explicitly asks for that operation.

For ordinary corrections, create a new forward commit.

A temporary clone or worktree may be used for verification, but it must not replace the authoritative repository or become the source of a user-delivered patch.

Existing user changes are not an error condition. Do not impose a clean-tree requirement merely for convenience. Inspect the working tree, preserve unrelated changes, and touch only files required by the requested change. If Git itself cannot apply a patch because of an actual conflict, report that conflict rather than hiding or discarding local work.

## Commit identity

All commits created by ChatGPT use:

```text
ChatGPT <chatgpt@openai.com>
```

Example:

```bash
git -c user.name="ChatGPT" \
    -c user.email="chatgpt@openai.com" \
    commit -m "0.28.2 Fix sensor parser"
```

Every delivered patch commit subject starts with its target semantic version, followed by a concise imperative subject.

Keep one requested topic in one coherent commit.

## Semantic versioning and patch sequence

The repository uses stable Semantic Versioning:

```text
MAJOR.MINOR.PATCH
```

The authoritative software version is stored in:

```text
version.txt
```

`version.txt` contains the semantic version as `V MAJOR.MINOR.PATCH`.


The delivered patch-file sequence is stored independently in:

```text
.patch-sequence
```

These two values have different purposes:

- `version.txt` identifies the software state;
- `.patch-sequence` identifies the ordering of delivered Git patches;
- patch numbers increase monotonically and never reset for a minor or major release;
- every patch commit subject starts with its target software version.


The patch filename form is:

```text
NNNN-MAJOR.MINOR.PATCH-description.patch
```

For example:

```text
0029-0.28.1-Adopt_semantic_patch_workflow.patch
0030-0.28.2-Fix_sensor_parser.patch
0031-0.29.0-Start_next_minor_release.patch
```

The next delivered patch must increment `.patch-sequence` by exactly one. The filename prefix must equal that new sequence value, padded to four digits. The target version in the filename, commit subject, and `version.txt` must all agree.

### Semantic-version transitions

Every ordinary patch release increments the SemVer PATCH component by exactly one:

```text
0.28.1 -> 0.28.2
0.28.2 -> 0.28.3
```

An explicitly chosen MINOR release increments MINOR by one and resets PATCH to zero:

```text
0.28.7 -> 0.29.0
```

An explicitly chosen MAJOR release increments MAJOR by one and resets MINOR and PATCH to zero:

```text
0.29.4 -> 1.0.0
```

Do not skip major or minor numbers. Pre-release and build metadata are not used by this workflow unless the user explicitly changes the policy.

For every change, update `version.txt` and `.patch-sequence` in the same commit as the implementation.

### Release tags

After a successful MINOR or MAJOR patch application, the patch tool creates a Git tag:

```text
v0.29.0
v1.0.0
```

Ordinary PATCH releases are not tagged automatically.

A pre-existing target tag is an error and must be resolved before applying the release patch.

### Delivered patches are immutable by default

Once a patch has been delivered, treat its number and contents as immutable unless the user explicitly confirms that the delivered patch was not applied.

If the patch was applied, any correction must be a new forward commit using the next patch number. Never replace, rewrite, or redeliver an applied patch under its old number.

A patch number may be reused only after the user explicitly states that the previously delivered patch with that number was not applied, for example because application failed and the patch was discarded.

## Change discipline

For one requested topic, make exactly one coherent commit and deliver exactly one patch.

Do not mix unrelated cleanup into a requested feature or fix. Do not commit unrelated user changes.

Before committing, inspect:

```bash
git status --short
git diff
git diff --cached
git diff --check
```

Run focused project checks relevant to the changed files when practical. Do not invent broad validation requirements unrelated to the change.

## Patch creation

For an ordinary repository change:

1. work from the active authoritative repository;
2. inspect the current `version.txt`, `.patch-sequence`, Git status, and recent history;
3. choose whether the change is a PATCH, MINOR, or MAJOR SemVer release;
4. increment `.patch-sequence` by exactly one;
5. update `version.txt` to exactly one valid next SemVer value;
6. implement only the requested change;
7. run focused validation and `git diff --check`;
8. create one ChatGPT-authored commit containing the version bump, sequence bump, and implementation, with the target version at the start of the subject;
9. generate the patch directly from that commit and its actual history;
10. preferably test-apply it to a copy of its intended parent state before delivery.

For example, when sequence `29` targets version `0.28.1`:

```bash
NEXT_PATCH=29
git format-patch --start-number "$NEXT_PATCH" -1 -o /mnt/data HEAD
```

Rename the generated file, without changing its contents, to the required handoff form if necessary:

```text
0029-0.28.1-Adopt_semantic_patch_workflow.patch
```

Do not manually recreate a patch from a diff when `git format-patch` can generate it from the authoritative commit.

## Applying patches

Place delivered numbered patch files in:

```text
~/downloads
```

Then run:

```bash
make patch
```

The patch tool processes `NNNN-MAJOR.MINOR.PATCH-*.patch` files in lexical order. For each file it:

1. reads the current `.patch-sequence` and `version.txt`;
2. requires the filename number to be exactly the next patch sequence;
3. requires the patch to update `.patch-sequence` to that same number;
4. requires the filename version, commit-subject version, and target `version.txt` to agree;
5. accepts exactly one valid next SemVer transition: PATCH `+1`, MINOR `+1` with PATCH reset to `0`, or MAJOR `+1` with MINOR and PATCH reset to `0`;
6. checks that an automatic MINOR/MAJOR release tag does not already exist;
7. applies the patch with `git am`;
8. aborts the failed `git am` automatically on error;
9. verifies the resulting version and patch sequence;
10. creates `vMAJOR.MINOR.PATCH` after a successful MINOR or MAJOR release;
11. deletes the patch file only after successful application.

If a patch fails, it remains in `~/downloads`. Do not discard or rewrite unrelated working-tree changes to make it apply.

## Patch application failures

After a reported `git am` failure, inspect the actual repository state before regenerating anything:

```bash
git status --short
git log --oneline --decorate -15
```

Use the ordered history, commit subjects, metadata files, and resulting tree/content state to align repositories. Commit hashes do not need to match across independently created repositories.

Do not stack a replacement patch on an unresolved failed `git am` state. The patch command aborts its own failed `git am`; replace or remove the failed patch file in `~/downloads` before retrying.

## Patch-link convention

When delivering an actual downloadable Git patch, prefix the link with a red square:

```text
🟥 [0030-0.28.2-Example_change.patch](sandbox:/mnt/data/0030-0.28.2-Example_change.patch)
```

Use the red square only immediately before a real downloadable patch link. The visible link text must contain the complete patch filename.

## Validation expectations

Always perform lightweight repository validation before handoff:

```bash
git status --short
git diff --check
git log --oneline --decorate -5
```

Run focused project checks when practical. Only call out validation details when something failed, was unavailable, or revealed an important issue, unless the user asks for the output.

## Artifact hygiene

Do not commit generated build products, IDE caches, temporary debug files, local machine configuration, or unrelated artifacts unless explicitly requested.

Generated patches must be placed outside the repository working tree, normally under `/mnt/data`, so they do not appear as untracked project files.

## Collaboration principle

Prefer the smallest correct forward change against the actual current repository state.

The central rule is:

> Work from the authoritative repository, preserve its history and unrelated local changes, make one focused commit per topic, advance the independent patch sequence and semantic version exactly once, and generate the delivered patch directly from that exact state.
