# Architecture

NarraLoom is a modular Python application with an independent HTTP API. A single writer owns each event journal. Models run behind replaceable asynchronous adapters; clients consume player projections and committed story output.

| Layer | Modules | Responsibility |
| --- | --- | --- |
| Host and API | `config`, `app`, `cli`, `client` | Workspace paths, sessions, API transport and recoverable client requests |
| Authoring | `content`, `studio`, `content_review`, `quality` | Worlds, stories, revisions, generation, review and isolated playtests |
| Model calls | `gateway`, `engines`, `prompts`, `decisions`, `routing` | Per-role configuration, contracts, budgets, repair and traces |
| Turn execution | `runtime`, `planning`, `rules`, `world` | Plans, NPC reactions, deterministic outcomes and narrative commits |
| Gameplay | `action_modules`, `checks`, `rulepacks`, `state_rules`, `simulation`, `continuity` | Versioned numerical checks, equipment, authored mechanics, world activity and story carry-over |
| Perspectives | `memory`, `semantic_memory`, `players`, `rooms`, `trades` | Visible history, optional embedding recall, independent players and confirmed transfers |
| Persistence | `store`, `journal`, `idempotency` | Durable records, writer lock, receipts and recovery |
| Portability | `packages`, `catalog`, `imports`, `backups`, `avatars` | Native content, starter copies, conversion, saves and presentation assets |

## Authoring lifecycle

A world stores reusable setting and character definitions. A story pins its world revision and content snapshot. A campaign pins the compiled story template. Creation jobs checkpoint generated drafts and their test stages; a successful report certifies only the tested revision. Editing produces a new revision and test job. Late test results cannot certify a newer edit.

Structure checks and declared-rule routes run in isolated state. Model reviewers compare narrative claims with the compiled opening and mechanics. Model playtests exercise a selected story route, the first custom-state route and the first host test route of each action module. Recipients of shared packages repeat validation with their own models.

## Turn lifecycle

1. Validate session, controlled actor, action ID and expected world version. Repeated identical requests recover their original receipt.
2. Build bounded context from the scene, character knowledge and relevant memories. Optional decision routing handles its declared narrow task.
3. The game master proposes a typed plan. Rules validate references and legal operations, then determine outcomes and recorded dice.
4. NPC models receive their own perspectives and permitted reactions. Accepted reactions are resolved against the same baseline and recorded outcomes.
5. The narrator describes the player's visible result. The runtime validates and commits the batch with its narrative and receipt.
6. Clients receive committed snapshots and refresh the player view. Replay rebuilds state from stored events without model calls.

Only the engine's validated commit changes canonical state. Model summaries and presentation adapters consume projections. Game time advances through committed actions; bounded simulation proposes changes within that pipeline.

## Extension boundaries

`create_app` accepts `AppConfig`, an in-memory `model_config`, a model `registry` or complete `gateway`, a `check_registry`, an `action_registry` and an `avatar_factory`. Generation and decision transports declare capabilities. Deterministic check engines pin their ID/version in each world and share the existing commit pipeline. A host can embed the backend in ASGI or build any frontend on the API.

Host-registered action modules supply typed parameters and portable state through the existing event pipeline. New event types and persistence internals are versioned core code, with ownership, replay and recovery contracts. See [action modules](ACTION_MODULES.md). See [check engines](CHECK_ENGINES.md), [contracts](CONTRACTS.md), [model engines](ENGINES.md), [SDK](CLIENT.md) and the [developer guide](../guides/developers.md).

## Hosting

Use one process per data directory and one active action per branch. Long model calls have timeouts and call/repair budgets. A model failure preserves a retryable action or authoring job; uncertain writes expose recovery-required state. A host owns asset execution and inference resources. Built-in browser identities suit individual and trusted-group deployments; hosted account systems can sit above these interfaces.
