# Optional 2D NPC presentation

Bind a ready avatar to a world character or select one while creating the world. When that NPC shares the player's scene, the reference frontend displays a deformable portrait with breathing, blinking, expressions, gestures and text-paced mouth movement. Committed dialogue drives silent subtitles. The player can collapse or replay the stage.

The portable format is `deformable-portrait` version 3 with `source-lip-warp-v3` binding. Native world packages can include the render subset: portrait, mouth atlas and rig. Install `.[avatar]` to validate imported image assets. Room asset access follows the participant's current scene and perspective; private speech is shown only to its audience.

## Create new assets

The source checkout includes a versioned Roleplay Avatar worker with `local` (Linux/WSL2) and `gpuq` runners. [The setup guide](../avatars.md) covers platform choices, pinned model downloads, HF mirrors and four isolated creation environments. Start from [the example configuration](../../configs/avatar.example.json), or run `narraloom models configure avatar-2d`. `narraloom models check` checks configured paths.

The required roles are `vision`, `image`, `voice_design`, `face_landmarker` and `segmentation`. `configs/avatar-models.local.json` maps each role to a path, repository and revision; `configs/avatar.local.json` selects interpreters, model configuration and runner. `AVATAR_IMAGE_BACKEND=flux2` uses FLUX; `qwen_image_edit` selects Qwen-Image-Edit for portrait expansion. Download that optional checkpoint separately and set the `image_edit` path. Mouth generation still requires FLUX. Model replacement must retain the selected worker adapter's model/pipeline interface.
This worker is an optional source integration. For another scheduler or a remote creation service, inject `avatar_factory(store)` in `create_app`; the host owns executor startup and resources. Independently installed backends can serve imported finished assets without launching the source worker.

Creation accepts PNG, JPEG and WebP references, at least 128 pixels on each side, at most 24 million pixels and 10 MB. Stable request IDs recover existing jobs. Packages publish only after contract/asset validation. The stage uses the committed story dialogue; character generation and rendering have independent job/state lifecycles.

The current stage is a WebGL portrait renderer with silent subtitle performance. Voice playback, phoneme synchronization and native Cubism rendering require separate presentation integrations. Adapter provenance and MIT terms are in [vendor/avatar_worker](../../vendor/avatar_worker/ADAPTER.md).
