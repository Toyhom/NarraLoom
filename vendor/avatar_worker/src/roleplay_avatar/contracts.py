"""Versioned internal contracts. These are not the native DLP3D wire format."""

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")]
Stream = Literal["audio", "motion", "face"]
Intent = Literal[
    "idle",
    "long_idle",
    "listen",
    "think",
    "speak",
    "acknowledge",
    "explain",
    "uncertain",
    "alert",
    "leave",
    "error",
]
STATES = {
    "idle",
    "long_idle",
    "listen",
    "think",
    "speak",
    "acknowledge",
    "explain",
    "uncertain",
    "alert",
    "leave",
    "error",
}


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Profile(Contract):
    schema_version: Literal["0.1.0"] = "0.1.0"
    character_id: Identifier
    display_name: str
    persona: str
    package_status: Literal["template_only", "asset_candidate", "validated"] = "template_only"
    model: str | None = "model.glb"
    display_rotation_y_deg: float = Field(default=0, ge=-360, le=360)
    display_height_m: float = Field(default=2.05, gt=0, le=10)
    renderer_2d: Literal["portrait", "cubism"] = "portrait"
    live2d_model: str | None = None
    live2d_parameter_map: dict[str, str] = Field(default_factory=dict)
    native_animation_map: dict[str, str] = Field(default_factory=dict)
    presentation_modes: list[Literal["3d", "2d"]] = Field(
        default_factory=lambda: ["3d"], min_length=1, max_length=1
    )


class Capabilities(Contract):
    body_topology: Literal["humanoid", "quadruped", "multiped", "serpentine", "custom"]
    face_mode: Literal["blendshape", "bone_face", "jaw_only", "none"]
    eye_mode: Literal["none", "paired", "custom"] = "none"
    appendages: list[str] = Field(default_factory=list)
    controller: Literal["humanoid", "creature"]
    motion_mode: Literal["native_clips", "retargeted_clips", "procedural"]
    active_streams: list[Stream]

    @model_validator(mode="after")
    def valid_streams(self):
        streams = set(self.active_streams)
        if len(streams) != len(self.active_streams) or not {"audio", "motion"} <= streams:
            raise ValueError("active_streams must uniquely include audio and motion")
        if self.face_mode in {"none", "jaw_only"} and "face" in streams:
            raise ValueError("none/jaw_only uses motion and must not wait for a face stream")
        if self.face_mode in {"blendshape", "bone_face"} and "face" not in streams:
            raise ValueError("blendshape/bone_face requires an explicit face stream")
        return self


class Joint(Contract):
    name: str
    parent: str | None
    semantic: str
    rest_translation: tuple[float, float, float] = (0, 0, 0)
    rest_rotation_xyzw: tuple[float, float, float, float] = (0, 0, 0, 1)
    local_axis: tuple[float, float, float] = (1, 0, 0)
    angle_limits_deg: tuple[float, float] = (-10, 10)
    owner: Literal["base", "expression", "speech", "gaze"]

    @model_validator(mode="after")
    def valid_transform(self):
        for vector in (self.rest_rotation_xyzw, self.local_axis):
            if not math.isclose(sum(v * v for v in vector), 1, abs_tol=1e-5):
                raise ValueError("rest quaternion and local axis must be unit length")
        low, high = self.angle_limits_deg
        if not -180 <= low <= 0 <= high <= 180:
            raise ValueError("angle limits must contain the neutral pose and lie within [-180,180]")
        return self


class RigMap(Contract):
    skeleton_version: str
    coordinate_system: Literal["right_handed_y_up_meters"]
    root_motion_node: str
    joints: list[Joint] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_tree(self):
        by_name = {j.name: j for j in self.joints}
        if len(by_name) != len(self.joints) or self.root_motion_node not in by_name:
            raise ValueError("joint names must be unique and root_motion_node must exist")
        if sum(j.parent is None for j in self.joints) != 1:
            raise ValueError("M0 requires one connected skeleton root")
        for joint in self.joints:
            visited = set()
            node = joint
            while True:
                if node.name in visited:
                    raise ValueError("cyclic skeleton")
                visited.add(node.name)
                if node.parent is None:
                    break
                if node.parent not in by_name:
                    raise ValueError(f"missing parent: {node.parent}")
                node = by_name[node.parent]
        return self


class FaceChannel(Contract):
    source: str
    target: str
    minimum: float = 0
    maximum: float = 1
    renderers: list[Literal["3d", "2d"]] = Field(default_factory=lambda: ["3d"], min_length=1, max_length=1)

    @model_validator(mode="after")
    def ordered(self):
        if self.minimum > self.maximum:
            raise ValueError("face minimum exceeds maximum")
        return self


class FaceMap(Contract):
    channels: list[FaceChannel] = Field(default_factory=list)


class Motion(Contract):
    file: str | None = None
    procedural: Literal["neutral", "head_nod", "speech_rhythm"] | None = None
    duration_s: float = Field(default=1, gt=0, le=60)
    loop: bool = False
    blend_s: float = Field(default=0.15, ge=0, le=2)
    fallback: Intent | None = None

    @model_validator(mode="after")
    def has_source(self):
        if sum(v is not None for v in (self.file, self.procedural, self.fallback)) != 1:
            raise ValueError("motion needs exactly one of file, procedural or fallback")
        return self


class MotionManifest(Contract):
    skeleton_version: str
    motions: dict[Intent, Motion]

    @model_validator(mode="after")
    def valid_fallbacks(self):
        if not STATES <= set(self.motions):
            raise ValueError(f"missing required states: {STATES - set(self.motions)}")
        for name in self.motions:
            visited = set()
            while name is not None:
                if name in visited or name not in self.motions:
                    raise ValueError("cyclic or missing motion fallback")
                visited.add(name)
                name = self.motions[name].fallback
        return self


class VoiceProfile(Contract):
    backend: Literal["replay", "cosyvoice3", "qwen3_base"]
    model_id: str | None = None
    revision: str | None = None
    reference_audio: str | None = None
    reference_text: str | None = None
    reference_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")] | None = None
    supported_styles: list[str] = Field(default_factory=lambda: ["neutral"])
    design_prompt: str
    effects: Literal["dry"] = "dry"

    @model_validator(mode="after")
    def truthful_backend(self):
        if "neutral" not in self.supported_styles:
            raise ValueError("neutral must be available as a style fallback")
        if self.backend == "qwen3_base" and self.supported_styles != ["neutral"]:
            raise ValueError("Qwen Base has no separate style instruction contract")
        refs = (self.reference_audio, self.reference_text, self.reference_sha256)
        if any(v is not None for v in refs) and not all(v is not None for v in refs):
            raise ValueError("reference audio, text and hash must be supplied together")
        return self


class Provenance(Contract):
    kind: Literal["project_authored_fixture", "external_asset", "generated_asset"]
    sources: list[dict[str, str]]
    seed: int | None = None
    generation_record: str | None = None
    notes: str


class QAReport(Contract):
    status: Literal["not_run", "failed", "passed"]
    checks: dict[str, Literal["pending", "failed", "passed"]]
    known_issues: list[str]


class CharacterPackage(Contract):
    profile: Profile
    capabilities: Capabilities
    rig_map: RigMap
    face_map: FaceMap
    motion_manifest: MotionManifest
    voice_profile: VoiceProfile
    provenance: Provenance
    qa_report: QAReport

    @model_validator(mode="after")
    def consistent(self):
        if self.profile.renderer_2d == "cubism" and (
            "2d" not in self.profile.presentation_modes or not self.profile.live2d_model
        ):
            raise ValueError("Cubism requires a declared 2D mode and model manifest")
        if "3d" in self.profile.presentation_modes and not self.profile.model:
            raise ValueError("3D presentation requires a model asset")
        if self.rig_map.skeleton_version != self.motion_manifest.skeleton_version:
            raise ValueError("motion and rig skeleton versions must agree")
        jaw = [j for j in self.rig_map.joints if j.semantic == "jaw" and j.owner == "speech"]
        if self.capabilities.face_mode == "jaw_only" and not jaw:
            raise ValueError("jaw_only requires a jaw joint owned by speech")
        if self.capabilities.face_mode in {"none", "jaw_only"} and self.face_map.channels:
            raise ValueError("no face channel mapping is allowed for none/jaw_only")
        if any(set(c.renderers) - set(self.profile.presentation_modes) for c in self.face_map.channels):
            raise ValueError("face channels must target a declared presentation mode")
        if self.profile.package_status == "validated" and self.qa_report.status != "passed":
            raise ValueError("validated assets require a passed QA report")
        return self


class ActionCue(Contract):
    """One bounded clip, timed from the first audio sample of its sentence."""

    name: Literal["nod", "shake_head", "tilt", "bow", "lean_forward", "lean_back", "sway", "bounce"]
    start_s: float = Field(default=0, ge=0, le=5)
    duration_s: float = Field(default=1.6, ge=0.4, le=4)
    strength: float = Field(default=0.6, ge=0, le=1)


class Delivery(Contract):
    tone: Literal["conversational", "warm", "playful", "serious"] = "conversational"
    pace: Literal["natural", "relaxed", "brisk"] = "natural"
    pause_after_ms: int = Field(default=260, ge=0, le=900)


class Segment(Contract):
    turn_id: Identifier
    segment_id: int = Field(ge=0)
    sequence: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=2000)
    emotion: str = "neutral"
    delivery: Delivery = Field(default_factory=Delivery)
    intensity: float = Field(default=0.4, ge=0, le=1)
    action_intent: Intent = "speak"
    actions: list[ActionCue] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def legacy_action(self):
        # Older roleplay adapters only supplied an intent. Explicit [] means
        # stillness and must never be replaced with an inferred action.
        names = {
            "acknowledge": "nod",
            "explain": "lean_forward",
            "uncertain": "tilt",
            "alert": "lean_back",
            "leave": "bow",
        }
        if "actions" not in self.model_fields_set and self.action_intent in names:
            self.actions = [ActionCue(name=names[self.action_intent], strength=self.intensity)]
        return self


class SpeakRequest(Contract):
    type: Literal["speak"]
    turn_id: Identifier
    character_id: Identifier
    conversation_id: Identifier | None = None
    text: str = Field(min_length=1, max_length=1000)
    source: Literal["user", "initiative"] = "user"
    initiative_ticket: str | None = None

    @model_validator(mode="after")
    def meaningful_text(self):
        self.text = self.text.strip()
        if not self.text or not any(c.isalnum() for c in self.text):
            raise ValueError("Message must contain meaningful text")
        return self

    emotion: Literal["auto", "neutral", "happy", "sad", "angry", "soft"] = "auto"


class CancelRequest(Contract):
    type: Literal["cancel"]
    turn_id: Identifier


class Event(Contract):
    schema_version: Literal["0.1.0"] = "0.1.0"
    type: Literal[
        "turn_start",
        "text",
        "stream_start",
        "audio",
        "motion",
        "face",
        "stream_end",
        "turn_end",
        "cancelled",
        "error",
    ]
    turn_id: Identifier
    conversation_id: Identifier | None = None
    segment_id: int = Field(default=0, ge=0)
    sequence: int = Field(ge=0)
    sample_offset: int = Field(default=0, ge=0)
    sample_rate: Literal[24000] = 24000
    data: dict = Field(default_factory=dict)


SCHEMAS = {
    model.__name__: model
    for model in (
        Profile,
        Capabilities,
        RigMap,
        FaceMap,
        MotionManifest,
        VoiceProfile,
        Provenance,
        QAReport,
        CharacterPackage,
        Segment,
        SpeakRequest,
        CancelRequest,
        Event,
    )
}
