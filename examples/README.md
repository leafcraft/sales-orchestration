# sales-orchestration — example scenarios

Four realistic scenarios that exercise the major paths through this mesh.

## How to run

```bash
python examples/run_examples.py                 # all scenarios
python examples/run_examples.py 01_             # one scenario (substring match)
```

## Scenario map

- **01_inbound_demo_request** — `manual_action` — Inbound demo request from MQL form — lead_qualification picks up high-intent signals, drafts the first-touch reach-out, and its tier × intent wires hand the hot lead to the AE.
- **02_cold_lead_revival** — `weekly_lead_revival` — Cron-fired weekly revival sweep — picks up cold leads with new intent signals and drafts re-engagement sequences.
- **03_competitor_steal_signal** — `manual_action` — A competitor-evaluation signal flags a customer evaluating an alternative — sales-ops accelerates the renewal play.
- **04_event_followup_burst** — `manual_action` — Conference scanned 320 badges — bulk follow-up. lead_qualification dedupes + ranks by signal strength.

## Audit trail

Every scenario appends one hash-chained entry to the template's
`logs/<audit>.jsonl` file. Tail it during a run to see the
ledger build up across scenarios.
