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
   approves. Nothing is committed without that answer: if nobody answers within
   60 min, the request waits no longer — its Inbox card closes and the ticket
   records that no reply came.
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
across parallel copies (`scaling.copies.count: 3`) that each claim a disjoint batch.
2.4.484's `scaling.copies.mode: auto` with `claim_tool: claim_cold_leads` could
replace this manual split — an owner decision, not made in this template.

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
- **Silence never advances a lead.** If nobody answers a gate within its time,
  the request waits no longer: its Inbox card closes and the ticket records that
  no reply came. Nothing is sent, approved or committed on silence, and nobody
  is chased automatically — the Sales Manager sees the closed card in the Inbox.
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
| *(no setting)* — human members | Human approvals | Answer in Studio's Inbox. To notify an external tool instead, create a vault connection (an "Add custom" record on the Infrastructure page, service type 'Outbound webhook') and set `webhook_config: {connection: <name>}` on the seat. |

### Tier 2 — real enrichment for the research desk
| Setting | Enables |
|---|---|
| vault connection `enrichment_mcp` | Real firmographics / DM / competitor reads (ZoomInfo / Clearbit / Explorium) |

> The MCP server's URL + token are entered only in the vault (Infrastructure →
> Integrations → MCP), never in `configs/config.yaml` or `.env`. The day-0
> research tools treat enrichment as wired as soon as the vault record
> `enrichment_mcp` exists. The block on
> `sales_research_agent` ships **commented**: create the connection, then
> uncomment it — in `configs/config.yaml` before the first start, in Studio's
> YAML editor after it (see *Changing the configuration after the first
> start*). The day-0 dev tools are the fallback contract.

### Tier 3 — n8n connectors (your CRM/MAP owns the state)
Each connector agent ships inert (`connector_config: {}`). A workflow's address
and token are entered only in the vault: create the connection on
Infrastructure → Integrations → n8n (base URL = the workflow's webhook URL),
then set `connector_config: {connection: <name>}` on the agent (in
`configs/config.yaml` before the first start, in Studio's YAML editor after it
— it applies live, no restart).

| Setting | Connector agent | Drives |
|---|---|---|
| vault connection `pipeline_health_n8n` | `pipeline_health_agent` | opportunity stages from your CRM |
| vault connection `nurture_n8n` | `deal_nurturer_agent` | enrol / sweep nurture in your MAP |
| vault connection `abm_n8n` | `abm_orchestrator_agent` | the account/contact ledger in your CRM |
| `SLACK_SALES_CHANNEL` / *(vault connection `escalation_webhook`)* | Manager escalation | Both targets ship **commented**; day 0 the Sales Manager gets every escalation in the Inbox. Slack: connect Slack on Infrastructure → Messaging → Slack, give `sales_manager_human` `channels: {slack: {connection: <name>}}`, set the channel id in `.env`, then uncomment the channel target. PagerDuty: create the vault connection `escalation_webhook` (an "Add custom" record, service type 'Outbound webhook'), then uncomment the webhook target. Both: in `configs/config.yaml` before the first start, in Studio's YAML editor after it. |

The connector crons ship **commented out** (a cron firing against an unwired
connector would error) — pick the connection, add a `timezone:`, then uncomment (same rule:
the file before the first start, Studio's YAML editor after it). The
only always-on cron is `lead_revival_agent` (Tue 10:00 `Asia/Kolkata`).

## The team (13 members)

| Agent | Role (human job title) | Responsibilities | Can perform |
|---|---|---|---|
| `sales_coordinator_agent` | Lead Desk Coordinator | Opens the lead case, orchestrates the pod, keeps live status, single point of contact | LLM (gpt-4o-mini); → intake (open_case), Sales Manager (escalate); **never scores or approves** |
| `lead_intake_agent` | Lead Intake & Enrichment Researcher | Normalise any-source lead → canonical `Lead` (freemail guard, domain derivation); enrich firmographics, funding, tech stack, decision makers | LLM + **cross-session memory**; `@pre_compose` account-history pull; `@chain` tier floor + idempotent upsert; `@compose` ABM register |
| `lead_qualification_agent` | SDR Researcher (Scoring & Personalisation) | Score ICP fit + intent → `tier`; draft a signal-cited opener in the same pass; route on the tier × intent matrix | LLM + **playbook** (route / nurture) + **memory**; `@chain` score/tier/hook/competitor/spam floors; `@compose` per-downstream; stashes for the finisher |
| `sales_research_agent` | Sales Research Desk | Mode-dispatched: competitor intel pack (`intel`) or pre-meeting account dossier (`dossier`); score completeness; flag KB gaps | LLM + **super_agent** (autonomous plan/execute/verify) + dev-store tools; `@chain` dossier-score floor + bounded research↔qualification loop |
| `lead_revival_agent` | Lead Revival Specialist | Weekly sweep of 90-day-cold leads for fresh intent (job moves, funding, hiring); cap revivals at 20 | LLM + **`scaling.copies.count: 3`** + **atomic claim tool** + **timezone** cron; `@chain` 20-cap floor; `@compose` re-derives the mean under the merge |
| `deal_desk_agent` | Opportunity & Outreach Liaison | Re-check the AE approval, commit the opportunity, queue the approved outreach, ledger it | Programmatic **FINISHER**; approve-token re-check → invariants → render pack → **delete-on-block** → WORM ledger |
| `pipeline_health_agent` | Pipeline Health Analyst | SLA/queue sweep; opportunity-stage state from your CRM; idle warnings; per-rep coverage | Programmatic (n8n); → Sales Manager (escalate) |
| `deal_nurturer_agent` | Nurture / Demand-Gen Coordinator | Enrol mid-funnel leads into MAP drip sequences; graduate on engagement ≥ 0.70 | Programmatic (n8n); → AE (graduated) → the finisher |
| `abm_orchestrator_agent` | ABM / Account Coordinator | Register contacts; flip to coordinated ABM at 3+ contacts / 14d; assign one AE; dedup touches | Programmatic (n8n); → AE (activation), audit |
| `ae_human` | Account Executive (Human) | Owns hot leads; approves the routed lead for commit | Human gate (60 min; nothing committed without "approved"); → the finisher on approval, anything else → audit |
| `sdr_human` | Sales Development Representative (Human) | Reviews warm high-intent and weak-hook sequences before send | Human gate (30 min); the decision is recorded → audit; the cadence runs in your sequencer |
| `sales_manager_human` | Sales Manager (Human) | Accountable owner — escalations, blocked commits, queue rebalancing | Human gate (4 h); the Manager's escalation target; gets every blocked Deal Desk commit |
| `sales_audit_logger_agent` | Audit & Compliance Clerk | Hash-chains every routing, handoff, approval, and held gate | External (custom sink); terminus |

The **LeafMesh Manager** supervises. It escalates to the Sales Manager (Inbox;
Slack / PagerDuty once their commented targets are enabled) when an agent hits
an error a retry cannot fix (auth, bad request, credit, bad config), when 3
different agents fail in one session, or when restarts run out. A hand-off that
misses its contract raises an alert, not an escalation. It does not chase an
unanswered approval and it does not watch SLAs — SLA and queue checks are the
pipeline sweep's job (`pipeline_health_agent`, once its CRM connector is wired).

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

## Changing the configuration after the first start

`configs/config.yaml` is only the first-start seed. On the first start (an empty store) the agency imports it as version 1 and from then on keeps its configuration in the store. After that the file is not read again: an edit to it is **not** applied, even after a restart (the boot log says "that edit was NOT applied").

To change a running agency:

- **Studio** — its settings pages, or the raw YAML editor.
- **API** — `PUT /api/yaml/raw` with an `X-API-Key` header and the body `{"yaml_content": "<the whole YAML>", "save_to_disk": true}`, or `PATCH /api/yaml/config` with `{"updates": {...}, "save_to_disk": true}`.

Each save is a new version and applies live on every pod — no restart. (A few settings, such as brokers, make the agency reload itself in place within seconds.) So wherever this README or a comment says "uncomment X in `configs/config.yaml`", do it in the file before the first start, or in Studio's YAML editor after it.

## Changing a running project (Docker)

What reaches a project that is already running (leafmesh 2.4.497). The
image holds the Python code and the first-start `configs/config.yaml`;
`.env` is passed in when the container is created; the store (Redis) keeps
its data on its own volume.

| You change | When it applies |
|---|---|
| An agent in Studio (prompt, model, tools, routes, human seats, schedules, …) | At once, no restart |
| A human seat's `channels` (Slack, email, …) | The agency reloads itself in place within seconds |
| Add or delete an agent in Studio | At once, including routes and schedules |
| A connection in the vault (model keys, MCP, webhooks, connectors, Slack, email) | At once. An agent switched off for a missing connection or address switches back on by itself |
| Anything in `.env` (licence, agency name, store, ports) | After `docker compose up -d` (the container is recreated) |
| Python code (`agency/*.py`: programmatic agents, tools, `@pre_compose`) | After a rebuild: `docker compose up -d --build` |
| `configs/config.yaml` | Never after the first start. It is read only when the store is empty |
| Several app containers on one store | A Studio save reaches every one within about 15 seconds |

- Keep model keys in the vault. A key there wins over the same key in
  `.env` (the log warns), and a change applies at once. From 2.4.497 that
  holds for every value the vault holds (endpoints, organisation / project
  ids, cloud identities); the `.env` value returns when the record goes.
- Code the image does not have: an agent marked pure Python
  (`integration: python`) is switched off until its function is in the image;
  any other programmatic agent stays on, and each call to code it does not
  have fails. Rebuild the image with the code first.
- A new Redis volume is an empty store, so `configs/config.yaml` is imported
  again as version 1.
- **If the agency refuses to start after an upgrade** (a new leafmesh pin,
  then a rebuild: "Configuration has N error(s) in the stored
  configuration"), repair the stored configuration with the agency stopped:

  ```bash
  docker compose run --rm sales-orchestration leafmesh config check      # each problem, with its line
  docker compose run --rm sales-orchestration leafmesh config versions   # kept versions: which pass, which is in use
  docker compose run --rm sales-orchestration leafmesh config rollback   # back to the newest version that passes (saved as a new version)
  ```

  Or `leafmesh config export > config.yaml`, fix it by hand, then
  `leafmesh config import config.yaml` (it is checked before it is saved).

## Where the data store is set

From leafmesh 2.4.482 the store (Redis or Postgres) is set **only in `.env`** — never in `configs/config.yaml`. A `persistence:` block in the YAML is ignored with a warning on leafmesh 2.4.482–2.4.485; from 2.4.486 the agency refuses to start if that block differs from `.env`, and names each `.env` line to add. The project's `.env` sets the store explicitly (`LEAFMESH_STORE`, `LEAFMESH_AGENCY_NAME`, `REDIS_*`).

- Redis (default): `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `REDIS_DB`; optional `REDIS_DEFAULT_TTL`, `REDIS_SESSION_TTL`, `REDIS_SSL*`, `REDIS_CLUSTER_NODES`.
- Postgres instead: `LEAFMESH_STORE=postgres` plus `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` (optional `POSTGRES_SSLMODE`).
- Or the whole server in one value: `REDIS_URL=redis://user:pw@host:6379/0` (`rediss://` turns TLS on) or `DATABASE_URL=postgresql://user:pw@host:5432/db`. The single names fill in what the URL leaves out.
- With Docker Compose the app reaches Redis as `redis` (the service name); compose sets that for you.
- Check it in Studio → **Infrastructure → Datastores**: it shows whether the store is reachable (never the address or password).

## This mesh's sign-in (leafmesh 2.4.497)

From leafmesh 2.4.497 each mesh signs in to LeafCraft with its own key, not
a key shared by every install.

- **First start.** The mesh makes a key pair and registers it with
  `LEAFMESH_LICENSE_KEY` and `LEAFMESH_ENV_TOKEN` from `.env` (copy the
  environment token from Studio — a placeholder such as `development` is
  refused). With both valid it works at once. If your organisation turned on
  "require approval", the first start stops and says so: approve it in
  Studio → **Keys → SDK access**, then start again. Organisation admins get an
  email for every new registration.
- **Where the key lives.** In the vault, in the store, encrypted with
  `LEAFMESH_VAULT_KEY`: it survives rebuilds and every copy of the app shares
  it. A new Redis volume, or a new vault key, makes a new key pair that
  registers again — revoke the old one in Studio.
- **Check or change it** (in Docker: `docker compose run --rm sales-orchestration leafmesh auth status`):
  - `leafmesh auth status` — credential id, key fingerprint, registration and
    mode, never a key; `--check` signs in now and reports the tokens.
  - `leafmesh auth register` — register now.
  - `leafmesh auth rotate` — a new key pair: once it is active the mesh
    switches to it and revokes the old one. A revoked or expired key is never
    revived; rotate instead.
- **Lost the environment token?** From 5 Dec 2026 Studio shows the licence
  key and environment token only once, when they are made (then only a hint).
  Rotate the environment token in Studio and put the new one in `.env`.
  Rotating it changes where the agency's data is kept in the store, so do it
  before the agency holds data.
- **An existing project whose `.env` says `LEAFMESH_ENV_TOKEN=development`.**
  2.4.497 needs the real token. The token also names where the agency's data
  sits in the store, so with the real token the agency starts on an empty
  store (vault, sessions, board) — the old data stays under the old name. Set
  the real token before you put data in the agency, or contact us to move it.

## Your vault key — back it up

`create-leafmesh` put a `LEAFMESH_VAULT_KEY` in your `.env` when it made this project. It is the master key that encrypts every connection and credential you store in the vault (in Redis / Postgres).

- **Back it up like a master password.** Lose it and every stored connection has to be entered again.
- **Never change or regenerate it** for an existing project — a new key locks the existing vault. To change it, use `leafmesh vault rotate-key`.
- Every copy of the app (every replica) must get the **same** value. Docker Compose passes it in from `.env` as an environment variable.
- Never commit `.env` (it is already in `.gitignore`).
