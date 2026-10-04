# Create worlds and stories

[English](creators.md) · [简体中文](zh-CN/creators.md) · [日本語](ja/creators.md)

A **world** defines shared places, characters and world-level mechanics. A **story** adds a player role, opening, clues, objectives and an outline within one world revision. A **campaign** is a player's saved playthrough of a compiled story.

## Choose a scale

| Preset | Starting shape | Useful for |
| --- | --- | --- |
| `scene` | One place, one NPC, lightweight interaction | Conversation games, intimate scenes, character studies |
| `story` | Three places, two NPCs | Short investigations and interactive stories |
| `adventure` | Four places, three NPCs | Exploration and tabletop-style play |

The editor supports larger authored settings. Choose the content language independently of the interface. Stories can use a different language from their world's source text; model ability determines language quality.

Describe the setting, recurring characters and tone. Add the first story idea or let the generator propose it. Optional toggles add game rules, custom state, a living world or an important NPC's 2D avatar. You can start with a small scene and add mechanics later.

## Optional animated portraits

Characters receive their personality, goals, knowledge and dialogue through the text model. In world creation, **Add an animated 2D portrait (optional)** starts unchecked. Leave it off for text play, or enable it to choose a finished portrait or submit a reference image. New image generation needs the separate [creator setup](avatars.md). You can also add or remove a portrait later in the world’s character editor.

## Edit and test

Generation saves editable drafts. Check the opening, player identity, map connections, NPC knowledge and intended outcomes. The story's test report combines structural validation, deterministic rule routes, opening/mechanics review and model playtests in isolated saves.

Edit failed content or use **AI revision and retest** to request a new revision and review its text changes. Every test result belongs to its exact revision. Existing campaigns keep their original compiled content when you edit a world or story.

[State rules](reference/state-rules.md) define integers, switches, phases, conditions, actions and triggers. Include executable acceptance routes for all declared actions/triggers. [Game rules](reference/rules.md) covers equipment, trading, lightweight combat and d20/d100 checks. Automatic tests cover the declared routes; explore alternate player choices yourself for narrative quality.

## Create another story

Open an existing world and provide a new premise. Each story pins a world revision. You can begin independently or carry eligible consequences from a previous campaign in the same world revision. World-level state can persist while story-specific clues, clocks and one-time triggers start fresh.

## Share and reuse

Build a native `.narraloom.zip` from up to eight tested stories in one world revision. Add a title, author credit, distribution terms and a spoiler-free summary. Optionally include ready 2D portrait assets. Download the package, share an unlisted link or list it on your server's shelf.

Recipients choose stories, install editable copies and run tests with their own models. Package content includes creator text and GM secrets, so use **player notes export** when sharing only a playthrough's visible story. Full campaign backups serve a separate restoration workflow.

Character-card JSON/PNG, CHARX and world books have a basic import-and-review path. Review the conversion report, especially unsupported scripts and mechanics. Native packages preserve the framework's own typed content. See [package reference](reference/community-packages.md) and [starter attribution](reference/community-content.md).
