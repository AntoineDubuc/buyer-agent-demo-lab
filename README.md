# buyer-agent demo lab

A small test bench for three changes to the open-source buyer agent (`ad_buyer`): budget **pacing**, a
**creative** check before launch, and an **adaptive negotiator**. It drives the buyer agent's own code
in-process against fixed sample scenarios and tells you, criterion by criterion, whether a change works.
It also renders plain-language before/after pages.

It is written for two readers: an AI coding agent proving its own work, and a human checking that proof.

- Standard library only. It runs under the buyer-agent checkout's own `.venv/bin/python` (3.11+).
- No network, no AI service, no credentials. Each run starts from an empty environment (`env -i`), uses a
  throw-away SQLite database, and blocks every outbound connection in-process.
- Missing features never crash the run: they are recorded as `not_available` (or `error`) and fail.

## Prerequisites

A buyer-agent checkout, installed:

```bash
cd <buyer-agent-checkout> && uv sync --locked --extra dev
```

## Verify a change (the one command)

```bash
./acceptance.sh <path-to-buyer-agent-checkout> <pacing|creatives|negotiation|all>
# same thing: PYTHONPATH=. <checkout>/.venv/bin/python -m demo_lab.check <checkout> <change>
```

It prints one line per criterion, `PASS  <criterion> — <observed>` or `FAIL  <criterion> — <observed>`,
then a `RESULT:` line. **PASS means every criterion below passed; the exit code is then 0.** Any failure
exits 1; a checkout that cannot run at all exits 2. `NOTE` lines are honest observations that never
change the result. Add `--out DIR` to keep the raw result JSON. On an unchanged buyer agent every change
FAILS overall; a few guard lines (today's negotiator unchanged, good ads can launch) pass on any version.

## Acceptance criteria

Data: a $150k sample campaign, 2026-07-01..09-30, CTV 50% / Display 30% / Audio 20%, checked on
2026-08-15 (`demo_lab/data/`). Each block names the interface the lab calls; the change must provide it.

**Pacing.** MCP tool `run_pacing_check(campaign_id, as_of=None)` reads the delivery JSON named by
`Settings.pacing_delivery_file` (env `PACING_DELIVERY_FILE`; one feed or a list of
`{campaign_id, as_of, channels: {CTV: {spend, impressions, effective_cpm, fill_rate}, ...}, deals}`),
saves a snapshot and returns `{channel_pacing: [{channel, status, deviation_pct, ...}], recommendations:
[{type: "reallocate", source_channel, target_channel, amount, reason}], ...}`.
- the MCP tool `run_pacing_check` exists
- `ctv_cant_spend` (CTV 72%, Display 135%, Audio 100% of plan): CTV `behind`, DISPLAY `ahead`,
  AUDIO `on_track`; exactly one recommendation, CTV → DISPLAY, amount > 0
- after that run, `check_pacing` returns the saved snapshot (same channel statuses)
- `audio_over` (98 / 96 / 128%): AUDIO `ahead`, CTV and DISPLAY `on_track`
- `all_on_pace` (101 / 97 / 103%): every channel `on_track`, no recommendations
- `two_behind_one_ahead` (75 / 130 / 78%): total recommended ≤ Display's overspend
- `no_delivery_yet`: `{"status": "no_delivery_data"}`
- unknown campaign: `run_pacing_check` answers `{"error": "Campaign not found: ..."}`
- status band: |deviation| ≤ 10% is `on_track`, below is `behind`, above is `ahead`

**Creatives.** The lab saves ads with `CampaignStore.save_creative_asset` in BOOKING, calls the MCP tool
`validate_campaign_creatives(campaign_id)` (results land in each asset's `validation_status` /
`validation_errors`), then `CampaignStore.mark_ready`, which must refuse while any ad is not valid.
- the MCP tool `validate_campaign_creatives` exists
- headline case (good 30s ad, 45s ad in a 30s slot, VAST 2.0 ad): NOT ready, stays `booking`;
  the 45s ad is `invalid` with a reason mentioning 45 and 30; the VAST 2.0 ad is `invalid` with a
  reason mentioning VAST 4; the good ad is `valid`; the refusal message names each broken ad
- seven-ad case: NOT ready; all six broken ads `invalid`, each with a non-empty reason
- all-valid case (one good ad per channel): the campaign DOES reach READY

**Negotiation.** `AdaptiveStrategy()` (defaults target 20, max 30, step 2, 6 rounds) runs through the
product's own `NegotiationClient.auto_negotiate`; the lab replaces only the client's four network methods
(`start_negotiation`, `counter_offer`, `accept`, `decline`) with in-memory sellers, so keep those
signatures. 200 seeded deals, six seller personalities.
- `from ad_buyer.negotiation.strategies import AdaptiveStrategy` works and `AdaptiveStrategy()` runs
  every deal with no error
- the adaptive negotiator never pays or offers above $30 in any deal
- today's negotiator (`SimpleThresholdStrategy(20, 30, 2, 6)`) matches the lab's pure reference loop
  deal-for-deal (outcome, price and every round): the change must not alter it
- the adaptive negotiator closes at least 1 deal with the seller that accepts any offer at its floor
- against the proportional conceder it wins the same number of deals at a lower average price

Not required, and printed as `NOTE`: the adaptive negotiator is not expected to win everywhere. In the
reference build it closes fewer deals than today's against the firm seller, neither closes against the
"stubborn, then caves" seller, and nobody can close against the wall seller ($40 floor).

## Before/after pages

```bash
./run_demo.sh                       # sibling folders: buyer-agent, -c1-pacing, -c2-creatives, -c3-negotiation
./run_demo.sh BASE C1 C2 C3 OUTDIR  # explicit folders: baseline, then one checkout per change
BEFORE_ONLY=1 ./run_demo.sh         # baseline only -> <change>.before-only.html
```

One self-contained HTML page per change (`pacing.html`, `creatives.html`, `negotiation.html`) with a
"before" column (baseline) next to an "after" column (the change), the acceptance table for both sides,
and the raw tool answers. Raw results go to `OUTDIR/results/<checkout>/<change>.<label>.json`. Default
`OUTDIR` is `../evidence/lab`. A single checkout can carry all three changes: pass it as C1, C2 and C3.

## Honesty labels (shown on every page)

- **Sample data.** The campaign and its delivery numbers are generated by the lab, not real delivery.
- **Declared metadata.** Ads are described (length, size, format, VAST version); no media file is
  downloaded or inspected. Thresholds are industry-typical defaults.
- **Simulated sellers.** Seller personalities are simple seeded models; they are not evidence about how
  real sellers behave.

## Lab self-tests

`python3 -m unittest discover -s tests -t .` pins the scenario math, seller transcripts, fixtures, the
acceptance logic (good and bad results) and that every page renders from any mix of results.

## Layout

`acceptance.sh` and `demo_lab/check.py` (pass/fail), `demo_lab/acceptance.py` (the criteria, also used by
the pages), `run_demo.sh` and `demo_lab/report.py` (pages), `demo_lab/run.py` and `demo_lab/runners/`
(drivers that run inside the buyer-agent interpreter), `demo_lab/data/` (all scenario data), `tests/`.
