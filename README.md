# sales-orchestration — Sales-Orchestration Pod

A pod of digital employees + a human sales roster that runs an inbound lead end
to end — **any-source lead → case opened → normalised & enriched → scored +
personalised → tier × intent routing → AE/SDR handoff → opportunity committed →
live status** — with a human on every gate, a finisher that fails closed, and the
systems (Salesforce / HubSpot / Outreach) as tools behind n8n connectors, never
members.

**Read `PRD.md`** for the full agent-by-agent spec. This is a **pod-standard**
build (SDK 2.4.131): a team of self-reliant agents, not a pipeline.

```bash
cp env .env && pip install -r requirements.txt && python main.py
```

## Story — one lead, end to end

**Priya Nair**, a VP of Data at a 1,400-person fintech, submits the marketing
site's "Book a demo" form. The webhook fires the `demo_request` entry point.

1. **Sol** (`sales_coordinator_agent`) opens the lead case, keeps the `lead_id`,
   records the stage, and hands it to intake — Sol owns the case and answers
   "where is this lead?" but never scores or approves anything itself.
2. **`lead_intake_agent`** normalises her submission into a canonical `Lead`
   (lowercases the email, derives `company_domain` because it is not freemail),
   then enriches it: 1,400 employees → `enterprise`, a Series-C funding signal,
   Snowflake + Datadog (both high-fit), three named decision makers. Native
   cross-session memory means the next lead from that domain reuses this context.
   It hands off to qualification and, in parallel, registers the contact with the
   ABM coordinator.
3. **`lead_qualification_agent`** (the SDR researcher) scores ICP fit + intent
   and drafts a signal-cited opener in one pass → `tier: hot`. Its own tier ×
   intent `can_call` matrix routes hot → **`ae_human`**. The scores and tier are
   re-derived by a deterministic floor the LLM cannot inflate.
4. **`ae_human`** — a real Account Executive — reviews the briefing + opener and
   approves (a default-deny gate: silence for 60 min holds the lead for review).
5. **Deal Desk** (`deal_desk_agent`, the FINISHER) re-checks that a human
   actually approved (allow/deny tokens, **unknown fails closed**), recovers the
   lead across the HITL gap, enforces invariants (a committable tier, a lead on
   record), renders the **opportunity pack to `./out/`**, deletes it on a tripped
   floor, and appends the ledger — never a half-committed opportunity.
6. **`sales_audit_logger_agent`** hash-chains every routing, handoff, approval,
   and held gate. Tamper-evident, the terminus of every branch.

A *cold* lead with a usable hook routes to `deal_nurturer_agent` for a MAP drip
(graduating to an AE at engagement ≥ 0.70); a *competitor* employee to the
super-agent `sales_research_agent` for an intel pack; *spam* straight to audit.
`lead_revival_agent` sweeps 90-day-cold leads every Tuesday, fanning the backlog
across parallel instances that each claim a disjoint batch.

## Why it works in an organization

Inbound leads rot in the gap between marketing and sales — a hot lead sits past
its SLA, a cold lead that quietly turned warm goes unre-checked, three reps
cold-email the same account, an AE walks into a meeting with no dossier. This pod
closes those gaps the only honest way:

- **The tier is earned, not claimed.** Qualification re-derives `tier` from the
  score bands in Python — the LLM may *name* a tier but can never inflate it past
  what the scores justify, and the routing matrix reads the *floored* keys. Spam
  and competitor cases short-circuit before any sales touch.
- **The finisher fails closed.** Reaching Deal Desk does not mean approved — it
  re-checks the human verdict against an allow/deny list, treats an **unknown
  verdict as a block**, and deletes a half-rendered pack if an invariant trips.
- **Silence never advances a lead.** Every human gate default-denies on timeout
  (held → audit); the Manager supervisor escalates stalls to the Sales Manager.
- **State lives in your systems.** Pipeline, nurture, and the account ledger live
  in your CRM/MAP behind n8n connectors — no template SQLite pretending to be a
  system of record.
- **Every decision is auditable.** A hash-chained WORM ledger records every
  route, handoff, approval, and held gate.

ROI: faster speed-to-lead, higher MQL→SQL conversion, fewer dropped leads, and a
tamper-evident record of every routing decision for RevOps.

## Configuration — what to set, in three tiers

Everything is set in `.env` (`cp env .env`). The **whole LLM chain (coordinate →
intake → qualify → route → research → revive) runs on Tier 1 alone** against the
seed dev store (`./data`); enrichment reads, the pipeline/nurture/ABM connectors,
and the CRM commit use dev stand-ins that **announce themselves** until you wire
Tiers 2–3.

### Tier 1 — required to boot (dev mode)
| Setting | For | Notes |
|---|---|---|
| `LEAFMESH_LICENSE_KEY` | LeafMesh runtime | **Required.** |
| `OPENAI_API_KEY` | Sol + intake + revival + Manager (`gpt-4o-mini`) | **Required.** |
| `ANTHROPIC_API_KEY` | qualification + research (`claude-sonnet-4-6`) | **Required.** |
| `REDIS_HOST` / `PORT` / `PASSWORD` | State store | Defaults `localhost:6379`. `docker run -d -p 6379:6379 redis:7-alpine`. |
| `HITL_OUTBOUND_URL` | Where human members are notified | Defaults to a local stub. |

### Tier 2 — real enrichment for the research desk
| Setting | Enables |
|---|---|
| `ENRICHMENT_MCP_URL` / `_TOKEN` | Real firmographics / DM / competitor reads (ZoomInfo / Clearbit / Explorium) |

> ⚠️ The SDK rejects an `mcp` block with an **empty** URL at load, so the block
> on `sales_research_agent` ships **commented** in `configs/config.yaml`. Fill
> the URL, then uncomment. The day-0 dev tools are the fallback contract.

### Tier 3 — n8n connectors (your CRM/MAP owns the state)
| Setting | Connector agent | Drives |
|---|---|---|
| `N8N_PIPELINE_HEALTH_WEBHOOK_URL` | `pipeline_health_agent` | opportunity stages from your CRM |
| `N8N_NURTURE_WEBHOOK_URL` | `deal_nurturer_agent` | enrol / sweep nurture in your MAP |
| `N8N_ABM_WEBHOOK_URL` | `abm_orchestrator_agent` | the account/contact ledger in your CRM |
| `PAGER_WEBHOOK` / `SLACK_SALES_CHANNEL` | Manager escalation | PagerDuty + Slack SLA alerts |

The connector crons ship **commented out** (a cron firing against an empty
`webhook_url` would error) — wire the URL, add a `timezone:`, then uncomment. The
only always-on cron is `lead_revival_agent` (Tue 10:00 `Asia/Kolkata`).

## The team (13 members)

| Agent | Role (human job title) | Responsibilities | Can perform |
|---|---|---|---|
| `sales_coordinator_agent` | Lead Desk Coordinator | Opens the lead case, orchestrates the pod, keeps live status, single point of contact | LLM (gpt-4o-mini); → intake (open_case), Sales Manager (escalate); **never scores or approves** |
| `lead_intake_agent` | Lead Intake & Enrichment Researcher | Normalise any-source lead → canonical `Lead` (freemail guard, domain derivation); enrich firmographics, funding, tech stack, decision makers | LLM + **cross-session memory**; `@pre_compose` account-history pull; `@chain` tier floor + idempotent upsert; `@compose` ABM register |
| `lead_qualification_agent` | SDR Researcher (Scoring & Personalisation) | Score ICP fit + intent → `tier`; draft a signal-cited opener in the same pass; route on the tier × intent matrix | LLM + **playbook** (route / nurture) + **memory**; `@chain` score/tier/hook/competitor/spam floors; `@compose` per-downstream; stashes for the finisher |
| `sales_research_agent` | Sales Research Desk | Mode-dispatched: competitor intel pack (`intel`) or pre-meeting account dossier (`dossier`); score completeness; flag KB gaps | LLM + **super_agent** (autonomous plan/execute/verify) + dev-store tools; `@chain` dossier-score floor + bounded research↔qualification loop |
| `lead_revival_agent` | Lead Revival Specialist | Weekly sweep of 90-day-cold leads for fresh intent (job moves, funding, hiring); cap revivals at 20 | LLM + **instances: 3** + **atomic claim tool** + **timezone** cron; `@chain` 20-cap floor; `@compose` re-derives the mean under the merge |
| `deal_desk_agent` | Opportunity & Outreach Liaison | Re-check the AE approval, commit the opportunity, queue the approved outreach, ledger it | Programmatic **FINISHER**; approve-token re-check → invariants → render pack → **delete-on-block** → WORM ledger |
| `pipeline_health_agent` | Pipeline Health Analyst | SLA/queue sweep; opportunity-stage state from your CRM; idle warnings; per-rep coverage | Programmatic (n8n); → Sales Manager (escalate) |
| `deal_nurturer_agent` | Nurture / Demand-Gen Coordinator | Enrol mid-funnel leads into MAP drip sequences; graduate on engagement ≥ 0.70 | Programmatic (n8n); → AE (graduated) → the finisher |
| `abm_orchestrator_agent` | ABM / Account Coordinator | Register contacts; flip to coordinated ABM at 3+ contacts / 14d; assign one AE; dedup touches | Programmatic (n8n); → AE (activation), audit |
| `ae_human` | Account Executive (Human) | Owns hot leads; approves the routed lead for commit | Human gate (60 min, default-deny → held → audit); → the finisher on approval |
| `sdr_human` | Sales Development Representative (Human) | Reviews high-tier / low-hook sequences before send | Human gate (30 min, default-deny → held → audit) |
| `sales_manager_human` | Sales Manager (Human) | Accountable owner — escalation, queue rebalancing, hold-for-review | Human gate (4 h); the Manager's escalation target |
| `sales_audit_logger_agent` | Audit & Compliance Clerk | Hash-chains every routing, handoff, approval, and held gate | External (custom sink); terminus |

The **LeafMesh Manager** supervises — it reads every hand-off and escalates
SLA breaches / stalls / contract violations to the Sales Manager (and pages
PagerDuty / posts Slack) automatically.

## Run it

```bash
pip install -r requirements.txt          # core LeafMesh runs the pod day-0
docker run -d -p 6379:6379 redis:7-alpine
cp env .env                              # fill at least Tier 1
python validate_config.py                # pre-flight: wiring, yields, dead-code
python -m pytest tests/ -q               # floors fire, finisher fails closed, seeds
python main.py                           # API at http://127.0.0.1:18820/docs
```

Drive a hot lead through the pod (day-0, against the seed store — no connector):

```bash
curl -X POST http://127.0.0.1:18820/api/mesh/call \
  -H "Content-Type: application/json" \
  -d '{"entry_point":"demo_request",
       "input_data":{"lead_id":"lead-hot-001","source":"demo",
                     "email":"priya.nair@northwind-fintech.example",
                     "job_title":"VP of Data","intent_signal":"demo_request",
                     "raw_payload":{"campaign":"launch-post-2026"}}}'
```

A competitor lead (`scout@rivalcrm.example`) short-circuits to the research desk;
a freemail spam submit (`winabigprize@gmail.com`) drops straight to audit — both
governed by the `@chain` floor, not the prompt. On AE approval, Deal Desk renders
the opportunity pack to `./out/` and appends `./data/sales_ledger.json`.

> Packaging note: `pip install leafmesh` (core) includes all LLM providers and
> runs the pod. For the real enrichment MCP add `leafmesh[mcp]`; for the n8n
> connectors nothing extra is needed. Avoid `leafmesh[all]` on Python 3.12+ (it
> pulls `cchardet`, which has no wheel) — add only the specific extras you need.

---

*Built with `create-leafmesh`. The config is the department; the PRD is the brief.*
*Design doctrine: `.claude/skills/leafmesh/building-agents-thoroughly.md`.*
