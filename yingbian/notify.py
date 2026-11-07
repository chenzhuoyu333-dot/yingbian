"""Notification preview and action checklist built from repair actions.

W2 §6 is explicit: the first version does not infer who needs to act. It shows
the affected rows and lets the user confirm recipients, so this module only
renders the rows and the concrete actions.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import Plan
from .repair import RepairResult


@dataclass
class Notification:
    node_id: str
    title: str
    level: str
    text: str


@dataclass
class ActionItem:
    text: str
    kind: str
    node_id: str = ""
    phone: str = ""
    script: str = ""


def build_preview(plan: Plan, result: RepairResult) -> tuple[list[Notification], list[ActionItem]]:
    notifications: list[Notification] = []
    actions: list[ActionItem] = []
    for action in result.actions:
        node = result.plan.find(action.node_id)
        title = action.payload.get("fromTitle") or (node.title if node else action.node_id)
        if action.action == "replace":
            old_title = action.payload.get("fromTitle", title)
            new_title = action.payload.get("toTitle", title)
            text = f"{old_title} 已改去「{new_title}」"
            level = "打断" if node and node.type == "reservation" else "知会"
        elif action.action == "drop":
            text = f"{title} 已取消"
            level = "打断"
        else:
            minutes = action.payload.get("minutes", 0)
            text = f"{title} 后移 {minutes} 分钟"
            level = "知会"
        notifications.append(Notification(action.node_id, title, level, text))

        if action.action == "replace" and node and node.contact:
            actions.append(
                ActionItem(
                    text=f"电话 {node.place or title} 确认新安排",
                    kind="call",
                    node_id=action.node_id,
                    phone=node.contact,
                    script=f"你好，我们原计划有变动，想确认 {node.title} 还可以安排吗？",
                )
            )
        elif action.action == "drop":
            actions.append(
                ActionItem(
                    text=f"告知同行：{title} 取消",
                    kind="notify",
                    node_id=action.node_id,
                )
            )
        else:
            actions.append(
                ActionItem(
                    text=f"告知同行：{text}",
                    kind="notify",
                    node_id=action.node_id,
                )
            )

    if not notifications:
        notifications.append(Notification("", "全员", "知会", "计划未变，无需打扰"))
    return notifications, actions


def render_notifications(plan: Plan, result: RepairResult) -> str:
    notifications, _ = build_preview(plan, result)
    lines = ["通知预览（通知对象由用户勾选）"]
    for item in notifications:
        lines.append(f"  [{item.level}] {item.title}：{item.text}")
    return "\n".join(lines)


def render_actions(plan: Plan, result: RepairResult) -> str:
    _, actions = build_preview(plan, result)
    lines = ["动作清单"]
    if not actions:
        lines.append("  ☐ 无（不需要额外动作）")
    for action in actions:
        lines.append(f"  ☐ {action.text}")
        if action.phone:
            lines.append(f"      拨号：tel:{action.phone}")
        if action.script:
            lines.append(f"      话术：{action.script}")
    return "\n".join(lines)
