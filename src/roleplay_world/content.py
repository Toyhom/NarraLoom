"""Editable world/story definitions and deterministic compilation to playable worlds."""

from typing import Annotated, Literal

from pydantic import Field, create_model

from .content_preferences import PRESETS, CreationPreset, LanguageChoice, LanguageTag, content_text
from .contracts import Contract, DomainError, Identifier
from .rulepacks import RuleSet, attach_rules, validate_rules
from .simulation import SimulationConfig, validate_simulation
from .state_rules import StateRules, compile_packs, validate_authoring, validate_pack

Text = Annotated[str, Field(min_length=1, max_length=600)]
Name = Annotated[str, Field(min_length=1, max_length=60)]
Index = Annotated[int, Field(ge=0, le=63)]


class Place(Contract):
    name: Name
    description: Text
    connects_to: Annotated[list[Index], Field(max_length=23)]


class Character(Contract):
    name: Name
    role: Name
    personality: Text
    goal: Text
    boundary: Text
    location: Index
    secret: Text
    avatar_id: Identifier | None = None


class WorldBlueprint(Contract):
    content_language: LanguageTag = "zh-CN"
    creation_preset: CreationPreset = "adventure"
    title: Name
    genre: Name
    tone: Name
    premise: Text
    setting: Text
    locations: Annotated[list[Place], Field(min_length=1, max_length=24)]
    characters: Annotated[list[Character], Field(min_length=1, max_length=32)]
    rules: RuleSet | None = None
    simulation: SimulationConfig | None = None
    state_rules: StateRules | None = None


class Clue(Contract):
    title: Name
    text: Text
    location: Index
    known_by: Annotated[list[Index], Field(max_length=32)] = Field(default_factory=list)


class Challenge(Contract):
    title: Name
    description: Text
    location: Index
    required_clues: Annotated[list[Index], Field(max_length=16)] = Field(default_factory=list)
    skill: Literal["observation", "persuasion", "agility", "craft", "none"] = "none"
    difficulty: Annotated[int, Field(ge=1, le=100)] = 8
    success: Text
    ending: bool = False
    reward_coins: Annotated[int, Field(ge=0, le=1000)] = 0
    reward_xp: Annotated[int, Field(ge=0, le=1000)] = 0


class StoryBlueprint(Contract):
    content_language: LanguageTag | None = None
    creation_preset: CreationPreset | None = None
    opening_suggestions: Annotated[list[Annotated[str, Field(min_length=1, max_length=160)]], Field(max_length=6)] = Field(default_factory=list)
    state_rules: StateRules | None = None
    title: Name
    synopsis: Text
    player_role: Name
    opening: Text
    start_location: Index
    starting_item: Annotated[str, Field(max_length=60)] = ""
    acts: Annotated[list[Text], Field(min_length=1, max_length=12)]
    clues: Annotated[list[Clue], Field(max_length=40)]
    challenges: Annotated[list[Challenge], Field(max_length=24)]
    pressure_name: Annotated[str, Field(max_length=60)] = ""
    pressure_event: Annotated[str, Field(max_length=600)] = ""


class CreateWorld(Contract):
    request_id: Identifier | None = None
    content_language: LanguageChoice = Field(default="auto", description="BCP-47 content language; auto follows the creative brief, independently of UI language.")
    creation_preset: CreationPreset = Field(default="adventure", description="Initial generation size: scene 1 location/1 NPC, story 3/2, adventure 4/3. Editing can expand any preset.")
    prompt: Annotated[str, Field(min_length=5, max_length=2500)]
    story_prompt: Annotated[str, Field(max_length=1800)] = ""
    rules_mode: Literal["none", "story-lite", "d20", "d100"] = "none"
    living_world: bool = False
    custom_states: bool = False
    avatar_id: Identifier | None = None


class CreateStory(Contract):
    request_id: Identifier | None = None
    content_language: LanguageChoice | None = None
    creation_preset: CreationPreset | None = None
    prompt: Annotated[str, Field(min_length=5, max_length=2500)]
    custom_states: bool = False


class EditWorld(Contract):
    expected_revision: int
    content: WorldBlueprint


class EditStory(Contract):
    expected_revision: int
    content: StoryBlueprint


class RepairStory(Contract):
    expected_revision: Annotated[int, Field(strict=True, ge=1)]


def story_generation_schema(world, preset=None, language=None):
    """Constrain references before the model runs, using the selected creation scale."""
    preset = preset or world.creation_preset
    size = PRESETS[preset]
    language = language or world.content_language
    loc = Literal[tuple(range(len(world.locations)))]
    actor = Literal[tuple(range(len(world.characters)))]
    clue = create_model(
        "SceneClue", __base__=Clue, location=(loc, ...),
        known_by=(list[actor], Field(default_factory=list, max_length=len(world.characters))),
    )
    clue_ref = Literal[tuple(range(size["clues"]))] if size["clues"] else int
    challenge = create_model(
        "SceneChallenge", __base__=Challenge, location=(loc, ...),
        required_clues=(list[clue_ref], Field(default_factory=list, max_length=size["clues"])),
    )
    ending = create_model(
        "EndingChallenge", __base__=challenge, skill=(Literal["none"], "none"), ending=(Literal[True], True)
    )
    fields = {
        "content_language": (LanguageTag, ...) if language == "auto" else (Literal[language], language),
        "creation_preset": (Literal[preset], preset),
        "state_rules": (type(None), None),
        "start_location": (loc, ...),
        "clues": (list[clue], Field(min_length=size["clues"], max_length=size["clues"])),
        "challenges": (tuple[challenge, ending], ...) if size["challenges"] else (list[challenge], Field(max_length=0)),
    }
    if preset == "scene":
        fields.update({key: (Literal[""], "") for key in ("starting_item", "pressure_name", "pressure_event")})
    return create_model("SceneStoryBlueprint", __base__=StoryBlueprint, **fields)


def world_generation_schema(preset="adventure", language="auto"):
    # The engine supplies a connected initial route network. Authors can edit it later.
    size = PRESETS[preset]
    place = create_model(
        "GeneratedPlace", __base__=Place, connects_to=(list[int], Field(default_factory=list, max_length=0))
    )
    character = create_model("GeneratedCharacter", __base__=Character,
                             location=(Literal[tuple(range(size["locations"]))], ...), avatar_id=(type(None), None))
    return create_model(
        "GeneratedWorld", __base__=WorldBlueprint,
        content_language=(LanguageTag, ...) if language == "auto" else (Literal[language], language),
        creation_preset=(Literal[preset], preset),
        rules=(type(None), None), simulation=(type(None), None), state_rules=(type(None), None),
        locations=(list[place], Field(min_length=size["locations"], max_length=size["locations"])),
        characters=(list[character], Field(min_length=size["characters"], max_length=size["characters"])),
    )


def connect_generated_world(world):
    for i, place in enumerate(world.locations):
        place.connects_to = [j for j in (i - 1, i + 1) if 0 <= j < len(world.locations)]
    validate_world(world)


def validate_world(world):
    n = len(world.locations)
    validate_rules(world.rules, n, len(world.characters))
    validate_simulation(world.simulation, n, len(world.characters))
    validate_authoring(world)
    for i, p in enumerate(world.locations):
        if any(x >= n or x == i for x in p.connects_to):
            raise DomainError("invalid_content", "地点连接必须指向其他现有地点，编号从 0 开始", 422)
    if len({p.name for p in world.locations}) != n:
        raise DomainError("invalid_content", "地点名称不能重复", 422)
    if len({a.name for a in world.characters}) != len(world.characters):
        raise DomainError("invalid_content", "人物名称不能重复", 422)
    if any(a.location >= n for a in world.characters):
        raise DomainError("invalid_content", "人物必须位于现有地点", 422)
    reached = {0}
    while True:
        more = reached | {j for i, p in enumerate(world.locations) for j in p.connects_to if i in reached}
        more |= {i for i, p in enumerate(world.locations) if reached.intersection(p.connects_to)}
        if more == reached:
            break
        reached = more
    if len(reached) != n:
        raise DomainError("invalid_content", "所有地点必须连通，不能生成无法到达的区域", 422)


def validate_story(world, story):
    validate_world(world)
    validate_authoring(world, story)
    if not world.rules and any(c.reward_coins or c.reward_xp for c in story.challenges):
        raise DomainError("invalid_content", "金币与经验奖励需要在世界中启用冒险规则", 422)
    locations = [story.start_location, *[c.location for c in story.clues], *[c.location for c in story.challenges]]
    if any(i >= len(world.locations) for i in locations):
        raise DomainError("invalid_content", "故事地点编号超出世界范围", 422)
    if any(i >= len(world.characters) for c in story.clues for i in c.known_by):
        raise DomainError("invalid_content", "线索知情人编号不存在", 422)
    if any(i >= len(story.clues) for c in story.challenges for i in c.required_clues):
        raise DomainError("invalid_content", "目标引用的线索不存在", 422)
    if bool(story.pressure_name) != bool(story.pressure_event):
        raise DomainError("invalid_content", "局势时钟名称与事件须同时填写或同时留空", 422)
    if not story.challenges:
        return
    if not any(c.ending for c in story.challenges):
        raise DomainError("invalid_content", "至少一个目标需要 ending=true，提供可达的故事结局", 422)
    if not any(c.ending and c.skill == "none" for c in story.challenges):
        raise DomainError(
            "invalid_content", "至少提供一条不依赖随机掷骰的结局路线（ending=true, skill=none）", 422
        )


def compile_story(world, story, story_id, revision=1, origin=None):
    validate_story(world, story)
    language = story.content_language or world.content_language
    preset = story.creation_preset or world.creation_preset
    def text(zh, en):
        return content_text(language, zh, en)
    locations = []
    for i, p in enumerate(world.locations):
        neighbors = set(p.connects_to) | {j for j, q in enumerate(world.locations) if i in q.connects_to}
        locations.append(
            {
                "id": f"loc_{i}",
                "name": p.name,
                "description": p.description,
                "exits": [{"to": f"loc_{j}", "travel_time_s": 120} for j in sorted(neighbors)],
            }
        )
    player = {
        "id": "pc_traveler",
        "name": text("旅人", "Traveler"),
        "control": "player",
        "persona": {"background": story.player_role},
        "goals": [story.synopsis],
        "boundaries": [text("玩家自行决定行动", "The player chooses their own actions")],
        "initial_knowledge": ["fact_setting"],
        "initial_state": {
            "location_id": f"loc_{story.start_location}",
            "resources": {} if preset == "scene" and not world.rules else {"coins": 8, "vitality": 10},
            "skills": {"observation": 2, "persuasion": 2, "craft": 2, "agility": 2},
        },
    }
    facts = [{"id": "fact_setting", "value": world.setting, "visibility": {"kind": "public"}}]
    actors = [player]
    for i, c in enumerate(world.characters):
        aid, fid = f"npc_{i}", f"fact_secret_{i}"
        facts.append({"id": fid, "value": c.secret, "visibility": {"kind": "actors", "actor_ids": [aid]}})
        actors.append(
            {
                "id": aid,
                "name": c.name,
                "control": "npc",
                "public_description": c.role,
                **({"avatar_id": c.avatar_id} if c.avatar_id else {}),
                "persona": {"personality": c.personality},
                "goals": [c.goal],
                "boundaries": [c.boundary],
                "initial_knowledge": ["fact_setting", fid],
                "initial_state": {"location_id": f"loc_{c.location}", "resources": {"coins": 5}},
            }
        )
    for i, clue in enumerate(story.clues):
        fid = f"fact_clue_{i}"
        facts.append(
            {
                "id": fid,
                "name": clue.title,
                "value": clue.text,
                "visibility": {"kind": "actors", "actor_ids": [f"npc_{j}" for j in clue.known_by]},
                "discoverable_at": [f"loc_{clue.location}"],
                "requires_check": False,
            }
        )
        for j in clue.known_by:
            actors[j + 1]["initial_knowledge"].append(fid)
    if story.pressure_name:
        facts.append({
            "id": "fact_pressure",
            "value": "pending",
            "value_labels": {"arrived": story.pressure_event},
            "visibility": {"kind": "gm_only"},
        })
    challenges = [
        {
            "id": f"challenge_{i}",
            "quest_id": f"quest_{i}",
            "name": c.title,
            "description": c.description,
            "location_id": f"loc_{c.location}",
            "required_facts": [f"fact_clue_{j}" for j in c.required_clues],
            "skill": c.skill,
            "difficulty": c.difficulty,
            "success": c.success,
            "ending": c.ending,
            "reward_coins": c.reward_coins,
            "reward_xp": c.reward_xp,
        }
        for i, c in enumerate(story.challenges)
    ]
    template = {
        "schema_version": "0.2.0",
        "content_language": language,
        "creation_preset": preset,
        "id": story_id,
        "version": str(revision),
        "title": story.title,
        "world_title": world.title,
        "player_role": story.player_role,
        "premise": story.synopsis,
        "opening": story.opening,
        "opening_suggestions": story.opening_suggestions or [text("我仔细观察周围，寻找线索。", "I look around carefully."), text("我向在场的人打听这里的情况。", "I ask the people here about this place.")],
        "locations": locations,
        "actors": actors,
        "facts": facts,
        "items": [{"id": "item_start", "name": story.starting_item, "quantity": 1, "holder_id": "pc_traveler"}] if story.starting_item else [],
        "relations": [],
        "hooks": [
            {"id": c["quest_id"], "name": c["name"], "description": c["description"], "status": "available"}
            for c in challenges
        ],
        "clocks": [
            {
                "id": "clock_pressure",
                "name": story.pressure_name,
                "kind": "time",
                "value": 0,
                "threshold": 6,
                "interval_s": 600,
                "visibility": {"kind": "public"},
            }
        ] if story.pressure_name else [],
        "mechanics": {
            "challenges": challenges,
            "escape_routes": {},
            "thresholds": [{"clock_id": "clock_pressure", "fact_id": "fact_pressure", "value": "arrived"}] if story.pressure_name else [],
        },
        "outline": list(story.acts),
        "provenance": {"kind": "community_adaptation", **origin} if origin else {"kind": "generated_and_reviewable"},
    }
    if world.simulation:
        template["mechanics"]["simulation"] = world.simulation.model_dump()
    attach_rules(template, world.rules)
    if world.state_rules or story.state_rules:
        cfg = compile_packs(world.state_rules, story.state_rules)
        validate_pack(cfg, template)
        template["mechanics"]["state_rules"] = cfg
    return template
