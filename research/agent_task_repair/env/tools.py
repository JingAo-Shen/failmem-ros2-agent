"""
Structured Tool Definitions and Return Types for FailMem Stage 2 Environment.
"""
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from enum import Enum


class StatusCode(str, Enum):
    SUCCESS = "SUCCESS"
    DOOR_BLOCKED = "DOOR_BLOCKED"
    ACCESS_DENIED_NO_BADGE = "ACCESS_DENIED_NO_BADGE"
    RECIPIENT_BUSY = "RECIPIENT_BUSY"
    RECIPIENT_AWAY = "RECIPIENT_AWAY"
    WRONG_LOCATION = "WRONG_LOCATION"
    PACKAGE_NOT_FOUND = "PACKAGE_NOT_FOUND"
    INVENTORY_FULL = "INVENTORY_FULL"
    NOT_HOLDING_PACKAGE = "NOT_HOLDING_PACKAGE"
    BATTERY_DEPLETED = "BATTERY_DEPLETED"
    INVALID_PARAMETER = "INVALID_PARAMETER"
    ACTION_TIMEOUT = "ACTION_TIMEOUT"
    NOT_AT_CHARGER = "NOT_AT_CHARGER"
    PARSE_ERROR = "PARSE_ERROR"


@dataclass
class ActionResult:
    status: StatusCode
    success: bool
    message: str
    observation: Dict[str, Any] = field(default_factory=dict)
    time_cost_s: float = 0.0
    battery_cost_pct: int = 0
    error_code: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "success": self.success,
            "message": self.message,
            "observation": self.observation,
            "time_cost_s": self.time_cost_s,
            "battery_cost_pct": self.battery_cost_pct,
            "error_code": self.error_code,
        }

    def format_for_agent(self) -> str:
        """Format return dict into a clean JSON-like string for LLM consumption."""
        obs_str = ""
        if self.observation:
            obs_str = f", observation: {self.observation}"
        return f"[Status: {self.status.value}, Success: {self.success}, TimeCost: {self.time_cost_s:.1f}s, BatteryCost: {self.battery_cost_pct}%{obs_str}] {self.message}"
