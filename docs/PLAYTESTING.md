# Playtest complete campaign trajectories

The installed `narraloom playtest` command runs authored actions through the normal planner, rules, characters, autonomous world and narration pipeline. Each run has an isolated event journal. Use it to check a creator's own story over many turns, inspect failures, or repeat the same trajectory with another module configuration.

## Prepare and run

Export one native world/story JSON from the studio and install `.[research]`. Write a plan using the [PlaytestPlan schema](../schemas/PlaytestPlan.schema.json), or generate the dialogue-memory example:

```bash
python examples/make_playtest_plan.py --source my-story.json --turns 100 --output plan.json
narraloom playtest --source my-story.json --plan plan.json \
  --models-config configs/models.local.json --secrets-root secrets \
  --output outputs/playtests/my-story
```

The example addresses an NPC at the opening, records an account, discusses other subjects and asks a paraphrased recall question. Edit the generated JSON to choose dialogue languages, actions and expected outcomes. For hybrid retrieval, configure the optional [memory embedding module](MEMORY.md). Provider limits and failures remain visible in the normal traces.

## Plan format

```json
{
  "format": "narraloom.playtest-1",
  "player_name": "Traveler",
  "steps": [
    {
      "id": "remember_arrangement",
      "command": {
        "mode": "ooc",
        "text": "Record the arrangement.",
        "note_record": {"id": "arrangement", "text": "Return the compass after the festival."}
      },
      "expect": {
        "properties": {"view": {"properties": {"game_time_s": {"const": 0}}}}
      },
      "recalls": [
        {
          "query": "compass",
          "expect": {
            "contains": {"properties": {"source_id": {"const": "arrangement"}}, "required": ["source_id"]}
          }
        }
      ]
    }
  ]
}
```

A plan contains 1–1000 uniquely named steps. `command` uses the [ActionCommand](../schemas/ActionCommand.schema.json) fields; the runner assigns its action ID and expected version. Free text, selected operations, private conversations, notes and simulation controls use their existing runtime contracts. Authored text retains its language.

Each `expect` is JSON Schema Draft 2020-12 applied to `{result, view}` after commit. The result is the acting player's committed narrative; the view is that character's projection. An optional `recalls` list contains up to eight queries per step. Each query accepts `actor_id`, `limit` and an earlier `world_version`; its `expect` applies to the returned source-record list. This host-side evaluation interface lets researchers inspect NPC perspectives. Player-facing access remains governed by the HTTP API.

Assertions stay outside model prompts and repair requests. Failed assertions remain in the report while subsequent actions continue. A step without assertions is counted as unscored. Memory probes read historical snapshots without advancing the game.

## Checkpoint and resume

Add `--max-steps 25` to stop after 25 newly assessed steps. Continue with the same source, plan, model configuration and output plus `--resume`. The runner verifies content and implementation fingerprints and recovers committed action receipts. Completed probes and steps are reused.

When execution failed or was interrupted before commit, inspect the report and trace, then add `--resume --retry-failed` to retry. The same action ID, saved plans and recorded rule outcomes are retained. Failed attempts stay in the report. A crash can leave model-call accounting incomplete; `steps_with_incomplete_attempt_accounting` identifies affected steps. Read-only probes interrupted before their checkpoint can run again on resume.

Changing the story, plan, model behavior settings or framework implementation requires a new output directory. Authentication credentials can rotate. Use a provider revision label when changing native adapters or deployed weights. Dice use each action's recorded seed; separate runs can have different rolls.

The final check closes and reopens the store and verifies the reconstructed state hash. Output contains `report.json`, `data/` and raw `traces/`; these include story content and private perspectives. Keep them in the research workspace. Exit status is `0` for completion with all scored assertions passed or an intentional checkpoint, `1` for a completed assertion failure or stopped execution, and `2` for invalid CLI input.

## Embed in research code

```python
from roleplay_world.playtesting import load_plan, load_source, playtest

report = await playtest(
    load_source("my-story.json"), load_plan("plan.json"),
    config=model_config, registry=my_model_registry,
    check_registry=my_check_registry,
    output="outputs/playtests/native", secrets_root="secrets",
)
```

The Python API accepts a compiled template and an authored plan. [playtest_adapter.py](../examples/playtest_adapter.py) demonstrates a native adapter, an actual item transfer and checkpoint recovery with deterministic fixture responses. Use [module evaluation](EVALUATION.md) for frozen individual calls. Campaign reports measure the exercised sequence and assertions; independent playthroughs assess writing, agency and alternate paths.
