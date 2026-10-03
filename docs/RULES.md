# Adventure rules

Choose narrative-only, `story-lite`, `d20` or `d100` during world creation. With rules enabled, the generator designs items, starting equipment, shops, modest enemies and potential companions. The editor exposes their values. New stories pin the selected world revision; existing campaigns retain their original rules.

The engine owns coins, health, stamina, experience, item quantities, equipment slots and shop inventory. Models propose legal operations and NPC acceptance/refusal. UI buttons submit explicit operations; free text lets the planner interpret intent.

- **d20:** attacks roll 1d20 plus the attack modifier against enemy defense. Weapons add damage, armor adds defense, and a surviving enemy makes one counterattack.
- **d100:** attacks succeed when 1d100 is at most `percentile_skill`. Enemy counterattacks have a base 55% chance, reduced by 5 percentage points per armor point, with a 5% floor. For ordinary story checks, difficulty represents the success percentage.
- **story-lite:** equipment and combat use the d20 mechanics. These are lightweight rules; complete classes, spells, initiative rounds and tactical combat need a separate extension.
- Defeated enemies leave the legal attack set. Objective and combat rewards are awarded once. Repeating or failing an objective cannot collect its completion reward.
- Rest requires a location without a living enemy, consumes 30 minutes of game time and restores health/stamina. At zero health, healing costs up to three coins and returns the party to the starting location. Game time still advances.
- Companions join only after NPC acceptance, follow movement and can leave the party. They provide scene interaction; party combat and loot distribution are separate extensions.

Buying, selling and picking up items support quantities. Equipped items must be unequipped before sale. Consumables require a relevant resource deficit.

Content validation checks references, trade conservation, equipment, consumables, single-round enemy combat, replay and refusal to join. Isolated rule fixtures validate mechanics; actual-model story routes add planner/character coverage. Assess balance across your intended starting configurations and player choices.

```bash
python -m pytest -q tests/test_rulepacks.py
python scripts/check_rules_browser.py --system d20 --output outputs/validation/rules-d20
python scripts/check_rules_browser.py --system d100 --output outputs/validation/rules-d100
```

Browser checks generate a world through the form, then exercise editing, equipment, shops, companionship, travel, combat, consumables, rest, branching, refresh and mobile layout against the real API. Inspect failed reports when generated values cannot support the chosen route.
