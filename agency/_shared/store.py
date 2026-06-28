"""Dev-mode store for the sales-orchestration agency.

Stands in for your CRM (lead + account ledger), MAP (prior touches /
engagement), and the cold-lead backlog so the
intake → qualify → route → research → revive chain runs end-to-end
**before any connector is wired**. Replace each read/write with the
matching n8n / CRM connector call in production; the function
signatures are the contract the rest of the mesh reads against.

The two integration points the connector agents already own
(pipeline / nurture / ABM) keep their state in your CRM/MAP — this
store is only the dev stand-in for the LLM agents' context-pulls
(@pre_compose) and their deterministic lifecycle writes (@chain).

  * CRM     → wire ${N8N_ABM_WEBHOOK_URL} into account_record / register_contact
  * MAP     → wire ${N8N_NURTURE_WEBHOOK_URL} into prior_touches / record_touch

Setting those env vars alone does nothing until you wire the calls here.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_DIR = Path("./data")

_FREEMAIL = frozenset({
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "icloud.com",
    "aol.com", "proton.me", "protonmail.com",
})

# Competitor domains — an inbound from one of these is a competitor
# employee, not a buyer (drives the deterministic is_competitor floor).
COMPETITOR_DOMAINS = frozenset({
    "rivalcrm.example", "competastack.example", "foeflow.example",
})

# High-fit tech stack (subset matters for ICP fit).
HIGH_FIT_TECH = frozenset({
    "salesforce", "hubspot", "snowflake", "databricks", "stripe",
    "shopify", "atlassian", "datadog", "okta",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


def _path(k: str) -> Path:
    _DIR.mkdir(parents=True, exist_ok=True)
    return _DIR / f"{k}.json"


def _load(k: str) -> dict[str, Any]:
    p = _path(k)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (ValueError, OSError):
        return {}


def _save(k: str, d: dict[str, Any]) -> None:
    p = _path(k)
    t = p.with_suffix(".json.tmp")
    t.write_text(json.dumps(d, indent=2, default=str))
    t.replace(p)


# ── Seed data — realistic accounts, leads, touches ───────────────────
# Account ledger: firmographics the intake/qualification agents reason
# over. Keyed by company_domain. Mirrors what an enriched CRM holds.
_SEED_ACCOUNTS: dict[str, Any] = {
    "northwind-fintech.example": {
        "company_domain": "northwind-fintech.example",
        "company_name": "Northwind Fintech",
        "firmographics": {"employee_count": 1400, "annual_revenue_usd": 240_000_000,
                          "industry": "fintech", "country": "US"},
        "company_tier": "enterprise",
        "funding": {"stage": "series-c", "last_round_usd": 80_000_000,
                    "last_round_date": "2025-11-02"},
        "funding_signal": True,
        "tech_stack": ["snowflake", "datadog", "okta", "python"],
        "high_fit_tech": ["datadog", "okta", "snowflake"],
        "decision_makers": [
            {"name": "Priya Nair", "title": "VP of Data", "linkedin_url": ""},
            {"name": "Tom Alvarez", "title": "Head of Platform", "linkedin_url": ""},
            {"name": "Dana Wu", "title": "Director of Analytics", "linkedin_url": ""},
        ],
        "competitor_overlap": ["rivalcrm"],
    },
    "brightside-retail.example": {
        "company_domain": "brightside-retail.example",
        "company_name": "Brightside Retail",
        "firmographics": {"employee_count": 180, "annual_revenue_usd": 22_000_000,
                          "industry": "ecommerce", "country": "GB"},
        "company_tier": "mid",
        "funding": {"stage": "series-a", "last_round_usd": 12_000_000,
                    "last_round_date": "2024-03-10"},
        "funding_signal": True,
        "tech_stack": ["shopify", "stripe", "hubspot"],
        "high_fit_tech": ["hubspot", "shopify", "stripe"],
        "decision_makers": [
            {"name": "Owen Reed", "title": "Head of Growth", "linkedin_url": ""},
        ],
        "competitor_overlap": [],
    },
    "tinyshop.example": {
        "company_domain": "tinyshop.example",
        "company_name": "TinyShop",
        "firmographics": {"employee_count": 6, "annual_revenue_usd": 400_000,
                          "industry": "retail", "country": "US"},
        "company_tier": "smb",
        "funding": {"stage": "bootstrapped", "last_round_usd": 0,
                    "last_round_date": ""},
        "funding_signal": False,
        "tech_stack": ["wordpress"],
        "high_fit_tech": [],
        "decision_makers": [],
        "competitor_overlap": [],
    },
}

# Inbound leads — one per routing branch so the demo exercises the
# whole tier × intent matrix. Keyed by lead_id.
_SEED_LEADS: dict[str, Any] = {
    # HOT — enterprise, strong intent, named DM, high-fit stack.
    "lead-hot-001": {
        "lead_id": "lead-hot-001", "source": "demo",
        "company_domain": "northwind-fintech.example",
        "email": "priya.nair@northwind-fintech.example",
        "job_title": "VP of Data", "intent_signal": "demo_request",
        "received_at_utc": _days_ago(0),
        "raw_payload": {"pages_viewed": ["pricing", "security", "integrations"],
                        "campaign": "launch-post-2026", "utm_source": "blog"},
    },
    # WARM with a usable hook — mid-market, moderate intent.
    "lead-warm-002": {
        "lead_id": "lead-warm-002", "source": "webform",
        "company_domain": "brightside-retail.example",
        "email": "owen.reed@brightside-retail.example",
        "job_title": "Head of Growth", "intent_signal": "downloaded_guide",
        "received_at_utc": _days_ago(1),
        "raw_payload": {"pages_viewed": ["blog", "case-studies"],
                        "asset": "scaling-checkout-guide"},
    },
    # COMPETITOR employee — must short-circuit to research, no sales touch.
    "lead-comp-003": {
        "lead_id": "lead-comp-003", "source": "webform",
        "company_domain": "rivalcrm.example",
        "email": "scout@rivalcrm.example",
        "job_title": "Product Manager", "intent_signal": "pricing_page",
        "received_at_utc": _days_ago(0),
        "raw_payload": {"pages_viewed": ["pricing", "pricing", "pricing"]},
    },
    # SPAM — freemail, no company, junk intent.
    "lead-spam-004": {
        "lead_id": "lead-spam-004", "source": "webform",
        "company_domain": "",
        "email": "winabigprize@gmail.com",
        "job_title": "", "intent_signal": "",
        "received_at_utc": _days_ago(0),
        "raw_payload": {"message": "BUY CHEAP FOLLOWERS NOW"},
    },
}

# Cold-lead backlog for the revival sweep — some have a fresh signal
# (revivable), some don't (skipped). last_touch_utc drives the 90d gate.
_SEED_COLD: dict[str, Any] = {
    "lead-cold-101": {
        "lead_id": "lead-cold-101", "company_domain": "brightside-retail.example",
        "email": "owen.reed@brightside-retail.example", "tier": "cold",
        "last_touch_utc": _days_ago(120),
        "new_signal": {"kind": "funding", "evidence": "Series-A extension announced",
                       "ts": _days_ago(5)},
    },
    "lead-cold-102": {
        "lead_id": "lead-cold-102", "company_domain": "northwind-fintech.example",
        "email": "dana.wu@northwind-fintech.example", "tier": "cold",
        "last_touch_utc": _days_ago(200),
        "new_signal": {"kind": "job_change", "evidence": "Promoted to VP Analytics",
                       "ts": _days_ago(12)},
    },
    "lead-cold-103": {
        "lead_id": "lead-cold-103", "company_domain": "tinyshop.example",
        "email": "owner@tinyshop.example", "tier": "cold",
        "last_touch_utc": _days_ago(95),
        "new_signal": None,                     # no signal → skipped
    },
    "lead-cold-104": {
        "lead_id": "lead-cold-104", "company_domain": "brightside-retail.example",
        "email": "ops@brightside-retail.example", "tier": "cold",
        "last_touch_utc": _days_ago(30),        # not cold enough (< 90d) → skipped
        "new_signal": {"kind": "hiring", "evidence": "Hiring 3 RevOps roles",
                       "ts": _days_ago(2)},
    },
}


def _accounts() -> dict[str, Any]:
    s = _load("accounts")
    if not s:
        s = dict(_SEED_ACCOUNTS); _save("accounts", s)
    return s


def _leads() -> dict[str, Any]:
    s = _load("leads")
    if not s:
        s = dict(_SEED_LEADS); _save("leads", s)
    return s


def _cold() -> dict[str, Any]:
    s = _load("cold_leads")
    if not s:
        s = dict(_SEED_COLD); _save("cold_leads", s)
    return s


# ── Account context (intake + qualification @pre_compose) ────────────
def freemail_domain(email: str) -> bool:
    dom = (email or "").split("@")[-1].lower().strip()
    return dom in _FREEMAIL


def derive_domain(email: str) -> str:
    """Company domain from email, unless freemail. PROD: CRM match."""
    dom = (email or "").split("@")[-1].lower().strip()
    if not dom or dom in _FREEMAIL:
        return ""
    return dom


def is_competitor_domain(domain: str) -> bool:
    return (domain or "").lower().strip() in COMPETITOR_DOMAINS


def get_account(company_domain: str) -> dict[str, Any]:
    """Firmographics + DMs + competitor overlap for a domain. PROD: CRM read."""
    return _accounts().get((company_domain or "").lower().strip(), {})


def get_lead(lead_id: str) -> dict[str, Any]:
    return _leads().get(lead_id, {})


def seeded_lead_ids() -> list[str]:
    return sorted(_leads().keys())


def prior_touches(company_domain: str) -> list[dict[str, Any]]:
    """Past outreach to this account (dedupe + warm-up signal). PROD: MAP read."""
    touches = _load("touches").get((company_domain or "").lower().strip(), [])
    return touches if isinstance(touches, list) else []


def contacts_in_window(company_domain: str, days: int = 14) -> int:
    """Distinct contacts seen from a domain inside the ABM window. PROD: CRM."""
    dom = (company_domain or "").lower().strip()
    reg = _load("contacts").get(dom, [])
    if not isinstance(reg, list):
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    n = 0
    for c in reg:
        try:
            if datetime.fromisoformat(c.get("at", "")) >= cutoff:
                n += 1
        except ValueError:
            n += 1
    return n


# ── Lifecycle writes (@chain — deterministic, idempotent) ────────────
def register_contact(company_domain: str, lead_id: str) -> dict[str, Any]:
    """Idempotently record a contact against the account ledger. PROD: CRM."""
    dom = (company_domain or "").lower().strip()
    if not dom:
        return {"registered": False, "contacts_in_window": 0}
    with _LOCK:
        reg = _load("contacts")
        bucket = reg.setdefault(dom, [])
        if not any(c.get("lead_id") == lead_id for c in bucket):
            bucket.append({"lead_id": lead_id, "at": _now()})
        _save("contacts", reg)
    return {"registered": True, "contacts_in_window": contacts_in_window(dom)}


def record_lead(lead: dict[str, Any]) -> None:
    """Persist a processed lead (idempotent on lead_id). PROD: CRM upsert."""
    lid = str(lead.get("lead_id") or "")
    if not lid:
        return
    with _LOCK:
        s = _leads(); s[lid] = {**s.get(lid, {}), **lead, "recorded_at": _now()}
        _save("leads", s)


def record_touch(company_domain: str, lead_id: str, channel: str,
                 note: str = "") -> None:
    dom = (company_domain or "").lower().strip()
    if not dom:
        return
    with _LOCK:
        t = _load("touches")
        t.setdefault(dom, []).append(
            {"lead_id": lead_id, "channel": channel, "note": note, "at": _now()})
        _save("touches", t)


def record_qualification(lead_id: str, tier: str, icp_fit: float,
                         intent_score: float, routed_to: str) -> None:
    """WORM-adjacent dev record of the scoring decision. PROD: CRM activity."""
    with _LOCK:
        q = _load("qualifications")
        q[lead_id] = {"lead_id": lead_id, "tier": tier, "icp_fit": icp_fit,
                      "intent_score": intent_score, "routed_to": routed_to,
                      "at": _now()}
        _save("qualifications", q)


def get_qualification(lead_id: str) -> dict[str, Any]:
    return _load("qualifications").get(lead_id, {})


# ── Cold-lead backlog (revival @pre_compose) ─────────────────────────
def cold_leads_due(min_days_cold: int = 90) -> list[dict[str, Any]]:
    """Leads cold >= min_days, oldest first. PROD: CRM saved search."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=min_days_cold)
    out = []
    for lead in _cold().values():
        try:
            last = datetime.fromisoformat(lead.get("last_touch_utc", ""))
        except ValueError:
            continue
        if last <= cutoff:
            out.append(lead)
    out.sort(key=lambda l: l.get("last_touch_utc", ""))
    return out
