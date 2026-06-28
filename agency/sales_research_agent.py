"""sales_research_agent — competitor intel pack (mode=intel) or
pre-meeting account dossier (mode=dossier), mode-dispatched.

@pre_compose  load_research_seed — pull the account ledger (facts, DMs,
              competitor overlap) for the requested account from the dev
              store so the dossier/intel is grounded in what we already
              know, plus a bounded re-trigger counter so a competitor
              lead can't ping-pong research ⇄ qualification forever.
@chain        score_research_floor — deterministic floors the LLM can't
              waive: re-compute dossier_score from the dossier contents,
              set requires_more_data from the 0.5 gate, and in intel mode
              force requires_more_data=false (intel never re-triggers the
              dossier → opener edge). Bounds the research↔qualification
              back-edge via the session stash and stops at the cap.
"""
from __future__ import annotations

from typing import Any

from leafmesh import LeafMeshLogger, chain, pre_compose

from agency._shared import session_stash, store, util

logger = LeafMeshLogger(__name__)

_MAX_RESEARCH_ROUNDS = 2          # bound research ⇄ qualification ping-pong

_DEFAULTS: dict[str, Any] = {
    "mode": "", "competitors_analysed": [], "intel_records": [],
    "primary_threat": "", "primary_threat_reasoning": "", "briefing": "",
    "ae_briefing_appendix": "", "requires_pricing_objection_prep": False,
    "kb_curation_needed_for": [], "account": "", "domain": "",
    "company_facts": [], "decision_makers": [], "recent_signals": [],
    "competitor_overlap": [], "talking_points": [], "risk_flags": [],
    "dossier_score": 0.0, "requires_more_data": False, "research_briefing": "",
}


def _dispatch_mode(data: Any) -> str:
    explicit = str(util.pick(data, "mode") or "").lower()
    if explicit in ("intel", "competitive_intel"):
        return "intel"
    if explicit in ("dossier", "account_dossier"):
        return "dossier"
    if util.pick(data, "competitors") or util.pick(data, "is_competitor"):
        return "intel"
    return "dossier"


def load_research_seed(data: Any, ctx: Any) -> dict[str, Any]:
    domain = str(util.pick(data, "domain") or util.pick(data, "company") or "")
    account = store.get_account(domain)
    return {
        "mode": _dispatch_mode(data),
        "domain": domain,
        "known_account": account,
        "known_competitor_overlap": account.get("competitor_overlap", []),
        "known_decision_makers": account.get("decision_makers", []),
    }


def _dossier_score(r: dict[str, Any]) -> float:
    """Deterministic completeness score — the floor for requires_more_data."""
    score = 0.0
    if len(r.get("company_facts") or []) >= 3:
        score += 0.15
    if len(r.get("decision_makers") or []) >= 1:
        score += 0.25
    if len(r.get("recent_signals") or []) >= 1:
        score += 0.20
    if len(r.get("talking_points") or []) >= 3:
        score += 0.20
    if len(r.get("competitor_overlap") or []) >= 1:
        score += 0.10
    if not (r.get("risk_flags") or []):
        score += 0.10
    return round(score, 2)


async def score_research_floor(result: dict[str, Any], ctx: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        result = {}
    mode = str(result.get("mode") or "").lower() or "dossier"
    result["mode"] = mode

    if mode == "intel":
        # Intel packs land in audit; NEVER re-trigger the dossier→opener edge.
        result["requires_more_data"] = False
        result["dossier_score"] = 0.0
    else:
        score = _dossier_score(result)
        result["dossier_score"] = score
        # Bound the research ⇄ qualification ping-pong before re-routing back.
        if score >= 0.5:
            session = util.sid(result, ctx)
            rounds = session_stash.bump(session, "research_rounds")
            if rounds > _MAX_RESEARCH_ROUNDS:
                result["requires_more_data"] = True       # stop the loop → terminal
                logger.warning(f"[research] round cap {rounds} hit — holding")
            else:
                result["requires_more_data"] = False
        else:
            result["requires_more_data"] = True

    if not result.get("research_briefing"):
        result["research_briefing"] = (
            f"{mode} pack, dossier_score={result['dossier_score']:.2f}. "
            f"{'Ready for opener.' if not result['requires_more_data'] and mode == 'dossier' else 'Needs review.'}")

    logger.info(f"[research] mode={mode} score={result['dossier_score']:.2f} "
                f"more_data={result['requires_more_data']}")
    return result


@pre_compose(context_processor=load_research_seed)
@chain(score_research_floor)
async def sales_research_agent(llm_response: Any, input_data: Any,
                               context: Any) -> dict[str, Any]:
    out = {**_DEFAULTS}
    llm = util.parse_json(llm_response)
    out.update({k: llm[k] for k in _DEFAULTS if k in llm})
    if not out.get("mode"):
        out["mode"] = _dispatch_mode(input_data)
    if not out.get("domain"):
        out["domain"] = str(util.pick(input_data, "domain") or util.pick(input_data, "company") or "")
    return out
