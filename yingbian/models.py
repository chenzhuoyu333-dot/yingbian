"""W1 spec data model: plan-saturday.json.

The external schema follows W1施工图 §1 exactly:
  planId / title / date / nodes / edges
  node: type, start, end, indoor, confirmed, windowLatest, alternatives, source, confidence
  edge: from, to, type, minGapMin

Only the amount needed for the demo is modelled. `dropped` is runtime state used
by the repair loop and is never written back to the plan file.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class PlanError(ValueError):
    """Raised when a plan file violates the W1 schema."""


def parse_time(value: str | int | None) -> int | None:
    if value is None or isinstance(value, int):
        return value
    try:
        hours, minutes = value.split(":")
        return int(hours) * 60 + int(minutes)
    except (AttributeError, ValueError) as exc:
        raise PlanError(f"时间格式应为 HH:mm，收到 {value!r}") from exc


def format_time(minutes: int | None) -> str | None:
    if minutes is None:
        return None
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


@dataclass
class Source:
    kind: str = "manual"
    note: str = ""
    at: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "note": self.note, "at": self.at}


@dataclass
class Alternative:
    id: str
    title: str
    indoor: bool
    start: int
    end: int
    travel_min: int = 0
    place: str = ""
    sacrifice: str = ""
    contact: str = ""

    @property
    def duration(self) -> int:
        return self.end - self.start

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "indoor": self.indoor,
            "start": format_time(self.start),
            "end": format_time(self.end),
            "travelMin": self.travel_min,
            "place": self.place,
            "sacrifice": self.sacrifice,
            "contact": self.contact,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Alternative":
        return cls(
            id=raw["id"],
            title=raw["title"],
            indoor=bool(raw["indoor"]),
            start=parse_time(raw["start"]) or 0,
            end=parse_time(raw["end"]) or 0,
            travel_min=int(raw.get("travelMin", 0)),
            place=raw.get("place", ""),
            sacrifice=raw.get("sacrifice", ""),
            contact=raw.get("contact", ""),
        )


@dataclass
class Node:
    id: str
    type: str
    title: str
    start: int
    end: int
    indoor: bool
    confirmed: bool
    window_latest: int | None = None
    alternatives: list[Alternative] = field(default_factory=list)
    source: Source = field(default_factory=Source)
    confidence: str = "high"
    place: str = ""
    contact: str = ""
    # 多日行程里这个节点属于哪一天（YYYY-MM-DD）；旧计划没有这个字段
    date: str = ""
    # 住宿占位：表示今晚过夜，不表示在这里停留多少分钟
    overnight: bool = False
    persons: list[str] = field(default_factory=list)
    sacrifice: str = ""
    dropped: bool = False
    resolved: bool = False
    # 高德真实店面信息：rating / cost / openTime / tel / tags / missing
    poi: dict[str, Any] | None = None
    # 这个点为什么被选中（来自打分函数，可解释）
    reason: str = ""
    # 城市必看 / 必去 / 偏好 / 顺路：界面上直接展示，解释“为什么有这一站”
    selection_reason: str = ""
    # 停留时长的依据（经验值 / 用户调整）；空表示旧计划没有这个字段
    stay_basis: str = ""

    @property
    def duration(self) -> int:
        return self.end - self.start

    def interval(self) -> tuple[int, int]:
        return self.start, self.end

    def clone(self) -> "Node":
        return copy.deepcopy(self)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "start": format_time(self.start),
            "end": format_time(self.end),
            "indoor": self.indoor,
            "confirmed": self.confirmed,
            "windowLatest": format_time(self.window_latest),
            "alternatives": [alt.to_dict() for alt in self.alternatives],
            "source": self.source.to_dict(),
            "confidence": self.confidence,
            "place": self.place,
            "contact": self.contact,
            "date": self.date,
            "overnight": self.overnight,
            "persons": list(self.persons),
            "sacrifice": self.sacrifice,
            # 来自高德的真实店面信息（评分/人均/营业时间/电话/招牌菜）与入选理由。
            # 生成器会填；手工计划没有这两个字段，前端读成空即可。
            "poi": dict(self.poi) if self.poi else None,
            "reason": self.reason,
            "selectionReason": self.selection_reason,
            "stayBasis": self.stay_basis,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Node":
        try:
            node = cls(
                id=raw["id"],
                type=raw["type"],
                title=raw["title"],
                start=parse_time(raw["start"]) or 0,
                end=parse_time(raw["end"]) or 0,
                indoor=bool(raw["indoor"]),
                confirmed=bool(raw["confirmed"]),
                window_latest=parse_time(raw.get("windowLatest")),
                alternatives=[Alternative.from_dict(a) for a in raw.get("alternatives", [])],
                source=Source(
                    kind=raw.get("source", {}).get("kind", "manual"),
                    note=raw.get("source", {}).get("note", ""),
                    at=raw.get("source", {}).get("at", ""),
                ),
                confidence=raw.get("confidence", "high"),
                place=raw.get("place", ""),
                contact=raw.get("contact", ""),
                date=raw.get("date", ""),
                overnight=bool(raw.get("overnight", False)),
                persons=list(raw.get("persons", [])),
                sacrifice=raw.get("sacrifice", ""),
                poi=dict(raw.get("poi") or {}) or None,
                reason=raw.get("reason", ""),
                selection_reason=raw.get("selectionReason", ""),
                stay_basis=raw.get("stayBasis", ""),
            )
        except KeyError as exc:
            raise PlanError(f"节点缺少字段 {exc.args[0]}: {raw.get('id', '?')}") from exc
        if node.end <= node.start:
            raise PlanError(f"节点 {node.id} 的 end 必须晚于 start")
        if node.type not in {"place", "slot", "transit", "reservation", "person", "task"}:
            raise PlanError(f"节点 {node.id} 的 type 非法: {node.type}")
        if node.confidence not in {"high", "medium", "low"}:
            raise PlanError(f"节点 {node.id} 的 confidence 非法: {node.confidence}")
        for alt in node.alternatives:
            if alt.end <= alt.start:
                raise PlanError(f"节点 {node.id} 的备选 {alt.id} 时间非法")
        return node


@dataclass
class Edge:
    src: str
    dst: str
    type: str = "precedes"
    min_gap: int = 0
    # 这段路怎么走：mode / label / distanceM / durationMin / source / text
    transport: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "from": self.src,
            "to": self.dst,
            "type": self.type,
            "minGapMin": self.min_gap,
            "transport": dict(self.transport) if self.transport else None,
        }


TIME_EDGES = {"precedes", "requires"}
EDGE_TYPES = {"precedes", "requires", "same_place", "shared_with"}


@dataclass
class Plan:
    plan_id: str
    title: str
    date: str
    nodes: list[Node]
    edges: list[Edge]
    version: int = 1
    end_date: str = ""
    days: int = 1
    # 生成器的说明（warnings / unresolvedMustVisit / humanSummary）。
    # 内置计划没有这一段；有了它，生成后的提示才会跟着计划一起返回给 App。
    generation: dict[str, Any] = field(default_factory=dict)

    def node(self, node_id: str) -> Node:
        for node in self.nodes:
            if node.id == node_id:
                return node
        raise PlanError(f"未知节点: {node_id}")

    def find(self, node_id: str) -> Node | None:
        return next((node for node in self.nodes if node.id == node_id), None)

    def clone(self) -> "Plan":
        return copy.deepcopy(self)

    def confirmed_nodes(self) -> list[Node]:
        return [node for node in self.nodes if node.confirmed]

    def active_nodes(self) -> list[Node]:
        return [node for node in self.nodes if not node.dropped]

    def edges_of(self, *types: str) -> list[Edge]:
        wanted = set(types)
        return [edge for edge in self.edges if edge.type in wanted]

    def predecessors(self, node_id: str) -> list[str]:
        return [edge.src for edge in self.edges if edge.dst == node_id and edge.type in TIME_EDGES]

    def successors(self, node_id: str) -> list[str]:
        return [edge.dst for edge in self.edges if edge.src == node_id and edge.type in TIME_EDGES]

    def topo_order(self) -> list[str]:
        indegree = {node.id: 0 for node in self.nodes}
        outgoing: dict[str, list[str]] = {node.id: [] for node in self.nodes}
        for edge in self.edges_of(*TIME_EDGES):
            outgoing[edge.src].append(edge.dst)
            indegree[edge.dst] += 1
        queue = [node_id for node_id, degree in indegree.items() if degree == 0]
        order: list[str] = []
        while queue:
            current = queue.pop(0)
            order.append(current)
            for nxt in outgoing[current]:
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    queue.append(nxt)
        if len(order) != len(self.nodes):
            raise PlanError("计划图存在环，无法传播")
        return order

    def to_dict(self) -> dict[str, Any]:
        result = {
            "planId": self.plan_id,
            "title": self.title,
            "date": self.date,
            "endDate": self.end_date,
            "days": self.days,
            "version": self.version,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
        }
        if self.generation:
            result["generation"] = self.generation
        return result

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Plan":
        try:
            plan = cls(
                plan_id=raw["planId"],
                title=raw["title"],
                date=raw["date"],
                end_date=raw.get("endDate", ""),
                days=int(raw.get("days", 1)),
                nodes=[Node.from_dict(item) for item in raw["nodes"]],
                edges=[
                    Edge(
                        src=edge["from"],
                        dst=edge["to"],
                        type=edge.get("type", "precedes"),
                        min_gap=int(edge.get("minGapMin", 0)),
                        transport=dict(edge.get("transport") or {}) or None,
                    )
                    for edge in raw.get("edges", [])
                ],
                version=int(raw.get("version", 1)),
                generation=dict(raw.get("generation") or {}),
            )
        except KeyError as exc:
            raise PlanError(f"计划缺少字段 {exc.args[0]}") from exc
        plan.validate()
        return plan

    @classmethod
    def load(cls, path: str | Path) -> "Plan":
        with open(path, "r", encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle))

    def validate(self) -> None:
        ids = [node.id for node in self.nodes]
        if len(ids) != len(set(ids)):
            raise PlanError("节点 id 重复")
        by_id = {node.id: node for node in self.nodes}
        for edge in self.edges:
            if edge.type not in EDGE_TYPES:
                raise PlanError(f"边类型非法: {edge.type}")
            if edge.src not in by_id or edge.dst not in by_id:
                raise PlanError(f"边引用了不存在的节点: {edge.src} -> {edge.dst}")
            if edge.min_gap < 0:
                raise PlanError(f"边 {edge.src} -> {edge.dst} 的 minGapMin 不能为负")
        for node in self.nodes:
            if node.window_latest is not None and node.window_latest < node.start:
                raise PlanError(f"节点 {node.id} 的 windowLatest 早于 start")
        self.topo_order()


def load_plan(path: str | Path | None = None) -> Plan:
    default = Path(__file__).resolve().parent.parent / "data" / "plan-saturday.json"
    return Plan.load(path or default)
