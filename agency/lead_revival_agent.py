"""lead_revival_agent — weekly sweep of 90d+ cold leads for fresh intent.

@pre_compose  load_cold_backlog — pull the cold-lead backlog (>= 90 days
              since last touch) from the dev store, each with whatever new
              signal we have on record, so the LLM reasons over the REAL
              backlog instead of inventing leads to revive.
@chain        cap_revivals — the deterministic revival cap the LLM must not
              be able to waive: a lead is only revivable if it carries a
              concrete new signal; the list is hard-capped at 20 (protect
              the SDR queue), keeping the highest-confidence entries; the
              counts are recomputed from the capped list.
"""
from __future__ import annotations

from typing import Any

from leafmesh import LeafMeshLogger, chain, compose, pre_compose

from agency._shared import store, util

logger = LeafMeshLogger(__name__)

_REVIVAL_CAP = 20          # protect the SDR queue — never revive more per sweep
_MIN_DAYS_COLD = 90

_DEFAULTS: dict[str, Any] = {
    "revivable_leads": [], "new_signals_summary": "", "total_revived": 0,
    "confidence_avg": 0.0, "skipped_no_signal": 0,
}


def load_cold_backlog(data: Any, ctx: Any) -> dict[str, Any]:
    due = store.cold_leads_due(_MIN_DAYS_COLD)
    return {
        "cold_leads": due,
        "cold_lead_count": len(due),
        "min_days_cold": _MIN_DAYS_COLD,
        "revival_cap": _REVIVAL_CAP,
    }


async def cap_revivals(result: dict[str, Any], ctx: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        result = {}
    revivable = result.get("revivable_leads")
    if not isinstance(revivable, list):
        revivable = []

    # Floor: only keep entries that carry a concrete signal (no "just in case").
    kept = [r for r in revivable
            if isinstance(r, dict) and (r.get("signal") or r.get("revival_reasoning"))]

    # Floor: hard cap at _REVIVAL_CAP, highest confidence first.
    def _conf(r: dict[str, Any]) -> float:
        return util.clamp01(r.get("confidence", r.get("confidence_avg", 0)))
    kept.sort(key=_conf, reverse=True)
    if len(kept) > _REVIVAL_CAP:
        logger.info(f"[revival] capping {len(kept)} → {_REVIVAL_CAP}")
        kept = kept[:_REVIVAL_CAP]

    result["revivable_leads"] = kept
    result["total_revived"] = len(kept)
    if kept:
        result["confidence_avg"] = round(sum(_conf(r) for r in kept) / len(kept), 4)
    else:
        result["confidence_avg"] = 0.0
    try:
        result["skipped_no_signal"] = max(0, int(result.get("skipped_no_signal") or 0))
    except (TypeError, ValueError):
        result["skipped_no_signal"] = 0
    if not result.get("new_signals_summary"):
        result["new_signals_summary"] = (
            f"{len(kept)} cold lead(s) revived on fresh signals "
            f"(avg confidence {result['confidence_avg']:.2f}).")

    logger.info(f"[revival] revived={result['total_revived']} "
                f"skipped={result['skipped_no_signal']}")
    return result


def _reshape_instances(result: dict[str, Any]) -> dict[str, Any]:
    """Under instances_handoff: last the SDK SUMS numbers across the parallel
    copies — total_revived summing is correct (disjoint batches), but a summed
    confidence_avg is nonsense. Re-derive the weighted mean from the per-copy
    detail on result['_instances'] (present only when >1 copy ran)."""
    inst = result.get("_instances") if isinstance(result, dict) else None
    if isinstance(inst, dict):
        copies = [c for c in (inst.get("results") or {}).values() if isinstance(c, dict)]
        num = sum(float(c.get("total_revived") or 0) * util.clamp01(c.get("confidence_avg"))
                  for c in copies)
        den = sum(float(c.get("total_revived") or 0) for c in copies)
        result["confidence_avg"] = round(num / den, 4) if den > 0 else 0.0
    return result


def _to_sdr(result: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """The SDR gets the revived batch with a correctly-averaged confidence."""
    r = _reshape_instances(dict(result))
    return {
        "revivable_leads": r.get("revivable_leads", []),
        "total_revived": r.get("total_revived", 0),
        "confidence_avg": r.get("confidence_avg", 0.0),
        "new_signals_summary": r.get("new_signals_summary", ""),
    }


def _to_audit(result: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """Audit gets a flat, self-describing event (the no-revivals terminus)."""
    r = _reshape_instances(dict(result))
    return {
        "session_id": util.sid(result, ctx),
        "payload": {"event": "lead_revival",
                    "total_revived": r.get("total_revived", 0),
                    "confidence_avg": r.get("confidence_avg", 0.0),
                    "skipped_no_signal": r.get("skipped_no_signal", 0)},
    }


@pre_compose(context_processor=load_cold_backlog)
@compose(sdr_human=_to_sdr, sales_audit_logger_agent=_to_audit)
@chain(cap_revivals)
async def lead_revival_agent(llm_response: Any, input_data: Any,
                             context: Any) -> dict[str, Any]:
    out = {**_DEFAULTS}
    llm = util.parse_json(llm_response)
    out.update({k: llm[k] for k in _DEFAULTS if k in llm})
    return out
