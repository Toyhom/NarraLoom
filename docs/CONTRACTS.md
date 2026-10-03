# Data and recovery contracts

The authoritative Python types live in `content.py`, `contracts.py`, `state_rules.py`, `packages.py` and the corresponding modules under `src/roleplay_world`. [schemas](../schemas) contains generated JSON Schema. Run `python scripts/export_schemas.py` after changing a public type. The running API publishes `/openapi.json`.

## Content identity

- `WorldBlueprint` contains shared locations, characters and optional rules/state/simulation.
- `StoryBlueprint` contains opening text, player role, clues, goals and story mechanics. It pins its world revision and snapshot.
- Campaigns retain a compiled template. Existing saves remain stable across author edits.
- Test certification refers to an exact story revision and is cleared when that revision changes.

Entity IDs are stable references. Display names and translated interface labels are separate from canonical enums and IDs. Creator content retains its authored language.

## Requests

`CreateWorld`, `CreateStory` and `NewCampaign` accept an optional `request_id`. Same owner, ID and payload recover the original durable result. A different payload returns `request_id_conflict`. Worlds and stories share a creation ID space; campaign creation has its own. Omitted IDs request new creation.

An `ActionCommand` contains `schema_version`, `action_id`, `expected_world_version`, `mode` and `text`, plus supported operation/visibility fields. The campaign and branch come from the URL. The session determines actor authority. Modes are `act`, `say`, `wait`, `ooc`. Game-outside discussion can add a saved narrative turn/version while preserving game facts and time.

Persist the session and prepared request before sending. Receipt recovery preserves original IDs and versions; execution retry is an explicit separate operation. Stale versions return a conflict. [CLIENT](CLIENT.md) gives recovery examples.

## Commit and replay

A committed action stores its validated event batch, outcomes, visible narrative and action result together. World versions increment at the commit boundary. Retries reuse recorded plans/outcomes where available; replay executes stored events without new model inference or dice rolls.

Cancellation before commit leaves the world unchanged. A committed result remains authoritative if a cancellation or network failure arrives later. Writer uncertainty enters `recovery_required`; inspect the durable journal before attempting new work.

## Visibility

World truth, NPC knowledge, individual player knowledge and visible narrative have separate projections. Knowing that someone said a claim does not make the claim a canonical world fact. Players control their own decisions. Private conversations and trades are filtered per participant.

NPC reply schemas include facts observed through the current action's deterministic effects. Transfers of newly observed facts follow the clock or authored events that establish the NPC's knowledge. Facts outside that resulting perspective remain invalid disclosures.

Player notes contain visible history. Creator exports, native content packages and full backups contain authored secrets and are intended for creators or restoration. See [package format](COMMUNITY_PACKAGES.md).

## Model responses

Generation receives a task-specific schema and returns JSON validated by Pydantic and semantic rules. Decision responses validate question/option sets and probability distributions. A transport success confirms schema compatibility; semantic quality is evaluated with task examples and playtests.
