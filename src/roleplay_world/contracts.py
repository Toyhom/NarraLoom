"""Versioned, bounded commands and model outputs. No executable model content."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")]
ShortText = Annotated[str, Field(min_length=1, max_length=1800)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewCampaign(Contract):
    request_id: Identifier | None = None
    template_id: Identifier = "world_fogharbor"
    story_id: Identifier | None = None
    player_name: Annotated[str, Field(min_length=1, max_length=32)] = "旅人"
    source_campaign_id: Identifier | None = None
    source_branch_id: Identifier | None = None
    source_world_version: Annotated[int, Field(ge=0)] | None = None


class ActionCommand(Contract):
    schema_version: Literal["0.1.0"] = "0.1.0"
    action_id: Identifier
    expected_world_version: Annotated[int, Field(ge=0)]
    mode: Literal["act", "say", "wait", "ooc"] = "act"
    text: ShortText
    actor_id: Identifier | None = None
    whisper_to: Identifier | None = None
    selected_operation: "Operation | None" = None
    note_record: "NoteRecord | None" = None
    simulation_control: Literal["pause", "resume"] | None = None
    trade: "TradeCommand | None" = None


class TradeItem(Contract):
    item_id: Identifier
    quantity: Annotated[int, Field(strict=True, ge=1, le=9999)] = 1


class TradeCommand(Contract):
    kind: Literal["propose", "counter", "accept", "decline", "withdraw"]
    target_id: Identifier | None = None
    offer_id: Identifier | None = None
    items: Annotated[list[TradeItem], Field(max_length=6)] = Field(default_factory=list)
    coins: Annotated[int, Field(strict=True, ge=0, le=999999)] = 0
    request_coins: Annotated[int, Field(strict=True, ge=0, le=999999)] = 0


class NoteRecord(Contract):
    id: Identifier
    text: Annotated[str, Field(min_length=1, max_length=1800)]
    kind: Literal["note", "commitment"] = "note"
    status: Literal["open", "done", "archived"] = "open"
    source_event_ids: Annotated[list[Identifier], Field(max_length=12)] = Field(default_factory=list)


class ForkRequest(Contract):
    source_branch_id: Identifier
    world_version: Annotated[int, Field(ge=0)]
    title: Annotated[str, Field(min_length=1, max_length=40)] = "新的选择"


class Operation(Contract):
    """Small interpreted vocabulary. Each variant is validated again against world state."""

    kind: Literal["move", "give", "reveal", "repair", "escape", "challenge",
                  "take", "use", "equip", "unequip", "buy", "sell", "attack", "rest", "recover", "recruit", "dismiss", "state_action"]
    target_id: Identifier
    item_id: Identifier | None = None
    when: Literal["always", "success", "failure"] = "always"
    quantity: Annotated[int, Field(ge=1, le=99)] = 1


class Check(Contract):
    skill: Literal["observation", "persuasion", "agility", "craft"]
    difficulty: Annotated[int, Field(ge=1, le=100)]
    purpose: Annotated[str, Field(min_length=1, max_length=120)]


class TurnPlan(Contract):
    intent: Annotated[str, Field(min_length=1, max_length=240)]
    time_cost_s: Annotated[int, Field(ge=0, le=1800)] = 60
    operations: Annotated[list[Operation], Field(max_length=5)] = []
    check: Check | None = None
    speakers: Annotated[list[Identifier], Field(max_length=2)] = []


class ActorReply(Contract):
    reaction: Literal["accept", "refuse", "none"] = Field(default="none", description="先决定是否接受本轮 offered_items；accept=愿意接收，refuse=明确拒绝，none=无物品交易。text 必须与该决定一致。")
    text: Annotated[str, Field(min_length=1, max_length=600)]
    reveal_fact_ids: Annotated[list[Identifier], Field(max_length=2)] = []
    emotion: Literal["neutral", "happy", "sad", "angry", "soft"] = "neutral"
    gesture: Literal["none", "nod", "shake_head", "tilt", "bow", "lean_forward", "lean_back", "sway", "bounce"] = "none"


class Narration(Contract):
    text: Annotated[str, Field(min_length=1, max_length=1800)]
    suggestions: Annotated[list[Annotated[str, Field(min_length=1, max_length=80)]], Field(max_length=3)] = []


class Segment(Contract):
    kind: Literal["narration", "dialogue", "rule_result", "note"]
    text: str
    speaker_id: str | None = None
    speaker_name: str | None = None


class DomainError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


ActionCommand.model_rebuild()
