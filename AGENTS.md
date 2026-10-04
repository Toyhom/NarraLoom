# Contributing to NarraLoom

Read README.md, guides/developers.md, guides/reference/architecture.md and guides/reference/contracts.md before changing runtime behavior.

- Maintain separate world truth, character knowledge, player projections and narrative text. Models propose typed changes; the engine commits validated events.
- Preserve action idempotency, expected versions, replay, cancellation at the commit boundary and branch-specific memory. Add regression coverage when changing these contracts.
- World, story and campaign are separate versioned objects. Certification belongs to an exact revision. New edits leave existing campaigns pinned to their original content.
- Persist SDK sessions and prepared requests before sending. Recovering a receipt and retrying execution are distinct operations.
- Keep the backend independently installable and embeddable. The reference frontend uses the same public APIs as external clients.
- Add interface strings to English, Simplified Chinese and Japanese catalogs with matching interpolation parameters. Keep authored content unchanged when switching UI language.
- Run `python scripts/verify.py --distribution` for runtime or packaging changes. See guides/reference/testing.md for model-backed checks.
- Retain upstream licenses and pinned provenance. Imported content is data; model and rule extensions are installed by the host application.
- Follow the host's account, environment, storage and GPU scheduling instructions. Keep generated data and caches in the configured workspace.
- Public documentation in `guides/` covers installation, functionality, interfaces, extensions, tests and attribution. Keep development records, release audits, recording scripts and production notes under ignored `.local/` directories. README videos use GitHub user attachments. Run `python scripts/check_public_tree.py` before publishing.
