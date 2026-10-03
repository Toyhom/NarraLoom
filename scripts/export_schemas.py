"""Generate public output contracts from the actual Python models."""
import json
from pathlib import Path

from roleplay_world.avatars import AvatarCreate
from roleplay_world.content import (
    CreateStory,
    CreateWorld,
    EditStory,
    EditWorld,
    RepairStory,
    StoryBlueprint,
    WorldBlueprint,
)
from roleplay_world.contracts import ActionCommand, ActorReply, ForkRequest, Narration, NewCampaign, TurnPlan
from roleplay_world.decisions import DecisionRequest
from roleplay_world.imports import ConvertRequest
from roleplay_world.packages import PackageBuild, PackageInstall, PackageManifest, PackageVisibility
from roleplay_world.rooms import RoomAction, RoomControl, RoomCreate, RoomJoin
from roleplay_world.rulepacks import RuleSet
from roleplay_world.settings import ProviderSettings
from roleplay_world.simulation import SimulationConfig
from roleplay_world.state_rules import StateRules

root = Path(__file__).resolve().parents[1] / "schemas"
root.mkdir(exist_ok=True)
models = [PackageBuild, PackageInstall, PackageManifest, PackageVisibility, ConvertRequest, DecisionRequest, ActionCommand, ActorReply, ForkRequest, Narration, NewCampaign, TurnPlan,
          CreateStory, CreateWorld, EditStory, EditWorld, RepairStory, StoryBlueprint, WorldBlueprint, AvatarCreate, ProviderSettings, RoomCreate, RoomJoin, RoomControl, RoomAction, RuleSet, SimulationConfig, StateRules]
for model in models:
    (root / (model.__name__ + ".schema.json")).write_text(
        json.dumps(model.model_json_schema(), ensure_ascii=False, indent=2) + "\n")
print(f"Exported {len(models)} schemas")
