# sales-orchestration — Sales Orchestration (lead → handoff)

An inbound-sales department, expressed as a LeafMesh agency. A CRO reading
`configs/config.yaml` sees their team: an intake/enrichment researcher, an
SDR researcher who scores and personalises, a pipeline-health desk, a
sales-research desk, nurture and ABM coordinators, the SDR / AE / sales-manager
human roster, and a hash-chained WORM audit clerk. Pipeline, sequence and
account state live in **your** CRM and MAP (Salesforce / HubSpot / Outreach)
behind n8n connectors — never in template SQLite. The four LLM judgment roles
carry real Python (`agency/<name>_agent.py`) for the work that *must* be code:
self-reliant context-pulls (`@pre_compose`), deterministic floors the LLM can't
waive (`@chain`), and per-downstream payload shaping (`@compose`). A seeded dev
store (`agency/_shared/store.py`) makes the whole chain run with no connectors;
the audit sink (`agency/_shared/audit_logger.py`) is the WORM clerk.

```bash
cp env .env && pip install -r requirements.txt && python main.py
```

## 0. Run it on day 0 — no connectors needed

The four LLM judgment roles are **self-reliant**: each pulls its own context
(`@pre_compose`) from a seeded dev store and enforces its own deterministic
floors (`@chain`) the LLM can't waive. The store
(`agency/_shared/store.py`) ships seeded with realistic leads — Priya at
enterprise fintech Northwind (→ `hot`), a mid-market warm lead with a hook, a
competitor employee (→ research short-circuit), a spam freemail submit (→
drop) — so the **whole chain runs against it before any webhook is wired**.

```bash
python validate_config.py          # pre-flight: wiring, yields, dead-code
python -m pytest tests/ -q         # floors fire, gate holds, store seeds
python main.py                     # API at http://127.0.0.1:18820/docs
```

Then drive a hot lead through intake → qualification → AE handoff. The
`@pre_compose` enriches Priya from the seeded account ledger; the `@chain`
floor scores + clamps + derives `tier: hot`; the tier × intent matrix routes
to `ae_human`; the WORM clerk records it:

```bash
curl -X POST http://127.0.0.1:18820/api/mesh/call \
  -H "Content-Type: application/json" \
  -d '{"entry_point":"demo_request",
       "input_data":{"lead_id":"lead-hot-001",
                     "source":"demo",
                     "email":"priya.nair@northwind-fintech.example",
                     "job_title":"VP of Data",
                     "intent_signal":"demo_request",
                     "raw_payload":{"campaign":"launch-post-2026"}}}'
```

A competitor lead (`scout@rivalcrm.example`) short-circuits to
`sales_research_agent`; a freemail spam submit (`winabigprize@gmail.com`)
drops straight to audit — both governed by the `@chain` floor, not the prompt.
You can also exercise the module floors directly without a license:

```bash
python -m pytest tests/test_agent_logic.py -q   # 19 module-smoke assertions
```

In production, each store read/write becomes the matching CRM/MAP connector
call (the function signatures in `store.py` are the contract); the connector
agents (pipeline / nurture / ABM) already own their state in your systems.

---

## 1. Story — one lead, end to end

**Priya Nair**, a VP of Data at a 1,400-person fintech, fills in the "Book a
demo" form on the marketing site after reading a launch post. The form webhook
fires the `demo_request` entry point.

1. **`lead_intake_agent`** normalises her submission into a canonical `Lead`
   (lowercases the email, derives `company_domain` from it because it is *not*
   a freemail address), then enriches it: firmographics (1,400 employees →
   `company_tier: enterprise`), a Series-C funding signal, a tech stack that
   includes Snowflake and Datadog (both on the high-fit list), and three named
   decision makers. Native cross-session memory means the *next* lead from the
   same domain reuses this account context for free. It hands off to
   `lead_qualification_agent` and, in parallel, registers the contact with
   `abm_orchestrator_agent`.
2. **`lead_qualification_agent`** (the SDR researcher) scores the lead against
   the ICP knowledge base and reads intent in one pass: high ICP fit + strong
   intent → **`tier: hot`**. In the *same* call it drafts a personalised opener
   citing two real signals (the launch post she read, the Snowflake stack), so
   `hook_quality` is high. Its own `can_call` matrix carries the routing: `tier
   == 'hot' and is_competitor == false` → **`ae_human`**.
3. **`ae_human`** — a real Account Executive — gets the lead plus the
   sales briefing and the opener in their inbox (a default-deny human gate; if
   no AE responds in 60 minutes the lead escalates to the sales manager). The
   AE accepts, creates the opportunity, and routes the decision to the audit
   clerk.
4. **`sales_audit_logger_agent`** appends a hash-chained WORM entry recording
   the route and the handoff. The chain makes any later tampering detectable.

Meanwhile `abm_orchestrator_agent` has noted Priya is the third contact from
that domain inside the 14-day window, so it flips the account into coordinated
ABM mode, assigns a single owning AE, and requests marketing air cover — all in
your CRM, via n8n.

A *cold* version of Priya (low intent, but a usable hook) would instead route
to `deal_nurturer_agent` for a drip sequence in your MAP, graduating to an AE
only when engagement crosses 0.70. A *competitor* employee routes to
`sales_research_agent` for an intel pack instead of a sales touch. Spam
short-circuits straight to audit.

## 2. Why it works in an organization

Inbound leads rot in the gap between marketing and sales. The expensive
failures are all timing and consistency: a hot lead that sits unworked past its
SLA, a cold lead that quietly turned warm (job change, funding round) that
nobody re-checked, three reps cold-emailing the same account, an AE walking into
a meeting with no dossier.

This agency closes those gaps deterministically. Every lead is scored,
personalised and routed within seconds of arrival; the tier × intent matrix is
explicit config, not tribal knowledge, so routing is auditable and uniform
across the team. The pipeline-health desk sweeps for SLA breaches and coverage
gaps; the revival agent re-checks 90-day-cold leads weekly for fresh signals;
the ABM coordinator dedupes touches so the account never feels swarmed. Humans
keep the high-judgment calls (the AE owns the opportunity, the manager owns
escalation) while the machine does the triage, enrichment and bookkeeping. The
ROI is faster speed-to-lead, higher MQL→SQL conversion, fewer dropped leads, and
a tamper-evident record of every routing decision for RevOps.

## 3. Configuration (three tiers)

### Tier 1 — Boot (required to start the mesh)

| Var | Required | Purpose |
|---|---|---|
| `LEAFMESH_LICENSE_KEY` | yes | SDK license |
| `OPENAI_API_KEY` | yes | `gpt-4o-mini` — manager, intake, revival |
| `ANTHROPIC_API_KEY` | yes | `claude-sonnet-4-6` — qualification, research |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` | host default | session + auto-storage (defaults `localhost:6379`, no password) |
| `LEAFMESH_ENV_TOKEN` | yes | environment token (`development`) |

### Tier 2 — Host prerequisites & adapters (grounding services)

- **MongoDB knowledge service `mongo_main`** — backs every `knowledge:` group:
  `sales_playbook` (manager), `firmographics` (intake), `icp_definition`
  (qualification), `intent_signals` (revival), `competitor_landscape`
  (research). Without it, RAG grounding is empty but the mesh still runs.
- **Slack channel adapter (optional).** `SLACK_BOT_TOKEN` and
  `SLACK_SIGNING_SECRET` in `env` belong to a `channels: {slack: {...}}`
  block (`ChannelConfig`) — there is **no** such block in this config today, so
  these two vars are **not auto-consumed**. The escalation target with
  `provider: slack` only uses its `channel_id` (`SLACK_SALES_CHANNEL`) and
  `message_template`. Add a `channels:` block if you want a full Slack adapter;
  otherwise the bot token / signing secret are inert.

### Tier 3 — Connectors (wire to your systems; optional, off by default)

| Var | Connector agent | What it drives |
|---|---|---|
| `N8N_PIPELINE_HEALTH_WEBHOOK_URL` | `pipeline_health_agent` | reads opportunity stages from your CRM |
| `N8N_NURTURE_WEBHOOK_URL` | `deal_nurturer_agent` | enrols / sweeps nurture sequences in your MAP |
| `N8N_ABM_WEBHOOK_URL` | `abm_orchestrator_agent` | keeps the account/contact ledger in your CRM |
| `PAGER_WEBHOOK` | manager escalation | PagerDuty Events v2 (defaults to the public enqueue URL) |
| `SLACK_SALES_CHANNEL` | manager escalation | Slack channel id for `[sales]` alerts |

The three n8n connector agents' `wake_up` crons are **commented out** until you
wire the webhooks — a cron firing against an empty `webhook_url` would error.
Set the URL, then uncomment the cron. The only always-on cron is
`lead_revival_agent` (Tue 10:00).

## 4. Agents

| Agent | Role (job title) | Responsibilities | Can perform |
|---|---|---|---|
| `lead_intake_agent` | Lead Intake & Enrichment Researcher | Normalise any-source lead → canonical `Lead` (freemail guard, domain derivation); enrich firmographics, funding, tech stack, decision makers; compute `company_tier`, `high_fit_tech`, `enrichment_confidence` | llm (gpt-4o-mini); hybrid cross-session memory; knowledge `firmographics`; → `lead_qualification_agent`, `abm_orchestrator_agent` |
| `lead_qualification_agent` | SDR Researcher (Scoring & Personalisation) | Score ICP fit + intent → `tier`; draft a signal-cited opener in the same pass; enforce hook-quality floor; route on the tier × intent matrix | llm (claude-sonnet-4-6); knowledge `icp_definition`; → `ae_human` (hot), `sdr_human` (warm high-intent / low-hook / cold low-hook), `deal_nurturer_agent` (usable hook), `sales_research_agent` (competitor), `sales_audit_logger_agent` (spam) |
| `pipeline_health_agent` | Pipeline Health Analyst | SLA/queue sweep; opportunity-stage state from your CRM; idle-opp warnings; per-rep weighted coverage | programmatic (n8n); entry points `scheduled_pipeline_health`, `opp_stage_update`, `pipeline_health_sweep`; → `sales_manager_human` (escalate) |
| `sales_research_agent` | Sales Research Desk | Mode-dispatched: competitor intel pack (`intel`) or pre-meeting account dossier (`dossier`); score dossier completeness; flag KB-curation gaps | llm (claude-sonnet-4-6); knowledge `competitor_landscape`; → `lead_qualification_agent` (strong dossier), `sales_audit_logger_agent` (intel / weak dossier) |
| `deal_nurturer_agent` | Nurture / Demand-Gen Coordinator | Enrol mid-funnel leads into MAP drip sequences; daily sweep advancing due touches; graduate on engagement ≥ 0.70 | programmatic (n8n); entry points `enrol_in_nurture`, `nurture_daily_sweep`; → `ae_human` (graduated), `sales_audit_logger_agent` |
| `abm_orchestrator_agent` | ABM / Account Coordinator | Register contacts against the account ledger; flip to coordinated ABM mode at 3+ contacts / 14d; assign one AE; dedup outbound touches | programmatic (n8n); entry points `register_abm_contact`, `coordinate_outbound_touch`; → `ae_human` (activation), `sales_audit_logger_agent` |
| `lead_revival_agent` | Lead Revival Specialist | Weekly sweep of 90-day-cold leads for fresh intent (job moves, funding, hiring); cap revivals at 20 to protect the SDR queue | llm (gpt-4o-mini); cron Tue 10:00; knowledge `intent_signals`; → `sdr_human` (revived), `sales_audit_logger_agent` (none) |
| `sdr_human` | Sales Development Representative | Review high-tier / low-hook sequences before send; start personalised cadence | human gate (30 min, default-deny → manager); → `sales_manager_human`, `sales_audit_logger_agent` |
| `ae_human` | Account Executive | Own hot leads; create opportunities; take MQL→SQL handoffs and graduated/ABM leads | human gate (60 min, default-deny → manager); → `sales_manager_human`, `sales_audit_logger_agent` |
| `sales_manager_human` | Sales Manager | Escalation endpoint; queue rebalancing; hold-for-review on contested leads | human gate (4 h, default-deny → hold); → `sales_audit_logger_agent` |
| `sales_audit_logger_agent` | Audit & Compliance Clerk | Append hash-chained WORM entries for every routing / sequence / handoff decision; tamper-evident record for RevOps | external (custom; intelligence fn in `agency/_shared/audit_logger.py`); terminal |

**Manager** (`gpt-4o-mini`, learning routing, knowledge `sales_playbook`)
supervises the mesh and escalates on SLA breaches via three targets: a
`human_agent` (the sales manager), a `webhook` (PagerDuty), and a `channel`
(Slack).
