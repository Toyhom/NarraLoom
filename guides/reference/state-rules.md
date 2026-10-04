# Custom state, conditions and effects

World and story editors expose custom state and story conditions. Enable automatic state design during creation to generate variables, optional actions, triggers and executable acceptance routes. Creators can also add and edit these definitions directly.

World rules belong to the world revision; story rules belong to that story. Stories can read world variables, while world rules stay independent of a particular story's clues, objectives and clocks. Variable, action and trigger IDs must be unique in their respective combined namespaces.

When a new story inherits a campaign in the same world revision, world variables and world-rule usage records can carry forward. Story variables, one-time triggers and cooldowns restart. The old branch retains its state.

## Supported mechanics

- Bounded integers, Boolean switches and enumerated phases. Increment/decrement clamps to bounds; direct assignment must be within bounds.
- All/any conditions over variables, actor resources, item quantities, locations, known facts, objective status, clocks, companions and game time.
- Player actions with fixed time cost, locations, prerequisites, cooldowns or one-time use. The planner can choose a currently legal action; players can select it explicitly.
- Triggers after a turn, movement, investigation, objective attempt, custom action, attack, rest, speech or waiting. Targets and conditions can narrow the trigger. To require objective success, also test its `completed` status.
- Effects that set/increment variables, adjust enabled actor resources, advance story clocks, disclose an existing fact to a specified actor or publish a recorded message to an actor.

For example, investigation progress reaching two can unlock a breakthrough and show the player a new lead. The engine applies the effects and the narrator describes their visible consequences.

## Visibility and execution

Variables are public-to-all-actors, player-only or GM-only. Public values are authored common information. NPC contexts omit player-only values/messages; player views and narration omit GM-only values. Creator configuration and full backups contain all definitions.

An action applies declared effects, advances game time and built-in clocks, then evaluates triggers. Triggers scan in declaration order for at most three rounds; each runs at most once per player action. Longer chains continue on the next game action. One-time flags, usage counts and last-run times are recorded in events. Repeating triggers require at least one second of game cooldown.

NPCs can relay facts they observe during these effects. A fact first supplied to an NPC by a trigger is shared after the trigger pass. Conditions depending on that newly shared knowledge are evaluated on the next action.

Each rule has at most six effects; automatic triggers have a 96-event limit per action. Exceeding a limit rejects the whole action. Resource payments validate in order; insufficient funds make the action/trigger unavailable without partial payment. Out-of-character discussion, notes and the simulation pause switch do not execute these triggers.

Custom state participates in the canonical journal, idempotency, cancellation, branches and replay. Rule edits create new content revisions and leave existing campaigns pinned.

## Acceptance routes

Each rule set declares independent routes from the initial story state, containing actions and final conditions. Saving a story runs:

1. Type, bound, reference and world/story scope checks.
2. Every declared deterministic route, including event replay. Combined routes must actually execute every custom action and trigger. Failures identify the route and step.
3. Model-assisted consistency review of narrative claims about mechanics and secrets. Issues cite actual text paths and quotations; a separate call checks the claim. Automatic generation permits up to two bounded narrative repair rounds. Authored edits and native imports preserve their text unless the creator requests revision.
4. The normal actual-model story route and the first custom-state route in a fresh branch. Additional state routes use deterministic execution.

All checks must pass for that story revision before play. Saved drafts remain editable after review failure. Revision checks prevent an old review from overwriting a newer edit. Declared routes establish specific coverage; alternate free-form choices still benefit from creator playtesting.

## API

`WorldBlueprint.state_rules` and `StoryBlueprint.state_rules` accept `StateRules`. Creation requests use `custom_states=true` for model-designed rules. A player can submit:

```json
{"selected_operation": {"kind": "state_action", "target_id": "declared_action_id"}}
```

The server revalidates conditions. The player view's `custom_state` exposes visible variables and available actions. Trigger definitions, hidden conditions and GM values stay in creator state.

Imported mechanics can be adapted to this typed format with a conversion report. Supported effects operate on declared data; arbitrary JavaScript, macros, MVU scripts and nested JSON writes require their own trusted host extensions. Item-count conditions sum matching inventory items; effects currently cover the operations listed above.

See [StateRules schema](../../schemas/StateRules.schema.json), `tests/test_state_rules.py`, and `scripts/check_states_browser.py`. `scripts/check_content_review.py --output outputs/validation/review` evaluates mechanics-review contrasts with the configured model.
