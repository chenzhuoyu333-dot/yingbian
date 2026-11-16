"""多人协作：成员、活动记录、投票。

设计取舍（为什么不是"共享文档"）：

  多人出行真正的痛点不是"看不到同一份行程"——微信群发个截图就解决了。
  真正的痛点是另外两件事：
    1. 谁说了算？（改一处会影响别人的安排）
    2. 改了什么、谁改的？（群里刷屏找不到结论）

  所以这里只做三件事：
    · 成员登记        —— 知道有谁在
    · 活动记录        —— 谁在什么时候提了什么（可追溯，替代群聊刷屏）
    · 投票决定        —— 影响大时不是谁手快谁说了算，而是少数服从多数 + 超时兜底

  实时性上用"客户端轮询 + 版本号"，不用长连接：
  演示环境 WiFi 本来就不稳，轮询比 WebSocket 更容易保证不翻车。

  并发写入用乐观锁（expectedVersion）：A 在 v3 上改、B 已改到 v4 时，
  A 的操作被拒并提示刷新，而不是悄悄覆盖 B 的改动。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime

SCHEMES = ("A", "B", "C")
DEFAULT_TTL_SECONDS = 300   # 5 分钟没人投完就按默认方案执行，不能卡死
MAX_ACTIVITY = 50


@dataclass
class Member:
    id: str
    name: str
    joined_at: str

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "joinedAt": self.joined_at}


@dataclass
class VoteRound:
    id: str
    plan_id: str
    event: dict
    options: list[str]
    votes: dict[str, str] = field(default_factory=dict)   # memberId -> schemeId
    ttl_sec: int = DEFAULT_TTL_SECONDS
    default_scheme: str = "B"
    created_at: float = field(default_factory=time.time)
    status: str = "open"           # open | closed
    winner: str | None = None
    decided_by: str = ""           # majority | all-voted | timeout-default

    @property
    def expires_at(self) -> float:
        return self.created_at + self.ttl_sec

    def tally(self) -> dict[str, int]:
        counts = {scheme: 0 for scheme in self.options}
        for scheme in self.votes.values():
            if scheme in counts:
                counts[scheme] += 1
        return counts

    def to_dict(self) -> dict:
        remaining = max(0, int(self.expires_at - time.time()))
        return {
            "id": self.id,
            "planId": self.plan_id,
            "event": self.event,
            "options": list(self.options),
            "votes": dict(self.votes),
            "tally": self.tally(),
            "status": self.status,
            "winner": self.winner,
            "decidedBy": self.decided_by,
            "defaultScheme": self.default_scheme,
            "remainingSec": remaining,
            "ttlSec": self.ttl_sec,
        }


@dataclass
class CollabState:
    members: dict[str, dict[str, Member]] = field(default_factory=dict)
    rounds: dict[str, VoteRound | None] = field(default_factory=dict)
    activity: dict[str, list[dict]] = field(default_factory=dict)

    # ── 成员 ──────────────────────────────────────
    def join(self, plan_id: str, member_id: str, name: str) -> Member:
        roster = self.members.setdefault(plan_id, {})
        existing = roster.get(member_id)
        if existing is not None:
            if name and name != existing.name:
                existing.name = name
            return existing
        member = Member(
            id=member_id,
            name=name or f"成员{len(roster) + 1}",
            joined_at=datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        )
        roster[member_id] = member
        self.record(plan_id, member.id, member.name, f"{member.name} 加入了行程")
        return member

    def roster(self, plan_id: str) -> list[Member]:
        return list(self.members.get(plan_id, {}).values())

    def member(self, plan_id: str, member_id: str) -> Member | None:
        return self.members.get(plan_id, {}).get(member_id)

    # ── 活动记录 ──────────────────────────────────
    def record(self, plan_id: str, member_id: str, name: str, text: str) -> None:
        log = self.activity.setdefault(plan_id, [])
        log.append(
            {
                "at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "memberId": member_id,
                "name": name,
                "text": text,
            }
        )
        del log[:-MAX_ACTIVITY]   # 只留最近 50 条

    def feed(self, plan_id: str) -> list[dict]:
        return list(reversed(self.activity.get(plan_id, [])))

    # ── 投票 ──────────────────────────────────────
    def start_vote(
        self,
        plan_id: str,
        event: dict,
        ttl_sec: int = DEFAULT_TTL_SECONDS,
        default_scheme: str = "B",
        initiator: Member | None = None,
    ) -> VoteRound:
        # 上一轮没结束就直接开始新一轮：旧轮次作废，避免两个投票同时生效
        self.rounds[plan_id] = None

        round_ = VoteRound(
            id="v_" + uuid.uuid4().hex[:8],
            plan_id=plan_id,
            event=dict(event or {}),
            options=list(SCHEMES),
            ttl_sec=max(10, min(3600, int(ttl_sec or DEFAULT_TTL_SECONDS))),
            default_scheme=default_scheme if default_scheme in SCHEMES else "B",
        )
        self.rounds[plan_id] = round_
        who = initiator.name if initiator else "有人"
        self.record(plan_id, initiator.id if initiator else "", who, f"{who} 发起投票：这次变化怎么改")
        return round_

    def current_vote(self, plan_id: str) -> VoteRound | None:
        round_ = self.rounds.get(plan_id)
        if round_ is None:
            return None
        self._maybe_resolve(plan_id, round_)
        return round_

    def cast_vote(self, plan_id: str, member_id: str, scheme_id: str) -> tuple[VoteRound | None, str]:
        """返回 (轮次, 错误信息)。错误信息为空表示成功。"""
        round_ = self.current_vote(plan_id)
        if round_ is None:
            return None, "当前没有进行中的投票"
        if round_.status != "open":
            return round_, "投票已经结束"

        member = self.member(plan_id, member_id)
        if member is None:
            return round_, "你还没加入这次行程，请先加入"
        if scheme_id not in round_.options:
            return round_, f"只能投 {'/'.join(round_.options)}"

        round_.votes[member.id] = scheme_id
        self.record(plan_id, member.id, member.name, f"{member.name} 投了方案 {scheme_id}")
        self._maybe_resolve(plan_id, round_)
        return round_, ""

    def _maybe_resolve(self, plan_id: str, round_: VoteRound) -> None:
        """
        结束条件（先到先判）：
          1. 全部成员都投了 → 按票数
          2. 超过 ttl 还没投完 → 按当前票数；平票/零票用默认方案
        平票一律用默认方案，不做二次投票 —— 演示不能卡住。
        """
        if round_.status != "open":
            return

        roster = self.roster(plan_id)
        all_voted = bool(roster) and len(round_.votes) >= len(roster)
        expired = time.time() >= round_.expires_at
        if not (all_voted or expired):
            return

        tally = round_.tally()
        top = max(tally.values()) if tally else 0
        leaders = [scheme for scheme, count in tally.items() if count == top and count > 0]

        if len(leaders) == 1:
            round_.winner = leaders[0]
            round_.decided_by = "all-voted" if all_voted else "majority"
        else:
            # 平票或没人投：用默认方案，并说明原因
            round_.winner = round_.default_scheme
            round_.decided_by = "timeout-default" if expired else "tie-default"
        round_.status = "closed"

        who = "全员已投" if all_voted else "投票超时"
        self.record(
            plan_id,
            "",
            "系统",
            f"{who}：方案 {round_.winner} 通过（{round_.decided_by}）",
        )


# 单进程内存状态。演示够用；重启会清空，这一点写进了 README 的已知限制。
STATE = CollabState()
