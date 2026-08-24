"""Deal Desk — Opportunity & Outreach Liaison (the FINISHER / actuator).

auto_discover matches `deal_desk_agent`. It sits BEHIND the human AE approval
gate. It never approves or sends — it re-checks that a human actually approved,
recovers the lead across the HITL gap, renders the opportunity pack, and records
an append-only ledger entry. It is the concrete "@chain fails closed":

  a) approve RE-CHECK — reaching this agent does NOT mean approved. An
     allow-token allowlist + block-token denylist; an UNKNOWN verdict fails
     closed (blocked).
  b) deterministic invariants a human can't waive (a committable tier, a lead on
     record).
  c) render the real pack to ./out; on a tripped floor, DELETE the partial and
     record status: blocked with reasons — never a half-committed opportunity.
  d) dev-store recovery — after the HITL gate the upstream payload is dropped, so
     it recovers the lead from the session stash / dev store.

Called AFTER the human AE approves (qualification already did the routing), so
this is the pure commit phase: re-check the approval, enforce the floor, commit.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from leafmesh import LeafMeshLogger, chain

try:
    from ._shared import session_stash, store, util
except ImportError:  # pragma: no cover — direct-run fallback
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _shared import session_stash, store, util  # type: ignore

logger = LeafMeshLogger(__name__)

_OUT_DIR = Path("./out")
_APPROVE_TOKENS = frozenset({"approved", "approve", "accept", "accepted", "go",
                             "send", "yes", "ok", "commit", "create_opportunity"})
_BLOCK_TOKENS = frozenset({"rejected", "reject", "no", "deny", "denied", "held",
                           "held_for_review", "hold", "disqualify", "skip"})
_COMMITTABLE_TIERS = frozenset({"hot", "warm"})


def _signal(input_data: dict) -> str:
    """The human verdict, from wherever the SDK delivered it (shape-tolerant)."""
    sources = [input_data]
    up = input_data.get("upstream_yields")
    if isinstance(up, dict):
        sources.extend(v for v in up.values() if isinstance(v, dict))
    for src in sources:
        for key in ("human_message", "human_decision", "decision", "message"):
            val = src.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip().lower()
    return ""


def _is_approved(input_data: dict) -> bool:
    """Fail closed: only an explicit approve token counts; unknown => not approved."""
    sig = _signal(input_data)
    if sig in _BLOCK_TOKENS:
        return False
    return sig in _APPROVE_TOKENS


def _is_blocked(input_data: dict) -> bool:
    return _signal(input_data) in _BLOCK_TOKENS


def _recover_lead(input_data: dict, context: dict) -> dict:
    """Recover the lead across the HITL boundary: upstream → stash → dev store."""
    up = input_data.get("upstream_yields") or {}
    candidates = [input_data]
    if isinstance(up, dict):
        candidates.append(up)
        candidates.extend(v for v in up.values() if isinstance(v, dict))
    for src in candidates:
        if isinstance(src, dict) and src.get("tier") and src.get("lead_id"):
            return src
    sid = util.sid(input_data, context)
    stashed = session_stash.stash_get(sid)
    if stashed.get("tier") and stashed.get("lead_id"):
        return stashed
    lead_id = str(util.pick(input_data, "lead_id") or "")
    q = store.get_qualification(lead_id)
    if q:
        lead = store.get_lead(lead_id)
        return {"lead_id": lead_id, "tier": q.get("tier", ""),
                "icp_fit": q.get("icp_fit", 0), "intent_score": q.get("intent_score", 0),
                "opening": lead.get("opening", ""),
                "sales_briefing": lead.get("sales_briefing", ""),
                "company_domain": lead.get("company_domain", "")}
    return {"lead_id": lead_id}


def _render_pack(lead: dict) -> str:
    """Render the approved opportunity pack to ./out. Returns the path."""
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    lead_id = str(lead.get("lead_id") or "lead")
    path = _OUT_DIR / f"{lead_id}_opportunity_pack.md"
    lines = [
        f"# Opportunity pack — {lead_id}",
        f"Tier: {lead.get('tier','')}  (ICP {lead.get('icp_fit','?')} / "
        f"intent {lead.get('intent_score','?')})",
        f"Account: {lead.get('company_domain','')}",
        "",
        "## Approved opening",
        str(lead.get("opening") or "(AE to draft — no opener on record)"),
        "",
        "## Sales briefing",
        str(lead.get("sales_briefing") or ""),
        "",
        "_Committed to the CRM as an opportunity + queued to the sequencer. Ledgered._",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def _delete_partial(result: dict) -> None:
    p = result.get("pack_path")
    if p:
        Path(p).unlink(missing_ok=True)
        result["pack_path"] = ""


def enforce_commit_floor(result: Any, context: dict) -> dict:
    """The finisher floor — commit ONLY on a real approval; delete on a block."""
    result = result if isinstance(result, dict) else {}
    result.setdefault("block_reasons", [])

    if not result.get("approved"):
        result["status"] = "blocked"
        if _is_blocked(result.get("_input", {})):
            result["block_reasons"].append("AE rejected / held")
        else:
            result["block_reasons"].append("no explicit approval on record (fail closed)")
        _delete_partial(result)
        logger.info(f"[deal_desk] commit floor BLOCKED: {result['block_reasons']}")
        return result

    lead = result.get("_lead") or {}
    tier = str(lead.get("tier") or "").lower()
    if not lead.get("lead_id"):
        result.update(status="blocked", approved=False)
        result["block_reasons"].append("no lead on record to commit")
        _delete_partial(result)
        logger.info(f"[deal_desk] commit floor BLOCKED: {result['block_reasons']}")
        return result
    if tier not in _COMMITTABLE_TIERS:
        result.update(status="blocked", approved=False)
        result["block_reasons"].append(
            f"tier {tier or '(none)'} is not a committable opportunity")
        _delete_partial(result)
        logger.info(f"[deal_desk] commit floor BLOCKED: {result['block_reasons']}")
        return result

    # Passed the floor — render, commit, ledger.
    result["pack_path"] = _render_pack(lead)
    store.record_outbox({"lead_id": lead.get("lead_id"), "action": "create_opportunity",
                         "pack_path": result["pack_path"], "tier": tier})
    store.append_ledger({"lead_id": lead.get("lead_id"), "event": "opportunity_committed",
                         "tier": tier, "approver": "ae_human"})
    result.update(committed=True, opportunity_created=True, status="committed")
    logger.info(f"[deal_desk] committed opportunity {lead.get('lead_id')} "
                f"→ {result['pack_path']}")
    return result


@chain(enforce_commit_floor)
async def deal_desk_agent(llm_response: Any, input_data: dict, context: dict) -> dict:
    input_data = input_data if isinstance(input_data, dict) else {}
    lead = _recover_lead(input_data, context)
    sid = util.sid(input_data, context)
    if lead.get("lead_id") and lead.get("tier"):
        session_stash.stash_put(sid, lead)   # keep recoverable across a replay

    out: dict[str, Any] = {
        "approved": False, "committed": False, "opportunity_created": False,
        "pack_path": "", "status": "", "block_reasons": [],
        "lead_id": str(lead.get("lead_id") or ""),
        "_input": input_data, "_lead": lead,
    }
    if _is_approved(input_data):
        out["approved"] = True             # the floor commits it
    else:
        out["status"] = "blocked"          # not approved → floor records it blocked
    return out
