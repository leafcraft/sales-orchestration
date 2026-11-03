# sales-orchestration — Sales-Orchestration Pod · PRD

## 1. Story

**Priya Nair**, a VP of Data at a 1,400-person fintech, submits the marketing
site's "Book a demo" form. The webhook fires the `demo_request` entry point.
**Sol** (`sales_coordinator_agent`) opens the lead case and hands it to
`lead_intake_agent`, which normalises and enriches her into a canonical `Lead`
(enterprise tier, Series-C funding signal, Snowflake/Datadog high-fit stack,
three decision makers), then hands off to `lead_qualification_agent` and, in
parallel, registers her with `abm_orchestrator_agent`. Qualification scores her
against the ICP, reads strong intent, lands `tier: hot`, and drafts a
signal-cited opener in the same call — then its own tier × intent matrix routes
her to `ae_human`. The AE approves within SLA; **Deal Desk** (`deal_desk_agent`,
the finisher) re-checks the approval, renders the opportunity pack, commits it,
and the decision lands in the hash-chained WORM audit. Because Priya is the third
contact from her domain in 14 days, the ABM coordinator flips the account into
coordinated mode, assigns one owning AE, and requests marketing air cover.

A cold lead with a usable hook routes to `deal_nurturer_agent`; a competitor
employee to the super-agent `sales_research_agent`; spam straight to audit.

## 2. Flow

```
ingress (webform / demo / event / partner / manual) ─► sales_coordinator_agent (Sol)
                                                              │ open_case
                                                              ▼
 lead_intake_agent ──parallel──► abm_orchestrator_agent ──activation──► ae_human
        │                              │
        ▼                              └───────────────────────────────► audit
 lead_qualification_agent  (tier × intent matrix, floored keys)
        ├── hot ─────────────► ae_human ──approved──► deal_desk_agent (FINISHER)
        │                                                   │ commit → pack + ledger
        │                                                   ├── blocked ─► sales_manager_human
        │                                                   └──────────────────► audit
        ├── warm hi-intent / lo-hook ─► sdr_human ─────────────────────────────► audit
        ├── warm/cold + hook ─► deal_nurturer_agent ──graduate──► ae_human ─► deal_desk
        ├── competitor ─────► sales_research_agent ──strong dossier──► lead_qualification
        └── spam ───────────────────────────────────────────────────────────► audit

 lead_revival_agent (cron Tue 10:00, copies.count:3 + atomic claim) ──revived──► sdr_human
 pipeline_health_agent (cron off) ──escalate──► sales_manager_human

 nothing advances on silence: an unanswered gate closes its Inbox card and the
 ticket records that no reply came. The Manager SUPERVISOR escalates repeated /
 unfixable agent errors to sales_manager_human via manager.escalation.
 sales_audit_logger_agent = hash-chained WORM terminus on every branch.
```

## 3. Actor inventory (job-title roster)

| Agent | Job title | Type |
|---|---|---|
| sales_coordinator_agent | Lead Desk Coordinator | llm |
| lead_intake_agent | Lead Intake & Enrichment Researcher | llm |
| lead_qualification_agent | SDR Researcher (Scoring & Personalisation) | llm |
| sales_research_agent | Sales Research Desk | llm (super_agent) |
| lead_revival_agent | Lead Revival Specialist | llm (cron, scaling.copies) |
| deal_desk_agent | Opportunity & Outreach Liaison | programmatic (FINISHER) |
| pipeline_health_agent | Pipeline Health Analyst | programmatic (n8n) |
| deal_nurturer_agent | Nurture / Demand-Gen Coordinator | programmatic (n8n) |
| abm_orchestrator_agent | ABM / Account Coordinator | programmatic (n8n) |
| ae_human | Account Executive | human |
| sdr_human | Sales Development Representative | human |
| sales_manager_human | Sales Manager | human |
| sales_audit_logger_agent | Audit & Compliance Clerk | external (custom) |

## 4. Data artifacts

- **`Lead`** (`data_structures.Lead`) — canonical inbound lead: `lead_id`,
  `source`, `company_domain`, `email`, `job_title`, `intent_signal`,
  `received_at_utc`, `raw_payload` (required: `source`).
- **Enrichment block** (intake yields) — `firmographics`, `company_tier`,
  `funding` + `funding_signal`, `tech_stack` + `high_fit_tech`,
  `decision_makers` + `decision_maker_count`, `enrichment_confidence`,
  `enrichment_complete`.
- **Qualification block** — `icp_fit`, `intent_score`, `tier`, `reasons`,
  `is_competitor`, `sales_briefing`, `opening`, `cited_signals`, `hook_quality`.
- **Opportunity pack** (`./out/<lead_id>_opportunity_pack.md`) — the finisher's
  rendered artifact: tier + scores, approved opening, sales briefing.
- **Audit entry** — `audit_event_id`, `written_at_utc`, `session_id`,
  `payload`, `hash_chain_prev`, `hash_chain_current` (SHA-256 chain).

## 5. Per-agent spec

See `configs/config.yaml` for the authoritative spec. Summary:

- **sales_coordinator_agent** (llm, gpt-4o-mini) — pure-YAML coordinator: opens
  the case (`open_case`), answers `lead_status`, escalates real exceptions. Never
  scores or approves. Owns the lead end to end.
- **lead_intake_agent** (llm, gpt-4o-mini) — `@pre_compose load_account_history`
  reuses the account ledger; `@chain persist_intake` re-derives `company_tier`
  (floor) + idempotent lead/contact upsert; `@compose` shapes the ABM register
  payload. Native cross-session **memory** reuses account context.
- **lead_qualification_agent** (llm, claude-sonnet-4-6) — `@pre_compose
  load_lead_context`; `@chain enforce_qualification_floors` clamps scores, forces
  `is_competitor` from the domain, drops spam, caps hook-quality with no signal,
  **re-derives `tier` from the score bands** (the LLM cannot inflate it), and
  **stashes the lead context by session for the finisher**; `@compose` emits a
  tailored payload per downstream. **playbook** (route / nurture) + **memory**.
- **sales_research_agent** (llm, claude-sonnet-4-6, **super_agent**) —
  `@pre_compose load_research_seed`; `@chain score_research_floor` recomputes
  `dossier_score`, sets `requires_more_data`, forces intel to never re-trigger,
  bounds the research↔qualification loop. Day-0 dev-store tools
  (`get_account_facts`, `list_decision_makers`, `list_competitor_overlap`) that
  announce `available:false`; commented enrichment `mcp` block for going live.
- **lead_revival_agent** (llm, gpt-4o-mini, cron Tue 10:00 `Asia/Kolkata`,
  **`scaling.copies.count: 3`**) — `@pre_compose load_cold_backlog`; `@chain cap_revivals`
  keeps only signal-backed leads, hard-capped at 20; an **atomic claim tool**
  (`claim_cold_leads`) fans the backlog across the copies (disjoint batches);
  `@compose` re-derives the mean confidence under the copies merge (`copies.handoff: last`).
- **deal_desk_agent** (programmatic, **FINISHER**) — the actuator behind the AE
  gate: approve-token re-check (allow/deny lists, **unknown fails closed**) →
  deterministic invariants (committable tier, lead on record) → render the
  opportunity pack to `./out` → **delete-on-block** → dev-store recovery across
  the HITL gap → outbox + append-only ledger. `agency/deal_desk_agent.py`.
- **pipeline_health_agent / deal_nurturer_agent / abm_orchestrator_agent**
  (programmatic, n8n) — connector-only; CRM/MAP owns pipeline / nurture /
  account-ledger state. No template Python.
- **ae_human / sdr_human / sales_manager_human** (human gates, 60 min / 30 min /
  4 h). Only an explicit "approved" from the AE reaches the finisher. If nobody
  answers in time, the request waits no longer: its Inbox card closes and the
  ticket records that no reply came — nothing is committed. The declared
  fallback (`held_for_review` → audit) is kept in config; on SDK 2.4.486 a dual
  seat does not route it. No human→human wire (dual↔dual is a footgun).
- **sales_audit_logger_agent** (external custom) — hash-chained WORM, executed
  via `mesh.intelligence()` from `agency/_shared/audit_logger.py`.

## 6. Entry points

Inbound leads (`webform_lead`, `demo_request`, `event_list`, `partner_referral`,
`manual_action`) and `lead_status` → the coordinator. HITL resume (`sales_reply`)
→ AE; `commit_opportunity` → the finisher. `scheduled_pipeline_health`,
`opp_stage_update`, `pipeline_health_sweep` → pipeline health.
`pre_meeting_dossier`, `competitive_intel_pull` → research. `weekly_lead_revival`,
`lost_deal_revival`, `ghosted_lead_recovery` → revival. `enrol_in_nurture`,
`nurture_daily_sweep` → nurture; `register_abm_contact`,
`coordinate_outbound_touch` → ABM. Plus direct-call/debug entries for intake and
qualification.

## 7. Controls & trust

- **Nothing advances on silence** — an unanswered gate closes its Inbox card and
  the ticket records that no reply came; nobody is chased automatically. The
  Manager escalates only agent errors (unfixable, or 3 failed agents in one
  session) to the Sales Manager.
- **The tier is earned, not claimed** — the tier × intent matrix reads the keys
  the Python `@chain` floored; the LLM cannot inflate a tier past its scores.
- **The finisher fails closed** — unknown approval verdict = blocked; a
  half-rendered pack is deleted on any tripped invariant.
- **WORM audit terminus on every branch** — hash-chained, tamper-evident.
- **State in the customer's systems** — pipeline / nurture / account-ledger state
  lives in the CRM/MAP behind n8n; no template SQLite.
- **Crons fail safe** — the n8n connector crons ship commented out (with a
  `timezone:` reminder) until their webhooks are wired; the only live cron
  (revival) declares its `timezone`.

## 8. Config pointer

`configs/config.yaml` is the department. `env` lists the three config tiers.
Python lives where a role genuinely needs hands:
- `agency/lead_intake_agent.py` — account-history pull, tier floor, ABM shaper.
- `agency/lead_qualification_agent.py` — lead-context pull, score/tier/hook floors,
  per-downstream shapers, finisher stash.
- `agency/sales_research_agent.py` — dossier seed, dossier-score floor + bounded loop.
- `agency/lead_revival_agent.py` — cold-backlog pull, 20-cap floor, copies-merge reshape.
- `agency/deal_desk_agent.py` — the fail-closed commit floor (the finisher).
- `agency/tools.py` — day-0 `@global_tool` surfaces (research reads + atomic claim).
- `agency/_shared/store.py` — seeded dev store (CRM/MAP stand-in) + outbox/ledger.
- `agency/_shared/session_stash.py` — bounded-loop counters + HITL stash.
- `agency/_shared/audit_logger.py` — hash-chained WORM sink.

## 9. Reflection / decisions

- **A pod, not a pipeline**: a coordinator opens the case, self-reliant
  specialists pull their own context (`@pre_compose`) and enforce floors
  (`@chain`) the LLM can't waive, a finisher produces the real artifact and fails
  closed, and the Manager supervises. One human / one agent / one system per
  stage; every wire conditional.
- **Usable on day 0**: a seeded dev store lets the whole chain run with no
  connectors; each store read/write becomes the matching CRM/MAP connector call
  in production (signatures are the contract).
- **Modern capabilities, fitted to the domain**: a per-intent **playbook**
  (route / nurture) on the SDR researcher; a **super_agent** on the research
  desk; **`scaling.copies` + an atomic claim** on the backlog-sweeping revival agent;
  native **memory** on the two lead-facing agents; a **timezone** on the one live
  cron; a commented **mcp** block for real enrichment.
- **Sequencing cadences** (the `[0,1,3]`-style day offsets) deliberately do
  **not** execute in the mesh — they belong to your MAP / sequencer; the wires
  only route.
