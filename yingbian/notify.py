"""Notification preview and action checklist built from a repair diff.

The point is to separate "who must be interrupted" from "who only needs to
know". A changed node with an action (reservation / transport / replacement)
becomes an interruption; everything else is a silent notice.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Plan, format_time
from .repair import Change, RepairResult


@dataclass
class Notification:
    person_id: str
    person_name: str
    level: str
    text: str
    node_ids: list[str] = field(default_factory=list)


@dataclass
class ActionItem:
    text: str
    kind: str
    node_id: str = ""
    phone: str = ""
    script: str = ""


def _is_removed(change: Change) -> bool:
    return change.old_active and not change.new_active


def _is_added(change: Change) -> bool:
    return not change.old_active and change.new_active


def _is_replacement_pair(left: Change, right: Change) -> bool:
    if left.node_id == right.node_id:
        return False
    if set(left.persons) != set(right.persons):
        return False
    if not ((_is_removed(left) and _is_added(right)) or (_is_added(left) and _is_removed(right))):
        return False
    return abs(left.old_start - right.old_start) <= 60


def _change_groups(plan: Plan, changes: list[Change]) -> list[list[Change]]:
    """Merge 'activity cancelled' + 'backup enabled' into one readable change."""
    groups: list[list[Change]] = []
    used: set[int] = set()
    for index, change in enumerate(changes):
        if index in used:
            continue
        group = [change]
        used.add(index)
        for other_index, other in enumerate(changes):
            if other_index in used:
                continue
            if _is_replacement_pair(change, other):
                group.append(other)
                used.add(other_index)
                break
        groups.append(group)
    return groups


def build_preview(plan: Plan, result: RepairResult) -> tuple[list[Notification], list[ActionItem]]:
    people = plan.person_map()
    nodes = plan.node_map()
    notifications: list[Notification] = []
    actions: list[ActionItem] = []

    for group in _change_groups(plan, result.changes):
        removed = [c for c in group if c.old_active and not c.new_active]
        added = [c for c in group if not c.old_active and c.new_active]
        moved = [c for c in group if c.old_active and c.new_active and c.old_start != c.new_start]
        person_ids = sorted({p for c in group for p in c.persons})
        names = "、".join(people[p].name for p in person_ids if p in people)
        start = group[0].new_start if added else group[0].old_start

        if removed and added:
            old, new = nodes[removed[0].node_id], nodes[added[0].node_id]
            text = f"{format_time(start)} {old.title} 取消，改 {new.title}（{new.place or '原地点'}）"
            level = "打断"
            actions.append(
                ActionItem(
                    text=f"通知 {names}：{old.title} 改 {new.title}",
                    kind="notify",
                    node_id=new.id,
                )
            )
            if new.kind == "reservation" and new.contact:
                actions.append(
                    ActionItem(
                        text=f"电话 {new.place} 确认 {format_time(start)} 的预约",
                        kind="call",
                        node_id=new.id,
                        phone=new.contact,
                        script=f"你好，我们原定 {format_time(start)} 的预约有变动，想确认还能否安排……",
                    )
                )
        elif moved:
            node = nodes[moved[0].node_id]
            text = f"{node.title} 从 {format_time(moved[0].old_start)} 改到 {format_time(moved[0].new_start)}"
            level = "打断" if node.kind in {"reservation", "transit"} else "知会"
            if node.kind == "reservation" and node.contact:
                actions.append(
                    ActionItem(
                        text=f"电话 {node.place} 改期到 {format_time(moved[0].new_start)}",
                        kind="call",
                        node_id=node.id,
                        phone=node.contact,
                        script=f"你好，我们想把 {format_time(moved[0].old_start)} 的预约改到 {format_time(moved[0].new_start)}，还可以吗？",
                    )
                )
            else:
                actions.append(
                    ActionItem(
                        text=f"告知 {names}：{text}",
                        kind="notify",
                        node_id=node.id,
                    )
                )
        else:
            node = nodes[group[0].node_id]
            text = f"{node.title} 有调整"
            level = "知会"

        for person_id in person_ids:
            notifications.append(
                Notification(
                    person_id=person_id,
                    person_name=people[person_id].name if person_id in people else person_id,
                    level=level,
                    text=text,
                    node_ids=[c.node_id for c in group],
                )
            )

    if not notifications:
        notifications.append(
            Notification("", "全员", "知会", "计划未变，无需打扰", [])
        )
    return notifications, actions


def render_notifications(plan: Plan, result: RepairResult) -> str:
    notifications, _ = build_preview(plan, result)
    lines = ["通知预览"]
    seen: set[tuple[str, str]] = set()
    for item in notifications:
        key = (item.person_id, item.text)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"  [{item.level}] {item.person_name}：{item.text}")
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


def render_preview(plan: Plan, result: RepairResult) -> str:
    return "\n\n".join(
        [render_notifications(plan, result), render_actions(plan, result)]
    )
