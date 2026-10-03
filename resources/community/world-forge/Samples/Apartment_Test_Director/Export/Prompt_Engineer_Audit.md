# Prompt Engineer Audit — Apartment 5C (sandbox, Director-voiced)

Preset: `Apartment5C_ChatPreset.json`. World Mode: **sandbox**. Cast: one World Director
card voicing three lorebook-only NPCs (Priya Anand, Theo Walsh, Nadia Okonkwo) +
`{{user}}` persona (Sam). Wholesome slice-of-life.

## Block Selection Rationale

| Block | State | Why |
|---|---|---|
| `main` | enabled | Engine half of the override contract; world-/character-agnostic. |
| `deep_think` | enabled | Sandbox-flavored — `SANDBOX_STATE` / `WORLD_PULSE`, no arc naming. |
| `arc_guardian` | **disabled** | Sandbox — no arcs. |
| `lore_integration` | enabled | Anti-recitation; apartment-specific anchors. |
| `spatial_awareness` | enabled | Ensemble scenes; includes the three roommates' heights. |
| `sensory_embodiment` | enabled (**weighted high**) | Sandbox emphasis (standing world must stay physically present). |
| `formatting` | enabled | Defers to `<style_contract>`; no marker chars. |
| `nsfw` | **disabled** | Wholesome; §8 out of scope. |
| `multi_character_dynamics` | **enabled** | A Director/Narrator card managing NPCs meets the enable criterion; Director-voiced lattice example. |
| `npc_ensemble` | **enabled** | **Sandbox default** + Director-voiced lorebook roster — carries NPC-to-NPC dialogue, ensemble prose scaling, and organic enrichment (the lorebook-cast complement to Multi-Character Dynamics). |
| `enhanceDefinitions` | disabled | `{{char}}` is the Director (not a real character); enriching it is not meaningful — `npc_ensemble` covers the roster instead. |
| `jailbreak` | enabled | Verbatim 4-clause frame; no NSFW closing affirmation. |

## Style Contract (would-be Master Design §11a)
- World default perspective: **third person**, **past** tense, limited. Markers: narration *asterisks*, dialogue "double quotes", emphasis **double asterisks**.
- Paragraph register: standard (mixed lengths).
- `is_multi_perspective: false` (single card), `is_multi_tense: false` → **no ACTIVE-SPEAKER RULE**.
- **The World Director card overrides** the world default to **third-person omniscient** via its `<style_override>` (the `world_forge.style_override` block on the card) — this is the intended demonstration of the override architecture: the world default is limited, the Director needs omniscient to narrate across all NPC interiors.

## Pass 1 — engine/world purity (PASS)
- Main Prompt contains no character / arc / faction / location names. ✓
- `<style_contract>` present; perspective + tense + markers only. ✓
- Formatting block contains no literal marker characters. ✓
- Jailbreak world-/character-agnostic; NSFW affirmation omitted. ✓

## Pass 2 — override pairing (PASS)
- Director card's `system_prompt` and `post_history_instructions` begin with `{{original}}`. ✓
- Director card's `<style_override>` (perspective `third_omniscient` + directive + rationale) **structurally mirrors** the `<style_contract>` shape (perspective/tense/marker keys). ✓

## Manual-application items (§7/§8)
None outstanding. `reasoning_effort` set to `high`.
