"""Data model for a resilience-aware day plan.

The model is deliberately small: nodes are places / slots / transit / reservations,
edges are one of five relation types. Everything is stored in one JSON file so the
same artefact can be used as algorithm fixture, demo script and UI seed data.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class PlanError(ValueError):
    """Raised when a plan file is malformed or internally inconsistent."""


def parse_time(value: str | int) -> int:
    if isinstance(value, int):
        return value
    try:
        hours, minutes = value.split(":")
        return int(hours) * 60 + int(minutes)
    except (AttributeError, ValueError) as exc:
        raise PlanError(f"时间格式应为 HH:MM，收到 {value!r}") from exc


def format_time(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


@dataclass(frozen=True)
class Member:
    id: str
    name: str
    role: str = "member"


@dataclass(frozen=True)
class Window:
    """Allowed start window, in minutes from midnight."""

    start: int
    end: int

    def contains(self, minute: int) -> bool:
        return self.start <= minute <= self.end


@dataclass
class Node:
    id: str
    kind: str
    title: str
    start: int
    duration: int
    persons: list[str]
    window: Window | None = None
    deadline: int | None = None
    outdoor: bool = False
    # none: unaffected by rain; degrade: becomes at_risk; cancel: becomes invalid
    weather_risk: str = "none"
    locked: bool = False
    active: bool = True
    alt_group: str | None = None
    source: str = "manual"
    confidence: str = "high"
    place: str = ""
    contact: str = ""

    @property
    def end(self) -> int:
        return self.start + self.duration

    def interval(self) -> tuple[int, int]:
        return self.start, self.end

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Node":
        try:
            window_raw = raw.get("window")
            window = (
                Window(parse_time(window_raw["start"]), parse_time(window_raw["end"]))
                if window_raw
                else None
            )
            deadline = parse_time(raw["deadline"]) if raw.get("deadline") else None
            node = cls(
                id=raw["id"],
                kind=raw["kind"],
                title=raw["title"],
                start=parse_time(raw["start"]),
                duration=int(raw["duration"]),
                persons=list(raw.get("persons", [])),
                window=window,
                deadline=deadline,
                outdoor=bool(raw.get("outdoor", False)),
                weather_risk=raw.get("weather_risk", "none"),
                locked=bool(raw.get("locked", False)),
                active=bool(raw.get("active", True)),
                alt_group=raw.get("alt_group"),
                source=raw.get("source", "manual"),
                confidence=raw.get("confidence", "high"),
                place=raw.get("place", ""),
                contact=raw.get("contact", ""),
            )
        except KeyError as exc:
            raise PlanError(f"节点缺少字段 {exc.args[0]}: {raw.get('id', '?')}") from exc
        if node.duration <= 0:
            raise PlanError(f"节点 {node.id} 的 duration 必须为正数")
        if node.weather_risk not in {"none", "degrade", "cancel"}:
            raise PlanError(f"节点 {node.id} 的 weather_risk 非法: {node.weather_risk}")
        if node.window and node.window.start > node.window.end:
            raise PlanError(f"节点 {node.id} 的时间窗起点晚于终点")
        return node


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    type: str = "precedes"


EDGE_TYPES = {"precedes", "requires", "same_place", "shared_with", "alternative_to"}
TIME_EDGES = {"precedes", "requires"}


@dataclass
class Plan:
    id: str
    title: str
    members: list[Member]
    nodes: list[Node]
    edges: list[Edge]
    travel: dict[str, dict[str, int]]
    day_start: int = 8 * 60
    version: int = 1

    def node(self, node_id: str) -> Node:
        for node in self.nodes:
            if node.id == node_id:
                return node
        raise PlanError(f"未知节点: {node_id}")

    def node_map(self) -> dict[str, Node]:
        return {node.id: node for node in self.nodes}

    def active_nodes(self) -> list[Node]:
        return [node for node in self.nodes if node.active]

    def person_map(self) -> dict[str, Member]:
        return {member.id: member for member in self.members}

    def edges_of(self, *types: str) -> list[Edge]:
        wanted = set(types)
        return [edge for edge in self.edges if edge.type in wanted]

    def successors(self, node_id: str) -> list[str]:
        return [edge.dst for edge in self.edges if edge.src == node_id and edge.type in TIME_EDGES]

    def predecessors(self, node_id: str) -> list[str]:
        return [edge.src for edge in self.edges if edge.dst == node_id and edge.type in TIME_EDGES]

    def travel_between(self, src: str, dst: str) -> int:
        try:
            return int(self.travel[src][dst])
        except KeyError as exc:
            raise PlanError(f"通行时间矩阵缺少 {src} -> {dst}") from exc

    def topo_order(self) -> list[str]:
        """Kahn topological order over time edges; detects cycles."""
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
            raise PlanError("计划图存在环，无法做时间传播")
        return order

    def alt_groups(self) -> dict[str, list[Node]]:
        groups: dict[str, list[Node]] = {}
        for node in self.nodes:
            if node.alt_group:
                groups.setdefault(node.alt_group, []).append(node)
        return groups

    def copy_with(
        self,
        *,
        starts: dict[str, int] | None = None,
        active: dict[str, bool] | None = None,
        version: int | None = None,
    ) -> "Plan":
        nodes = []
        for node in self.nodes:
            nodes.append(
                Node(
                    id=node.id,
                    kind=node.kind,
                    title=node.title,
                    start=starts.get(node.id, node.start) if starts else node.start,
                    duration=node.duration,
                    persons=list(node.persons),
                    window=node.window,
                    deadline=node.deadline,
                    outdoor=node.outdoor,
                    weather_risk=node.weather_risk,
                    locked=node.locked,
                    active=active.get(node.id, node.active) if active else node.active,
                    alt_group=node.alt_group,
                    source=node.source,
                    confidence=node.confidence,
                    place=node.place,
                    contact=node.contact,
                )
            )
        return Plan(
            id=self.id,
            title=self.title,
            members=list(self.members),
            nodes=nodes,
            edges=list(self.edges),
            travel=self.travel,
            day_start=self.day_start,
            version=version if version is not None else self.version + 1,
        )

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Plan":
        try:
            members = [
                Member(id=m["id"], name=m.get("name", m["id"]), role=m.get("role", "member"))
                for m in raw["members"]
            ]
            nodes = [Node.from_dict(item) for item in raw["nodes"]]
            edges = [
                Edge(src=e["from"], dst=e["to"], type=e.get("type", "precedes"))
                for e in raw.get("edges", [])
            ]
            plan = cls(
                id=raw.get("id", "plan"),
                title=raw.get("title", "未命名计划"),
                members=members,
                nodes=nodes,
                edges=edges,
                travel={key: dict(value) for key, value in raw.get("travel", {}).items()},
                day_start=parse_time(raw.get("day_start", "08:00")),
                version=int(raw.get("version", 1)),
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
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise PlanError("节点 id 重复")
        person_ids = {member.id for member in self.members}
        by_id = self.node_map()
        for node in self.nodes:
            if node.kind not in {"place", "slot", "transit", "reservation", "person", "task"}:
                raise PlanError(f"节点 {node.id} 的类型非法: {node.kind}")
            unknown = set(node.persons) - person_ids
            if unknown:
                raise PlanError(f"节点 {node.id} 引用了不存在的成员: {sorted(unknown)}")
        for edge in self.edges:
            if edge.type not in EDGE_TYPES:
                raise PlanError(f"边类型非法: {edge.type}")
            if edge.src not in by_id or edge.dst not in by_id:
                raise PlanError(f"边引用了不存在的节点: {edge.src} -> {edge.dst}")
        for edge in self.edges_of(*TIME_EDGES):
            if edge.src not in self.travel or edge.dst not in self.travel[edge.src]:
                raise PlanError(f"时间边 {edge.src} -> {edge.dst} 缺少通行时间")
        for group, nodes in self.alt_groups().items():
            active = [node for node in nodes if node.active]
            if len(active) > 1:
                raise PlanError(f"备选组 {group} 同时激活了多个节点: {[n.id for n in active]}")
        self.topo_order()


def load_plan(path: str | Path | None = None) -> Plan:
    default = Path(__file__).resolve().parent.parent / "data" / "guzhen_day.json"
    return Plan.load(path or default)
