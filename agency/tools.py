"""Global tools for the sales-orchestration pod.

Day-0 tool surfaces that read the seed dev store so the pod runs with NO
connector wired, and **each announces itself**: when there is no real source and
no seed, it returns `available: false` and says why — never a synthetic success
that looks like a real read. To go live, create the vault record
'enrichment_mcp' (Infrastructure → Integrations → MCP) and uncomment the
enrichment `mcp` block in the configuration (each named action becomes its own
namespaced tool); these dev tools are the fallback contract. "Wired" is decided
by that vault record existing — nothing in .env.

  * research tools   → sales_research_agent's account-ledger reads.
  * claim_cold_leads → the atomic claim that fans lead_revival_agent's backlog
    out across its parallel copies (each copy claims a DISJOINT batch).
"""
import os

from leafmesh import global_tool, LeafMeshLogger, connection_rows
from leafmesh.vault.refs import UnresolvedVaultRef

try:
    from ._shared import store
except ImportError:  # pragma: no cover — direct-run fallback
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _shared import store  # type: ignore

logger = LeafMeshLogger(__name__)


ENRICHMENT_RECORD = "enrichment_mcp"
_NOT_WIRED = (f"no seed account for this domain, and the vault record "
              f"'{ENRICHMENT_RECORD}' does not exist (Infrastructure → Integrations → MCP)")


async def _enrichment_wired() -> bool:
    """True when the vault record the enrichment MCP block uses exists.

    connection_rows raises UnresolvedVaultRef when there is no such record →
    not wired. Any other error (the record exists but is not row-shaped, or
    this agent may not read it) still means the record exists → wired.
    """
    try:
        await connection_rows(ENRICHMENT_RECORD)
        return True
    except UnresolvedVaultRef:
        return False
    except PermissionError:  # SecretNotAllowed: the record exists; it only limits which agents read it
        return True


@global_tool(category="research")
async def get_account_facts(company_domain: str) -> dict:
    """Read known firmographics + funding + tech stack for an account domain.

    Reads the seed account ledger when no enrichment connector is wired.
    Announces `available: false` when there is genuinely nothing on record.

    Args:
        company_domain: The account domain (e.g. "northwind-fintech.example").
    """
    acct = store.get_account(str(company_domain).strip().lower())
    if not acct:
        if await _enrichment_wired():
            return {"available": False,
                    "reason": "enrichment is wired — use the enrichment_* MCP tools for this domain"}
        return {"available": False, "reason": _NOT_WIRED}
    logger.info(f"get_account_facts domain={company_domain} available=True")
    return {"available": True, "company_domain": acct.get("company_domain", ""),
            "firmographics": acct.get("firmographics", {}),
            "funding": acct.get("funding", {}),
            "tech_stack": acct.get("tech_stack", []),
            "company_tier": acct.get("company_tier", "")}


@global_tool(category="research")
async def list_decision_makers(company_domain: str) -> dict:
    """List known decision makers (name, title) for an account domain.

    Args:
        company_domain: The account domain to look up.
    """
    acct = store.get_account(str(company_domain).strip().lower())
    if not acct:
        return {"available": False, "reason": _NOT_WIRED}
    return {"available": True, "decision_makers": acct.get("decision_makers", [])}


@global_tool(category="research")
async def list_competitor_overlap(company_domain: str) -> dict:
    """List competitors this account shows usage / interest in.

    Args:
        company_domain: The account domain to look up.
    """
    acct = store.get_account(str(company_domain).strip().lower())
    if not acct:
        return {"available": False, "reason": _NOT_WIRED}
    return {"available": True, "competitor_overlap": acct.get("competitor_overlap", [])}


@global_tool(category="revival")
def claim_cold_leads(batch_size: int = 5) -> dict:
    """Atomically claim a DISJOINT batch of the current cold-lead revival sweep.

    Each parallel copy of lead_revival_agent calls this to pull its own slice of
    the backlog, so the copies split the sweep instead of duplicating it. Returns
    `available: false` when the sweep queue is empty (all leads already claimed).

    Args:
        batch_size: How many cold leads to claim (default 5).
    """
    try:
        n = max(1, int(batch_size))
    except (TypeError, ValueError):
        n = 5
    batch = store.claim_cold_leads(n)
    if not batch:
        return {"available": False, "reason": "no unclaimed cold leads left in this sweep"}
    logger.info(f"claim_cold_leads claimed={len(batch)}")
    return {"available": True, "claimed": batch, "claimed_count": len(batch)}
