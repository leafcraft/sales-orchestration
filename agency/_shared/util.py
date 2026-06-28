"""Shared agent helpers — session-id extraction, upstream-yields
navigation, robust JSON parsing, numeric clamps. Pure functions, no
side effects; imported by the per-agent modules.
"""
from __future__ import annotations

import json
import re
from typing import Any


def sid(input_data: Any, context: Any = None) -> str:
    """Best-effort session_id from input / context / webhook envelope."""
    for s in (context, input_data):
        if isinstance(s, dict):
            if s.get("session_id"):
                return str(s["session_id"])
            owd = s.get("original_webhook_data")
            if isinstance(owd, dict) and owd.get("session_id"):
                return str(owd["session_id"])
    return ""


def pick(data: Any, key: str, default: Any = "") -> Any:
    """Find `key` on the input, or anywhere in upstream_yields."""
    if isinstance(data, dict):
        if data.get(key) not in (None, ""):
            return data[key]
        uy = data.get("upstream_yields")
        if isinstance(uy, dict):
            if uy.get(key) not in (None, ""):
                return uy[key]
            for v in uy.values():
                if isinstance(v, dict) and v.get(key) not in (None, ""):
                    return v[key]
    return default


def parse_json(resp: Any) -> dict[str, Any]:
    """Tolerant: dict passthrough, JSON string, or first {...} in text."""
    if isinstance(resp, dict):
        return resp
    if isinstance(resp, str):
        try:
            return json.loads(resp)
        except ValueError:
            m = re.search(r"\{.*\}", resp, re.S)
            if m:
                try:
                    return json.loads(m.group(0))
                except ValueError:
                    pass
    return {}


def clamp01(x: Any) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return round(max(0.0, min(1.0, v)), 4)
