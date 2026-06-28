"""lead_qualification_agent — the SDR researcher: scores ICP fit + intent
and drafts the personalised opener in one pass; its wires carry the
tier × intent routing matrix.

@pre_compose  load_lead_context — pull the lead's enrichment, the account
              ledger (firmographics, DMs, competitor overlap) and prior
              touches from the dev store so the LLM scores over REAL
              history instead of being spoon-fed by the conductor.
@chain        enforce_qualification_floors — the deterministic floors the
              LLM must not be able to waive:
                · clamp icp_fit / intent_score / hook_quality to 0..1
                · competitor-domain → is_competitor=true, no sales touch
                · spam → tier forced to spam (drop)
                · no cited signals → hook_quality capped (no hook)
                · tier RE-DERIVED from the score bands — the LLM may name
                  a tier but cannot inflate it past what the scores justify
                · persist the scoring decision to the store (idempotent)
@compose      emit the right payload per downstream — the AE gets the full
              briefing + opener; the nurturer gets only the routing keys;
              research gets the competitor signal; audit gets a flat event.

The tier × intent `can_call` matrix in config.yaml reads the floored
`tier` / `is_competitor` / `hook_quality` keys — so routing is governed
by this Python floor, not by whatever the LLM wishes were true.
"""
from __future__ import annotations

from typing import Any

from leafmesh import LeafMeshLogger, chain, compose, pre_compose

from agency._shared import store, util

logger = LeafMeshLogger(__name__)

_VALID_TIERS = ("cold", "warm", "hot", "spam")

_DEFAULTS: dict[str, Any] = {
    "icp_fit": 0.0, "intent_score": 0.0, "tier": "cold", "reasons": [],
    "is_competitor": False, "sales_briefing": "", "opening": "",
    "cited_signals": [], "hook_quality": 0.0, "lead_id": "",
}


def _derive_tier(icp_fit: float, intent_score: float) -> str:
    """Deterministic tier band from the two scores. The single source of
    truth for tier — the LLM's named tier is only honoured when it does
    NOT exceed this band (see enforce_qualification_floors)."""
    total = icp_fit + intent_score
    if total < 0.4 and intent_score < 0.1:
        return "spam"
    if total < 1.0:
        return "cold"
    if total < 1.5:
        return "warm"
    return "hot"


_TIER_RANK = {"spam": 0, "cold": 1, "warm": 2, "hot": 3}


def load_lead_context(data: Any, ctx: Any) -> dict[str, Any]:
    """Pull enrichment + account ledger + prior touches for this lead."""
    company_domain = str(util.pick(data, "company_domain") or "")
    email = str(util.pick(data, "email") or "")
    if not company_domain and email:
        company_domain = store.derive_domain(email)
    account = store.get_account(company_domain)
    return {
        "lead_id": str(util.pick(data, "lead_id") or ""),
        "company_domain": company_domain,
        "email": email,
        "job_title": str(util.pick(data, "job_title") or ""),
        "intent_signal": str(util.pick(data, "intent_signal") or ""),
        "company_tier": str(util.pick(data, "company_tier") or account.get("company_tier", "")),
        "firmographics": util.pick(data, "firmographics") or account.get("firmographics", {}),
        "high_fit_tech": util.pick(data, "high_fit_tech") or account.get("high_fit_tech", []),
        "decision_makers": util.pick(data, "decision_makers") or account.get("decision_makers", []),
        "competitor_overlap": account.get("competitor_overlap", []),
        "prior_touches": store.prior_touches(company_domain),
        "is_competitor_domain": store.is_competitor_domain(company_domain),
    }


async def enforce_qualification_floors(result: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """Deterministic floors the LLM cannot waive. Runs after the agent."""
    if not isinstance(result, dict):
        result = {}

    icp = util.clamp01(result.get("icp_fit"))
    intent = util.clamp01(result.get("intent_score"))
    hook = util.clamp01(result.get("hook_quality"))
    cited = result.get("cited_signals") or []
    result["icp_fit"], result["intent_score"] = icp, intent

    # Floor: no cited signals → hook cannot exceed 0.4 (no signal, no hook).
    if not cited:
        hook = min(hook, 0.4)
    result["hook_quality"] = hook

    # Floor: competitor domain → flag it, no sales touch (research instead).
    domain = str(result.get("company_domain") or "")
    if store.is_competitor_domain(domain):
        result["is_competitor"] = True
    result["is_competitor"] = bool(result.get("is_competitor", False))

    # Floor: tier RE-DERIVED from scores; the LLM may NAME a tier but
    # never inflate it above the band the scores justify.
    derived = _derive_tier(icp, intent)
    named = str(result.get("tier") or "").strip().lower()
    if named not in _VALID_TIERS:
        named = derived
    # Honour the LLM only if it did not over-promote past the band.
    result["tier"] = named if _TIER_RANK[named] <= _TIER_RANK[derived] else derived

    # Floor: a competitor is never a sales tier — but never auto-spam'd
    # (the AE still wants the intel). Leave tier; routing sends to research.

    # Floor: sales_briefing is never empty.
    if not result.get("sales_briefing"):
        action = {"hot": "AE direct call today", "warm": "SDR sequence + manager review",
                  "cold": "automated nurture", "spam": "drop"}[result["tier"]]
        result["sales_briefing"] = (
            f"Tier {result['tier']} (ICP {icp:.2f} / intent {intent:.2f}). "
            f"Recommended: {action}.")

    # Floor: spam / competitor → no opener drafted.
    if result["tier"] == "spam" or result["is_competitor"]:
        result["opening"] = ""

    # Persist the decision (idempotent dev write; PROD = CRM activity).
    lead_id = str(result.get("lead_id") or "")
    if lead_id:
        store.record_qualification(lead_id, result["tier"], icp, intent,
                                   routed_to="(matrix)")

    logger.info(f"[qualify] {lead_id or '?'} tier={result['tier']} "
                f"icp={icp:.2f} intent={intent:.2f} hook={hook:.2f} "
                f"competitor={result['is_competitor']}")
    return result


def _to_ae(result: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """The AE owns the opportunity — give them everything to act now."""
    return {
        "lead_id": result.get("lead_id", ""),
        "tier": result.get("tier", ""),
        "icp_fit": result.get("icp_fit", 0.0),
        "intent_score": result.get("intent_score", 0.0),
        "sales_briefing": result.get("sales_briefing", ""),
        "opening": result.get("opening", ""),
        "cited_signals": result.get("cited_signals", []),
    }


def _to_sdr(result: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """The SDR reviews/sends the sequence — briefing + opener + hook score."""
    return {
        "lead_id": result.get("lead_id", ""),
        "tier": result.get("tier", ""),
        "sales_briefing": result.get("sales_briefing", ""),
        "opening": result.get("opening", ""),
        "hook_quality": result.get("hook_quality", 0.0),
    }


def _to_nurturer(result: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """The nurturer (n8n) only needs the routing keys to enrol the lead."""
    return {
        "mode": "enrol",
        "lead_id": result.get("lead_id", ""),
        "tier": result.get("tier", ""),
        "upstream_yields": {"hook_quality": result.get("hook_quality", 0.0)},
    }


def _to_research(result: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """Research desk needs the competitor signal, not the sales briefing."""
    return {
        "mode": "intel",
        "lead_id": result.get("lead_id", ""),
        "company": result.get("company_domain", ""),
        "domain": result.get("company_domain", ""),
        "upstream_yields": {"competitor_overlap": result.get("cited_signals", [])},
    }


def _to_audit(result: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """Audit gets a flat, self-describing event (spam terminus)."""
    return {
        "session_id": util.sid(result, ctx),
        "payload": {"event": "qualification", "lead_id": result.get("lead_id", ""),
                    "tier": result.get("tier", ""), "is_competitor": result.get("is_competitor", False)},
    }


@pre_compose(context_processor=load_lead_context)
@compose(
    ae_human=_to_ae,
    sdr_human=_to_sdr,
    deal_nurturer_agent=_to_nurturer,
    sales_research_agent=_to_research,
    sales_audit_logger_agent=_to_audit,
)
@chain(enforce_qualification_floors)
async def lead_qualification_agent(llm_response: Any, input_data: Any,
                                   context: Any) -> dict[str, Any]:
    """Merge the LLM's scoring/personalisation with the lead identity; the
    @chain then enforces the floors and the @compose shapes per downstream."""
    out = {**_DEFAULTS}
    llm = util.parse_json(llm_response)
    out.update({k: llm[k] for k in _DEFAULTS if k in llm})

    # Identity + domain must survive even if the LLM dropped them
    # (the floors and routing depend on them).
    out["lead_id"] = str(out.get("lead_id") or util.pick(input_data, "lead_id") or "")
    domain = str(util.pick(input_data, "company_domain") or "")
    if not domain:
        domain = store.derive_domain(str(util.pick(input_data, "email") or ""))
    out["company_domain"] = domain
    return out
