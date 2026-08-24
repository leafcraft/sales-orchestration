"""lead_intake_agent — normalise any-source lead → canonical Lead, then
enrich with firmographics, funding, tech stack, decision makers.

@pre_compose  load_account_history — pull the account ledger for the lead's
              domain (firmographics, funding, tech stack, DMs, prior
              touches) so enrichment REUSES known account context instead
              of re-fetching / hallucinating it. This is the native-memory
              account-context reuse, made deterministic against the store.
@chain        persist_intake — deterministic lifecycle the LLM can't skip:
                · re-derive company_tier from firmographics (floor)
                · re-flag is_competitor from the domain (floor)
                · upsert the lead into the store (idempotent on lead_id)
                · register the contact against the account ledger (the ABM
                  window count) — idempotent
"""
from __future__ import annotations

from typing import Any

from leafmesh import LeafMeshLogger, chain, compose, pre_compose

from agency._shared import store, util

logger = LeafMeshLogger(__name__)

_DEFAULTS: dict[str, Any] = {
    "lead_id": "", "source": "", "company_domain": "", "email": "",
    "job_title": "", "intent_signal": "", "raw_payload": {},
    "firmographics": {}, "company_tier": "unknown", "funding": {},
    "funding_signal": False, "tech_stack": [], "high_fit_tech": [],
    "decision_makers": [], "decision_maker_count": 0,
    "enrichment_confidence": 0.0, "enrichment_complete": False,
}


def _tier(firmographics: dict[str, Any], has_domain: bool) -> str:
    """Deterministic company_tier from size/revenue — the floor."""
    if not has_domain:
        return "unknown"
    emp = int(firmographics.get("employee_count") or 0)
    rev = int(firmographics.get("annual_revenue_usd") or 0)
    if emp >= 1000 or rev >= 100_000_000:
        return "enterprise"
    if emp >= 100 or rev >= 10_000_000:
        return "mid"
    return "smb"


def load_account_history(data: Any, ctx: Any) -> dict[str, Any]:
    """Pull known account context for the inbound domain (or derive it)."""
    email = str(util.pick(data, "email") or "")
    declared = str(util.pick(data, "company_domain") or "")
    domain = declared or store.derive_domain(email)
    account = store.get_account(domain)
    return {
        "derived_domain": domain,
        "is_freemail": store.freemail_domain(email),
        "is_competitor_domain": store.is_competitor_domain(domain),
        "known_account": account,
        "prior_touches": store.prior_touches(domain),
    }


async def persist_intake(result: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """Floors + idempotent lifecycle writes."""
    if not isinstance(result, dict):
        result = {}

    domain = str(result.get("company_domain") or "")
    firmographics = result.get("firmographics") or {}

    # Floor: re-derive company_tier deterministically (LLM can't waive it).
    result["company_tier"] = _tier(firmographics, bool(domain))

    # Floor: re-flag competitor from the domain.
    if store.is_competitor_domain(domain):
        result["is_competitor"] = True

    # Floor: confidence/complete are numeric and bounded.
    result["enrichment_confidence"] = util.clamp01(result.get("enrichment_confidence"))
    result["enrichment_complete"] = result["enrichment_confidence"] >= 0.5

    # Idempotent lifecycle writes (PROD = CRM upsert + contact register).
    lead_id = str(result.get("lead_id") or "")
    if lead_id:
        store.record_lead({
            "lead_id": lead_id, "company_domain": domain,
            "email": result.get("email", ""), "job_title": result.get("job_title", ""),
            "intent_signal": result.get("intent_signal", ""),
            "company_tier": result["company_tier"],
        })
        if domain:
            reg = store.register_contact(domain, lead_id)
            result["contacts_in_window"] = reg.get("contacts_in_window", 0)

    logger.info(f"[intake] {lead_id or '?'} domain={domain or '(none)'} "
                f"tier={result['company_tier']} "
                f"conf={result['enrichment_confidence']:.2f}")
    return result


def _to_abm(result: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """The ABM coordinator (n8n) only needs mode + identity to register the
    contact against the account ledger — not the whole enrichment block."""
    return {
        "mode": "register",
        "company_domain": result.get("company_domain", ""),
        "lead_id": result.get("lead_id", ""),
        "upstream_yields": {"company_tier": result.get("company_tier", "")},
    }


@pre_compose(context_processor=load_account_history)
@compose(abm_orchestrator_agent=_to_abm)
@chain(persist_intake)
async def lead_intake_agent(llm_response: Any, input_data: Any,
                            context: Any) -> dict[str, Any]:
    out = {**_DEFAULTS}
    llm = util.parse_json(llm_response)
    out.update({k: llm[k] for k in _DEFAULTS if k in llm})

    # Identity / source / payload survive an LLM omission.
    out["lead_id"] = str(out.get("lead_id") or util.pick(input_data, "lead_id") or "")
    out["source"] = str(out.get("source") or util.pick(input_data, "source") or "")
    if not out.get("raw_payload"):
        rp = util.pick(input_data, "raw_payload")
        out["raw_payload"] = rp if isinstance(rp, dict) else (input_data if isinstance(input_data, dict) else {})

    # Domain: honour the LLM unless it's empty, then derive (freemail-safe).
    if not out.get("company_domain"):
        out["company_domain"] = store.derive_domain(str(out.get("email") or util.pick(input_data, "email") or ""))
    out["decision_maker_count"] = len(out.get("decision_makers") or [])
    return out
