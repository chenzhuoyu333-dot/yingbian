"""应变：W1 施工图实现（schema + 四态传播 + 最小修复）。"""

from .models import Alternative, Edge, Node, Plan, PlanError, load_plan
from .propagate import Event, ImpactReport, propagate
from .repair import Action, RepairResult, apply_actions, repair

__all__ = [
    "Alternative",
    "Edge",
    "Node",
    "Plan",
    "PlanError",
    "load_plan",
    "Event",
    "ImpactReport",
    "propagate",
    "Action",
    "RepairResult",
    "apply_actions",
    "repair",
]

__version__ = "0.2.0"
