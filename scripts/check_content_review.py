"""Real-model contrast cases for evidence-grounded content review and bounded repair."""

import argparse
import asyncio
import json
from pathlib import Path

from roleplay_world.content import StoryBlueprint, WorldBlueprint, compile_story
from roleplay_world.content_review import assess_content, review_story
from roleplay_world.gateway import ModelGateway

ROOT = Path(__file__).resolve().parents[1]


def baseline():
    world = WorldBlueprint(
        title="钟楼调查", genre="温暖调查", tone="明亮", premise="居民希望找出钟楼停转原因。", setting="旅人在镇上调查。",
        locations=[{"name": name, "description": "可自由调查的公共地点。", "connects_to": links}
                   for name, links in [("钟楼", [1]), ("档案室", [0, 2]), ("广场", [1])]],
        characters=[{"name": name, "role": "居民", "personality": "耐心", "goal": "帮助调查", "boundary": "不愿伤害人",
                     "location": i, "secret": "想在秋天学习画画。"} for i, name in enumerate(["艾琳", "老莫"])])
    story = StoryBlueprint(
        title="校准钟楼", synopsis="调查证据并校准现场装置。", player_role="调查员", opening="你站在钟楼内，看到齿轮停转。",
        start_location=0, starting_item="笔记本", acts=["调查证据", "校准现场"],
        clues=[{"title": "钥匙位置", "text": "铜钥匙的位置可用来辨认装置，调查只获取这条知识。", "location": 0},
               {"title": "装置图示", "text": "墙上的图示说明装置的工作原理。", "location": 1}],
        challenges=[{"title": "核对结构", "description": "根据已知图示核对现场结构。", "location": 1,
                     "required_clues": [1], "success": "你核对了现场结构。"},
                    {"title": "校准", "description": "根据铜钥匙线索确认装置的位置，校准现场齿轮。", "location": 0,
                     "required_clues": [0, 1], "success": "现场校准完成。", "ending": True}],
        pressure_name="午后", pressure_event="居民们准备休息。",
        state_rules={"variables": [
            {"id": "key_found", "name": "铜钥匙位置确认", "kind": "boolean", "initial": False},
            {"id": "progress", "name": "校准进度", "kind": "integer", "initial": 5, "maximum": 10},
            {"id": "hidden", "name": "幕后警戒", "kind": "integer", "initial": 37, "visibility": "gm"}],
            "actions": [{"id": "inspect", "name": "确认位置", "description": "观察现场，确认铜钥匙的位置，不移动实物。",
                         "effects": [{"kind": "set", "target": "key_found", "value": True},
                                     {"kind": "add", "target": "progress", "value": 1},
                                     {"kind": "message", "text": "铜钥匙位置已经确认，校准进度增加1。"}]}],
            "tests": [{"name": "确认位置", "steps": [{"kind": "state_action", "target_id": "inspect"}],
                       "expect": [{"source": "variable", "key": "key_found", "value": True}]}]})
    compile_story(world, story, "review_contrast")
    return world, story


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--repair-source", help="Optional private native export to review and repair without changing its source")
    args = parser.parse_args()
    folder = (ROOT/args.output).resolve()
    if not folder.is_relative_to(ROOT/"outputs/validation"):
        raise ValueError("Invalid report path")
    folder.mkdir(parents=True, exist_ok=False)
    gateway = ModelGateway(json.loads((ROOT/"configs/models.local.json").read_text()), folder/"traces")
    report = {"status": "running", "mode": "live_models", "cases": [], "calls": []}

    def save():
        (folder/"report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")

    async def generate(role, prompt, data, schema, jid, validator):
        budget = {"calls": 0, "repairs": 0, "traces": [], "max_calls": 3, "max_repairs": 2}
        try:
            return await gateway.generate(role, prompt, data, schema, jid, budget, validate=validator)
        finally:
            report["calls"].extend(budget["traces"])
            save()

    try:
        world, story = baseline()
        for name, kind in [("knowledge_only", None), ("local_display", None), ("item_receipt", "unsupported_item"),
                           ("contextual_handover", "unsupported_item"),
                           ("mandatory_item", "unmodeled_dependency"), ("opposite_value", "contradictory_effect"),
                           ("public_secret", "secret_exposure")]:
            candidate = story.model_copy(deep=True)
            if name in {"local_display", "contextual_handover"}:
                candidate.challenges[0].title = "核对墙上图示" if name == "local_display" else "让老莫交出机械图纸"
                candidate.challenges[0].description = ("与老莫一起查看他展示的墙上图示。" if name == "local_display"
                                                       else "说服老莫将机械图纸交给你，作为你的随身工具。")
                candidate.challenges[0].success = "老莫取出机械图纸，展示其中的说明。"
            elif name == "item_receipt":
                candidate.state_rules.actions[0].effects[-1].text = "铜钥匙落入你的手中，已放入你的背包。"
            elif name == "mandatory_item":
                candidate.challenges[-1].description = "必须先从背包交出一张机械图纸，才能校准齿轮。"
            elif name == "opposite_value":
                candidate.state_rules.actions[0].effects[-1].text = "校准进度减少1。"
            elif name == "public_secret":
                candidate.opening = "你站在钟楼内。幕后警戒当前值为37。"
            review, rejected = await assess_content(world, candidate, generate, name)
            kinds = {issue.kind for issue in review.issues}
            # A mandatory handover is both a missing dependency and unsupported
            # inventory transfer; either diagnosis must point to the injected text.
            allowed = {kind, "unsupported_item"} if name == "mandatory_item" else {kind}
            paths = {"item_receipt": "/story/state_rules/actions/0/effects/2/text",
                     "contextual_handover": "/story/challenges/0/", "mandatory_item": "/story/challenges/1/",
                     "opposite_value": "/story/state_rules/actions/0/effects/2/text", "public_secret": "/story/opening"}
            passed = any(c.kind in allowed and c.path.startswith(paths[name]) for c in review.issues) if kind else not kinds
            report["cases"].append({"name": name, "expected": kind, "status": "passed" if passed else "failed",
                                    **review.model_dump(), "rejected_findings": rejected})
            print(name, report["cases"][-1]["status"], sorted(kinds), flush=True)
            save()
        if args.repair_source:
            original = json.loads((ROOT/args.repair_source).read_text())
            world = WorldBlueprint.model_validate(original["world"])
            story = StoryBlueprint.model_validate(original["story"])
            repaired, result = await review_story(world, story, generate, "repair_original", repair=True)
            (folder/"after.local.json").write_text(json.dumps({**original, "story": repaired.model_dump()}, ensure_ascii=False, indent=2))
            report["repair"] = result
            assert result["repair_rounds"] > 0, "Known original mismatch must be repaired"
        assert all(case["status"] == "passed" for case in report["cases"]), "Contrast case failure"
        report["status"] = "passed"
    except BaseException as exc:
        report.update(status="failed", error=str(exc))
        raise
    finally:
        save()


if __name__ == "__main__":
    asyncio.run(main())
