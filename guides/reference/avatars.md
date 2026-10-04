# Optional 2D NPC presentation

Bind a ready avatar to a world character or select one while creating the world. When that NPC shares the player's scene, the reference frontend displays a deformable portrait with breathing, blinking, expressions, gestures and text-paced mouth movement. Committed dialogue drives silent subtitles. The player can collapse or replay the stage.

The portable format is `deformable-portrait` version 3 with `source-lip-warp-v3` binding. Native world packages can include the render subset: portrait, mouth atlas and rig. Install `.[avatar]` to validate imported image assets. Room asset access follows the participant's current scene and perspective; private speech is shown only to its audience.

## Create new assets

The source checkout includes a versioned Roleplay Avatar worker. Its bundled executor uses GPUQ and explicit model environments from `configs/avatar.local.json`; start with [the example](../../configs/avatar.example.json). It needs the upstream image/vision/face/voice creation dependencies, configured model directories and compatible Python interpreters. See [Roleplay Avatar](https://github.com/Toyhom/RoleplayAvatar) for those model services and their terms.

This worker is an optional source integration. For another scheduler or a remote creation service, inject `avatar_factory(store)` in `create_app`; the host owns executor startup and resources. Independently installed backends can serve imported finished assets without launching the source worker.

Creation accepts PNG, JPEG and WebP references, at least 128 pixels on each side, at most 24 million pixels and 10 MB. Stable request IDs recover existing jobs. Packages publish only after contract/asset validation. The stage uses the committed story dialogue; character generation and rendering have independent job/state lifecycles.

The current stage is a WebGL portrait renderer with silent subtitle performance. Voice playback, phoneme synchronization and native Cubism rendering require separate presentation integrations. Adapter provenance and MIT terms are in [vendor/avatar_worker](../../vendor/avatar_worker/ADAPTER.md).
