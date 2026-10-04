# Native world and story packages

NarraLoom packages share one fixed world revision and up to eight stories in that world. Authors build a private, immutable snapshot, download it as `.narraloom.zip`, and optionally make it visible through a link or the current server’s community shelf. Recipients get editable copies and run their own automatic tests before play.

Package metadata identifies the author and their stated distribution terms.

## Creator workflow

1. Create or import a world, write/generate stories, and complete their current-revision tests.
2. In that world, choose **Create a world package**. Pick a pinned world revision and up to eight tested stories. Stories using different world revisions need different packages.
3. Enter a package ID, release number, public title/summary, author, distribution terms, optional tags, model recommendations and known limitations. Keep spoilers out of the public summary. Upstream attribution and conversion history stay inside the download; the new package license does not override their licenses.
4. Choose whether to include ready 2D assets. The package contains only the portrait, mouth atlas and rig. Generation reference images, voice samples, campaign dialogue and provider configuration are not read. If assets are omitted, exported avatar bindings are cleared and the omission is declared; source worlds are unchanged.
5. Build the private package. Download it or change its visibility under **My packages**. A changed snapshot needs a new release number. Updating the source world or story never updates an already-built package.

| Visibility | Discovery and access |
| --- | --- |
| Private | Only the owning session can inspect, download or install it |
| Unlisted | Anyone who has the package URL can inspect, download or install it; absent from search |
| Listed | Included in this server’s shelf and searchable by title/summary/author, exact language and tag |
| Withdrawn | New public downloads/installs stop; owner retains access, and existing recipients keep their copies |

Only public metadata is fetched while browsing: creator summary, titles, counts, languages, tags, dependency declarations and limitations. The full package intentionally includes GM secrets and authored source/provenance, because it is a creator artifact. Downloading or installing is a separate action. No external URLs or package scripts are fetched or executed.

## Recipient workflow

Open a share link or browse the shelf, choose stories, and click **Add to my worlds and test**. Model calls use the receiving session’s settings. Each selected story has a separate durable test job, with normal cancellation/retry and exact-revision gating. The author’s test summary is advisory and cannot certify the recipient’s copy.

A downloaded file can be previewed and installed through **Import a package file**, including after the author withdraws the online listing. A later partial install from the same bytes adds the missing stories to the same world; it never overwrites edited worlds/stories or existing campaigns. New stories stay pinned to the package’s original world snapshot even when the recipient has edited their world meanwhile.

Worlds using a [check engine](check-engines.md) retain its pinned ID, version and options. Package preview reports that dependency. The recipient's host registers the matching implementation before automatic testing and play. If it is missing, the imported content remains available for editing and the test job reports `check_engine_unavailable`; install the implementation and retry that job. Packages containing the `check_engine` world field require NarraLoom 0.16.0 or newer.

Worlds with [action modules](action-modules.md) retain their schemas, initial state and pinned implementation IDs. Package previews list these dependencies. The recipient registers them before testing; missing implementations report `action_module_unavailable`. Snapshots containing the `action_modules` world field require NarraLoom 0.19.0 or newer.

Up to eight jobs from one package count as one creation batch for admission, and the existing single-model-job semaphore still runs them serially. A failed story does not stop other selected stories from being tested. Retry/continue remains per story. Existing single-story native exports, character cards, PNG, CHARX and world books retain their prior APIs.

## Portable 2D assets

The optional render subset supports the existing `deformable-portrait` version 3 / `source-lip-warp-v3` pipeline, with up to four distinct assets. References are rewritten to recipient-owned avatar records, and assets are available through the normal Avatar and room APIs. Imported assets render without GPU generation or the author’s local directory. Text-only/headless use does not require Pillow; installing image assets requires the `avatar` optional dependency. Imported finished assets cannot restart a nonexistent generation job.

Images are bounded PNGs, and rig texture references must name the bundled portrait and mouth atlas. ZIP paths, duplicate entries, symlinks, encryption, extra files, hashes, dimensions and declared dependencies are validated before library mutation. Current package limits: 32 MiB compressed/uncompressed, 2 MiB authored JSON, 14 files, one world, eight stories and four render assets. Packages with unknown schema versions/capabilities are rejected with a diagnostic; they are not silently downgraded.

## Backend contract

| Method / path | Request / result |
| --- | --- |
| `POST /api/studio/packages` | `PackageBuild`: metadata, `stories=[{id,revision}]`, `include_avatars`; creates a private snapshot |
| `GET /api/studio/packages` | Current owner’s package metadata, including private/withdrawn records |
| `PUT /api/studio/packages/{id}/visibility` | `PackageVisibility`: expected publication revision and visibility; rejects stale updates |
| `GET /api/community` | Public metadata search: `q`, `language`, `tag`, `offset`, `limit` (up to 50); `{total,items}` |
| `GET /api/community/{id}` | Metadata subject to visibility |
| `GET /api/community/{id}/download` | Immutable ZIP, with creator filename |
| `POST /api/community/{id}/install` | `PackageInstall`: optional `story_keys`; absent means all; returns the first selected story’s normal job |
| `POST /api/studio/packages/preview` | Raw ZIP body; validates and returns metadata without writing a library or calling a model |
| `POST /api/studio/packages/import?story_keys=story_1&story_keys=story_2` | Raw ZIP; optional repeated story selectors, otherwise all; same installation identity as online install |

Mutations use the existing session cookie and CSRF token. Poll `/api/studio` to follow all package test jobs; the first job’s completion does not certify all other stories. `batch_id` groups package tests, `package_digest` identifies the original bytes. New library/asset/job references are committed in a single journal frame. Files are fsynced before their references; a failed commit may leave an unreferenced file, never a certified partial library. The runtime stays single writer.

The archive contains `manifest.json`, `content.json` and optional `assets/<portable-id>/puppet/{rig.json,portrait.png,mouth-atlas.png}`. The manifest records format/schema, creator metadata, engine floor, dependencies, omissions and each file’s SHA-256/size. `content.json` preserves authored world/story payloads, upstream provenance, original story revisions and advisory test summaries. No provider secret or executable plugin field is introduced into engine authority.

New publication records require a runtime that recognizes the `publications` library (v0.12+). Existing campaign event formats and hashes are unchanged. Older runtimes cannot read journals with the new publication collection; use an appropriate pre-upgrade copy for rollback.

## Verification

`python -m pytest -q tests/test_packages.py` covers deterministic snapshots, version/owner/test gates, malformed archives, optional render portability, duplicate/partial installs, admission, atomic failure and restart/withdrawal behavior. `python scripts/verify.py --community` runs the full acceptance entry point. `scripts/check_community_browser.py --url ... --output outputs/validation/<unique-run>` uses actual models and independent browser sessions for creation, package building, public listing, recipient tests/play, withdrawal and file installation. Optional `--creator-session` and `--avatar-id` reuse an owned ready asset without starting a GPU job; evidence must identify any test metadata fixture. `--reuse-creation` reuses completed creation jobs after a harness/UI failure and retains the original report.
