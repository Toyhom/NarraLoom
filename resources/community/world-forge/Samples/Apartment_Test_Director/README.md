# Apartment Director Test — World Director + lorebook-only NPCs

The companion to `Samples/Apartment_Test/`. Same premise, **opposite cast topology**, so
the two together cover both ways the NPC Memory Manifest is consumed:

| | `Apartment_Test` | `Apartment_Test_Director` (this one) |
|---|---|---|
| Controller | none — 2 AI-played roommate **cards** | one **World Director card** (the "char controller") |
| NPCs | live as character cards | live **only in the lorebook** (no per-NPC cards) |
| Manifests | one per character lorebook (2 files) | **one aggregated manifest**, 3 npcs in a single lorebook |
| Tests | card-backed characters → npcs | lorebook-only NPCs → npcs (the manifest's core job) |

**Premise:** Flat 5C, a four-person share. `{{user}}` (**Sam**) lives with three roommates,
all voiced by the single World Director card:
- **Priya Anand** — 25, med student; clipped, sardonic, clinical.
- **Theo Walsh** — 23, barista/musician; gentle, trailing, musical.
- **Nadia Okonkwo** — 28, freelance designer who runs the house; blunt, deadpan, declarative.

No plot, no arcs — sandbox.

## Files (`Export/`)

| File | Role | Carries a manifest? |
|---|---|---|
| `WorldDirector_Card.json` | The controller card — narrates + voices all 3 NPCs (`style_override` = third-omniscient) | — (cards never carry manifests) |
| `Apartment_World_Lorebook.json` | Tier 1 — setting (position 0) | No |
| `Apartment_NPC_Lorebook.json` | Tier 2 — **all 3 NPCs aggregated** (`NPC — Name (Facet)`) | **Yes** — one manifest, 3 npcs |
| `Sandbox_Lorebook.json` | Tier 3 — `SANDBOX_STATE` + `WORLD_PULSE` | No |
| `Apartment5C_ChatPreset.json` | Chat Completion Preset (Prompt Engineer output) | — |
| `Prompt_Engineer_Audit.md` | Block-selection rationale + Pass 1/2 results | — |
| `User.md` | `{{user}}` persona (Sam) | — |

> **Preset.** `Apartment5C_ChatPreset.json` is a **sandbox** preset and the counterpart
> to sample 1's: `arc_guardian` and `nsfw` disabled, `multi_character_dynamics` enabled,
> and — the key difference — **`npc_ensemble` enabled** (the sandbox default for a
> Director-voiced lorebook roster: NPC-to-NPC dialogue, ensemble prose scaling, organic
> enrichment). The world-default perspective is third-limited; the World Director card
> **overrides** it to third-omniscient via its `<style_override>` — the intended
> demonstration of the override contract. See `Prompt_Engineer_Audit.md`.

## The aggregated manifest

`Apartment_NPC_Lorebook.json` holds all three roommates as `NPC — Name (Facet)` entries
(uids 0–12) and **one** `[[NPC_MANIFEST]]` entry (uid 13) covering the whole cast:

```jsonc
{
  "schema": 1,
  "lorebook": { "name": "Apartment 5C — NPCs", "kind": "npc" },
  "personas": { "user": { "name": "Sam", "aliases": ["Sam", "{{user}}"] } },
  "npcs": [
    { "id": "priya_anand",  "facets": { "physical": 0, "psychological": 1, "standingGoal": 2 },
      "relationships": [{ "to": "theo_walsh",    "kind": "roommate", "note": "..." }] },
    { "id": "theo_walsh",   "facets": { "physical": 4, "psychological": 5, "standingGoal": 6 },
      "relationships": [{ "to": "nadia_okonkwo", "kind": "roommate", "note": "..." }] },
    { "id": "nadia_okonkwo","facets": { "physical": 8, "psychological": 9, "standingGoal": 10 },
      "relationships": [{ "to": "priya_anand", ... }, { "to": "theo_walsh", ... }] }
  ]
}
```

**Expected stable ids:** `priya_anand`, `theo_walsh`, `nadia_okonkwo` (persona `Sam`).
The three relationship edges form a small connected graph (Priya→Theo, Theo→Nadia,
Nadia→Priya & Nadia→Theo).

This is the **aggregated** form — the `^NPC —` comment convention the extension's prose
fallback also recognizes, with the manifest making facets/relationships explicit.

## How to set it up in SillyTavern

1. **Import the card** `WorldDirector_Card.json` (this is the single character you chat with).
2. **Import the lorebooks**: `Apartment_World_Lorebook`, `Apartment_NPC_Lorebook`,
   `Sandbox_Lorebook`. Link them to the World Director card (or set them as active world
   info) so they load in the chat.
3. **Persona:** create a persona named **Sam**, paste `User.md`, activate it.
4. **Preset:** import `Apartment5C_ChatPreset.json` as a Chat Completion preset and select it.
5. Start a normal (single-character) chat with the World Director and let the flat run.

## How to verify the NPC Memory extension

- The `[[NPC_MANIFEST]]` entry is **disabled** — confirm it never enters the prompt.
- The extension should discover **three npcs** (`priya_anand`, `theo_walsh`,
  `nadia_okonkwo`) from a **single** lorebook, plus the persona `Sam` — keyed by id.
- This is the important case the manifest exists for: these NPCs have **no character
  card**, so without the manifest the extension would have to prose-parse them. Confirm
  all three are found and attributed even though none is a card.
- `facets` should resolve to the right entries; the relationship graph should resolve in
  all directions.
- Re-export / re-import and confirm the three ids are unchanged (UIDs may renumber).
- Turn tags are consumer-owned (contract §7) — nothing emitted here.

## Notes

- **Sandbox** → manifests have **no `scenes[]`** (no arc `BEAT —` entries).
- No `Group_Lorebook.json` — consolidated group lorebook is deprecated (#40); the
  aggregated NPC lorebook already gives a single manifest for the whole cast.
- Three voices kept deliberately far apart (clinical / musical / declarative) so the
  Voice Auditor's distinctiveness lens and any consumer-side attribution have an easy
  target.
- Illustrative test scaffolding, not a showcase world.
