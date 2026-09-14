"""Versioned narrative content templates and immutable run snapshots."""
import copy
import hashlib
import json

_RAW = {
    "classic_insight_v1": {
        "display_name": "认知拆解", "version": "1",
        "stages": [
            ("开场共情", "从观众熟悉的困境切入", "hook"),
            ("底层病灶", "解释问题背后的机制", "insight"),
            ("核心模型", "提炼书中的关键框架", "insight"),
            ("实战工具", "给出可执行的应用方法", "action"),
            ("哲学升华", "收束为长期的思考与行动", "action"),
        ],
        "guidance": {
            "copy": "从共情问题逐步推导到模型与行动，避免只罗列观点。",
            "script": "开场快速建立共鸣，中段解释机制，结尾给出可持续练习。",
            "storyboard": "画面由困境、机制示意和行动场景逐步推进。",
        },
    },
    "story_journey_v1": {
        "display_name": "案例故事", "version": "1",
        "stages": [
            ("人物处境", "建立人物、目标与现实处境", "hook"),
            ("冲突升级", "让代价、障碍或误判具体化", "insight"),
            ("关键发现", "通过书中观点触发理解变化", "insight"),
            ("转折", "展示新理解如何改变选择", "action"),
            ("落地启示", "把故事迁移为观众可用的启示", "action"),
        ],
        "guidance": {
            "copy": "以一个连贯人物或事件作为主线，每段都推进冲突或理解。",
            "script": "优先叙事动作、选择与后果，理论只在关键发现处集中解释。",
            "storyboard": "保持角色、场景和时间线连续，用转折前后对照表现变化。",
        },
    },
    "practical_workshop_v1": {
        "display_name": "问题解法", "version": "1",
        "stages": [
            ("问题诊断", "明确症状、代价与适用人群", "hook"),
            ("核心原则", "说明解决问题不可省略的原则", "insight"),
            ("操作步骤", "拆成有顺序的实践步骤", "insight"),
            ("案例演练", "用具体场景演示步骤的使用", "action"),
            ("行动清单", "收束为当下可执行的检查清单", "action"),
        ],
        "guidance": {
            "copy": "围绕一个明确问题组织，步骤必须能被案例验证。",
            "script": "先诊断再讲原则，步骤使用清晰顺序，结尾形成行动清单。",
            "storyboard": "重点呈现问题信号、步骤操作和案例前后对比。",
        },
    },
}

ALLOWED_BLOCK_TYPES = ("CARD", "QUOTE", "TABLE", "STEPS")
CONTENT_TEMPLATE_IDS = tuple(_RAW)

def get_template(name=None):
    name = name or "classic_insight_v1"
    if name not in _RAW:
        raise ValueError("未知 content template：" + str(name))
    raw = _RAW[name]
    data = {"id": name, "version": raw["version"],
            "display_name": raw["display_name"], "stages": [
                {"index": i + 1, "name": stage, "objective": objective,
                 "segment": segment,
                 "allowed_block_types": list(ALLOWED_BLOCK_TYPES)}
                for i, (stage, objective, segment) in enumerate(raw["stages"])],
            "guidance": copy.deepcopy(raw["guidance"])}
    data["sha256"] = hashlib.sha256(
        json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return data

def template_snapshot(value=None):
    if isinstance(value, dict) and value.get("id") in _RAW:
        snapshot = copy.deepcopy(value)
        required = {"id", "version", "stages", "guidance", "sha256"}
        if required <= set(snapshot) and len(snapshot["stages"]) == 5:
            return snapshot
        return get_template(snapshot["id"])
    return get_template(value if isinstance(value, str) else None)

def template_names(template=None):
    return [x["name"] for x in template_snapshot(template)["stages"]]


def template_catalog():
    """返回供人工选择的完整模板目录；新增模板会自动出现在目录中。"""
    return [get_template(name) for name in CONTENT_TEMPLATE_IDS]
