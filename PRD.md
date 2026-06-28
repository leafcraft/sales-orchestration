# sales-orchestration — Sales Orchestration · PRD

## 1. Story

**Priya Nair**, a VP of Data at a 1,400-person fintech, submits the marketing
site's "Book a demo" form. The webhook fires the `demo_request` entry point.
`lead_intake_agent` normalises and enriches her into a canonical `Lead`
(enterprise tier, Series-C funding signal, Snowflake/Datadog high-fit stack,
three decision makers), then hands off to `lead_qualification_agent` and, in
parallel, registers her with `abm_orchestrator_agent`. The qualification agent
scores her against the ICP, reads strong intent, lands `tier: hot`, and drafts a
signal-cited opener in the same call — then its own tier × intent matrix routes
her to `ae_human`. The AE accepts within SLA, creates the opportunity, and the
decision lands in the hash-chained WORM audit. Because Priya is the third
contact from her domain in 14 days, the ABM coordinator flips the account into
coordinated mode, assigns one owning AE, and requests marketing air cover.

A cold lead with a usable hook would route to `deal_nurturer_agent` instead; a
competitor employee to `sales_research_agent`; spam straight to audit.

## 2. Flow

```
ingress (webform / demo / event / partner / manual)
        │
        ▼
 lead_intake_agent ──parallel──► abm_orchestrator_agent ──┐
        │                              │ (activation)      │
        ▼                              ▼                   │
 lead_qualification_agent           ae_human              audit
        │  (tier × intent matrix)       │
        ├── hot ─────────────► ae_human ─┤
        ├── warm hi-intent ─► sdr_human ─┤
        ├── warm/cold lo-hook► sdr_human ┤
        ├── warm/cold hook ─► deal_nurturer_agent ──graduate──► ae_human
        ├── competitor ─────► sales_research_agent ──dossier──► lead_qualification
        └── spam ──────────────────────────────────────────────► audit
                                       │
   sdr_human / ae_human ──timeout/escalate──► sales_manager_human ──► audit
                                       │
 lead_revival_agent (cron Tue 10:00) ──revived──► sdr_human
 pipeline_health_agent (cron off) ──escalate──► sales_manager_human

 sales_audit_logger_agent = WORM terminus on every branch
```

## 3. Actor inventory (job-title roster)

| Agent | Job title | Type |
|---|---|---|
| lead_intake_agent | Lead Intake & Enrichment Researcher | llm |
| lead_qualification_agent | SDR Researcher (Scoring & Personalisation) | llm |
| pipeline_health_agent | Pipeline Health Analyst | programmatic (n8n) |
| sales_research_agent | Sales Research Desk | llm |
| deal_nurturer_agent | Nurture / Demand-Gen Coordinator | programmatic (n8n) |
| abm_orchestrator_agent | ABM / Account Coordinator | programmatic (n8n) |
| lead_revival_agent | Lead Revival Specialist | llm (cron) |
| sdr_human | Sales Development Representative | human |
| ae_human | Account Executive | human |
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
- **Audit entry** — `audit_event_id`, `written_at_utc`, `session_id`,
  `payload`, `hash_chain_prev`, `hash_chain_current` (SHA-256 chain).

## 5. Per-agent spec

See `configs/config.yaml` for the authoritative spec. Summary:

- **lead_intake_agent** (llm, gpt-4o-mini) — `@pre_compose load_account_history`
  pulls the account ledger for the domain so enrichment reuses known context;
  `@chain persist_intake` re-derives `company_tier` deterministically (floor)
  and idempotently upserts the lead + registers the contact. Knowledge
  `firmographics`. Fan-out to qualification + ABM.
- **lead_qualification_agent** (llm, claude-sonnet-4-6) — `@pre_compose
  load_lead_context` pulls enrichment + account ledger + prior touches;
  `@chain enforce_qualification_floors` clamps scores, forces `is_competitor`
  from the domain, drops spam, caps hook-quality with no signal, and
  **re-derives `tier` from the score bands** (the LLM may name a tier but
  cannot inflate it); `@compose` emits a tailored payload per downstream. The
  tier × intent `can_call` matrix reads the *floored* keys. Knowledge
  `icp_definition`.
- **pipeline_health_agent** (programmatic, n8n) — connector-only; CRM owns
  opportunity-stage state. Escalates to the sales manager.
- **sales_research_agent** (llm, claude-sonnet-4-6) — `@pre_compose
  load_research_seed` pulls the account ledger; `@chain score_research_floor`
  recomputes `dossier_score`, sets `requires_more_data` from the 0.5 gate,
  forces intel packs to never re-trigger, and bounds the research↔qualification
  loop via the session stash. Knowledge `competitor_landscape`.
- **deal_nurturer_agent / abm_orchestrator_agent** (programmatic, n8n) —
  connector-only; MAP/CRM owns nurture + account-ledger state.
- **lead_revival_agent** (llm, gpt-4o-mini, cron Tue 10:00) — `@pre_compose
  load_cold_backlog` pulls the >= 90d cold-lead backlog; `@chain cap_revivals`
  keeps only signal-backed leads and hard-caps at 20 (protect the SDR queue).
  Knowledge `intent_signals`.
- **sdr_human / ae_human / sales_manager_human** (human gates) — default-deny
  fallbacks (30 min / 60 min / 4 h) escalating to the manager / hold-for-review.
- **sales_audit_logger_agent** (external custom) — hash-chained WORM, executed
  via `mesh.intelligence()` from `agency/_shared/audit_logger.py`.

## 6. Entry points

`webform_lead`, `demo_request`, `event_list`, `partner_referral`,
`manual_action` → intake. `scheduled_pipeline_health`, `opp_stage_update`,
`pipeline_health_sweep` → pipeline health. `pre_meeting_dossier`,
`competitive_intel_pull` → research. `weekly_lead_revival`, `lost_deal_revival`,
`ghosted_lead_recovery` → revival. Plus direct-call / debug entry points for
qualification, intake, nurture (`enrol_in_nurture`, `nurture_daily_sweep`) and
ABM (`register_abm_contact`, `coordinate_outbound_touch`).

## 7. Controls & trust

- **Human gates default-deny on timeout** — SDR/AE escalate to the manager;
  the manager holds for review. No silent advance.
- **Routing is explicit config** — the tier × intent matrix lives in
  `lead_qualification_agent.can_call`, mutually exclusive per row; spam and
  competitor cases short-circuit before any sales touch.
- **WORM audit terminus on every branch** — hash-chained, tamper-evident.
- **State in the customer's systems** — pipeline / nurture / account-ledger
  state lives in the CRM/MAP behind n8n; no template SQLite.
- **Crons fail safe** — the three n8n connector crons are commented out until
  their webhooks are wired.

## 8. Config pointer

`configs/config.yaml` is the department. `env` lists the three config tiers.
Python lives where a role genuinely needs hands:
- `agency/lead_intake_agent.py` — `@pre_compose` account-history pull, `@chain`
  tier floor + idempotent lead/contact upsert.
- `agency/lead_qualification_agent.py` — `@pre_compose` lead-context pull,
  `@chain` score/tier/hook/competitor/spam floors, `@compose` per-downstream
  payloads.
- `agency/sales_research_agent.py` — `@pre_compose` dossier seed, `@chain`
  dossier-score floor + bounded research↔qualification loop.
- `agency/lead_revival_agent.py` — `@pre_compose` cold-backlog pull, `@chain`
  20-cap floor.
- `agency/_shared/store.py` — seeded dev store (CRM/MAP stand-in).
- `agency/_shared/session_stash.py` — per-session bounded-loop counters.
- `agency/_shared/audit_logger.py` — hash-chained WORM sink.

## 9. Reflection / decisions

- **Deep where the domain calls for it**: the four LLM judgment roles are
  self-reliant — they pull their own context (`@pre_compose` from the dev
  store) and enforce their own deterministic floors (`@chain`) the LLM cannot
  waive. The tier × intent routing matrix reads the *floored* keys, so routing
  is governed by Python, not by whatever the model wishes were true. The
  connector roles (pipeline / nurture / ABM) stay pure n8n YAML — their state
  genuinely lives in your CRM/MAP, so they need no template Python.
- **Usable on day 0**: a seeded dev store (`agency/_shared/store.py`) lets the
  full intake → qualify → route → research → revive chain run with no
  connectors set; each store read/write becomes the matching connector call in
  production (signatures are the contract).
- **Merged roles**: intake absorbed enrichment; qualification absorbed scoring +
  personalisation + the old sequence-orchestrator's routing matrix; research
  absorbed competitor-intel + account-dossier (mode-dispatched). The cast stays
  a recognisable sales department without thin single-function nodes.
- **Sequencing cadences** (the `[0,1,3]`-style day offsets) deliberately do
  **not** execute in the mesh — they belong to your MAP / sequencer (Outreach /
  Salesloft); the wires only route.
- **Slack adapter**: `SLACK_BOT_TOKEN` / `SLACK_SIGNING_SECRET` are documented
  for an optional `channels: {slack: {...}}` block; the escalation target uses
  only `channel_id`. They are inert until that block is added.
