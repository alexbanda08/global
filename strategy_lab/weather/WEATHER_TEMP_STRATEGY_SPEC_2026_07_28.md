# Weather temperature markets — strategy spec (2026-07-28)

New strategy line, fully separate from the crypto up/down stack. Different resolution source
(weather stations, not Chainlink), different fee schedule (`weather_fees`), different edge type
(physical nowcast, not microstructure).

## Why now

- The vertical has EXPLODED since our June wallet decodes: **42 cities, ~50+ active daily
  high/low-temp events, 11 brackets each (negRisk)**. Per-city 24h volume $20k–250k
  (Hong Kong $249k, Seoul $115k, NYC $63k on 2026-07-28); event liquidity $30k–390k.
  In June these books were "thin, near capacity at $400–980/trade" — no longer true.
- We already decoded the two winning archetypes (2026-06-03 reports):
  - `0x331bf91c` — forecast-alpha longshot buyer, +$65k lifetime, 27.6% ROI, faded.
  - `@hightemptation` (0x6011655c) — **nowcast scalp**: buy near-certain bracket at ~0.95
    before full convergence, sell 0.98–1.0, median hold 12 min, 99% WR May–Jun, +$7.5k.
  Both verdicts said: uncopyable via wallet-follow; **"to run it yourself you'd need your own
  fast temperature nowcast feed."** That feed is free and verified working (see §Data).

## Market mechanics (verified 2026-07-28 via gamma API)

- Event slug: `highest-temperature-in-{city}-on-{month}-{day}-{year}` (+ `lowest-...`).
  Created ~1 day before the target date (NYC Jul-28 created Jul-27 01:03 UTC).
- 11 mutually-exclusive brackets, negRisk=true. US cities: 2°F brackets + open tails,
  whole-°F precision. Non-US: 1°C brackets, HK resolves to 0.1°C precision.
- Tick 0.01 (0.001 in the tails), orderMinSize 5.
- **Fees: `feeType=weather_fees`, `feeSchedule={rate: 0.05, exponent: 1, takerOnly: true,
  rebateRate: 0.25}`.** Taker-only 5% (verify exact formula — likely rate×p×(1−p)-style or
  rate×proceeds; MUST pin down empirically from a real fill before sizing). Makers get a 25%
  rebate share → maker-first execution strongly favored.
- Liquidity rewards active (`rewardsMinSize 100, rewardsMaxSpread 4.5`) → there are paid MMs
  quoting these books; expect tight spreads (0.01) in the meat, loose in tails.

### Resolution sources (per market description — mechanical, no UMA judgment)

| Region | Source | Precision | Our live proxy |
|---|---|---|---|
| US cities | Wunderground **airport station history page** (e.g. NYC = KLGA LaGuardia) | whole °F | METAR (same underlying obs): aviationweather.gov API, IEM ASOS 5-min |
| Hong Kong | HK Observatory "Absolute Daily Max", daily extract | 0.1 °C | HKO open API `rhrread` (10-min updates) — verified working |
| Other intl | city-specific (met service or Wunderground airport station) | 1 °C typical | METAR for airport stations; per-city verification needed |

⚠️ Gotcha to verify per station: Wunderground's displayed daily max is derived from METAR
(°C → °F conversion + rounding, T-group 0.1°C when present). Brackets whose boundary sits
within ~0.5°F of the running max are ROUNDING-RISKY — treat as uncertain, don't count as dead.

## The edge — three layers, in order of tractability

### Layer 1: dead-bracket / monotone-max arbitrage (deterministic, START HERE)
Daily max temperature is **monotone non-decreasing** within the day. The moment the station's
running max crosses a bracket's upper boundary, that bracket and everything below it is worth
**exactly 0** — no model, pure arithmetic.
- SELL (or buy the No of) any bracket strictly below the running max that still has a bid.
- The cumulative price of {brackets ≥ running-max bracket} must be ≈ 1.00; if it trades < ~0.95,
  buy the underpriced side.
- Edge source = latency between obs publication (METAR ~hh:51 + SPECI; ASOS 5-min feeds;
  HKO 10-min) and the crowd repricing 11 books × 84 events/day across timezones. Nobody can
  watch all of them manually; we can, with the same collector discipline as shadow_v52.

### Layer 2: peak-lock convergence scalp (the hightemptation clone)
After the local afternoon peak (temp decisively declining, e.g. 2 consecutive obs ≥1°F below
max, after typical peak hour), the winning bracket is ~locked but often still trades 0.85–0.95.
Buy it, exit at 0.98+ or hold to resolution. This is exactly what made @hightemptation
99% WR; our advantage is breadth (42 cities) + automation, not being faster on one city.
Requires a "peak is in" classifier — start with a dumb rule (local hour ≥ climatological peak
AND falling obs AND no incoming warm front proxy), tighten with data.

### Layer 3: forecast-distribution vs market — LADDER framing (upgraded 2026-07-28 from the 0xSurferX article)
NBM/ECMWF/GFS forecasts vs the opening bracket distribution, but traded as a **distribution,
not a point**: buy a tight cluster of 3–4 adjacent buckets centered on the bias-corrected
STATION forecast, sized ∝ own probability per bucket, only when Σ(own prob) over the cluster
materially exceeds Σ(ask) + fees. Concepts adopted from the article (see §Article review):
- **D+1/D+2 horizon** — events open ~1 day early (matches our observation); that's where
  forecast edge lives, before nowcast determinism takes over.
- **Fresh-model-run timing** — ECMWF/GFS runs 00/06/12/18Z publish on a lag; reprice window
  after a shifted run = event-driven entry, the D+1 analog of our METAR-transition hypothesis.
- **Underdispersion filter** — ensemble spread today vs its climatological spread for that
  city; unusually tight ensemble = outcome more certain than the market prices → press;
  wide ensemble → widen the ladder or skip. (Real meteorology: spread–skill relationship.)
- **Per-station bias correction** — model minus station-resolved outcome, rolling; our
  collector produces exactly this table for free (forecast vs resolved outcome daily).
Still the hardest layer (real weather-quant competition); attack only with collector data.

## What we do NOT do
- No wallet copy-trading (both June verdicts: dead on arrival).
- No annual/climate markets (hottest-year, sea ice) — one-shot, no repeated trials, unfalsifiable edge.
- No taker sprees before the fee formula is verified on a real fill.

## Data plan (prerequisite for everything)

1. **Scanner/snapshot collector** (`weather_scan.py`, this dir): every 5–10 min, pull all
   active daily temp events (gamma) + running max per station (METAR/HKO) → append snapshot CSV.
   One row per bracket per tick: prices, best bid/ask, running max, dead/floor flags.
   Run as a scheduled task like `V52Shadow`. Zero capital, zero risk — read-only.
2. After ~2–4 weeks: measure (a) how often dead brackets stay bid > 0.01 and for how long,
   (b) the price path of the eventual winner vs time-to-peak (Layer-2 entry curve),
   (c) open-time calibration (Layer 3).
3. Resolution ground truth: scrape final resolved outcome per event (gamma `closed` events)
   + station daily max — also validates our obs proxy against the actual resolution source.

## Validation gates (same rigor as the rest of the lab)
- Layer 1: paper-log every dead-bracket signal with the book at signal time; ≥100 signals,
  measure fillable $ at signal vs 5 min later. It's an arb — the only questions are frequency,
  size, and whether we're first.
- Layer 2: pre-registered entry rule, paper fills at best ask (maker-join price as upper bound),
  ≥200 paper trades, bootstrap CI > 0 net of the verified fee, before any capital.
- Ground-truth rule applies: judge only by logged book snapshots, never by "the price now" hindsight.

## Article review — 0xSurferX "Temperature ladder bot" (x.com status 2080256772057489502, 2026-07-23; read + ground-truthed 2026-07-28)

Claim: "passive $6k/month" ladder bot, public wallet `0x4989bfed5900ba096b08ba1f9b718464527c983e`.
**Ground-truth via lb-api + data-api (2026-07-28):** wallet = pseudonym **`macau.weather`**;
lifetime profit **+$8,114 TOTAL**, 30d **+$6,011**, **7d −$713**. So "$6k/mo" = one good month,
not a track record ("passed the test of time" is marketing; article funnels to a paid TG).
Positions contradict the article's own city list: **Hong Kong ONLY** (article says
Singapore/Miami/Tokyo/Shanghai), and he runs 5–6-leg ladders (article says 3–4). Today's two
big HK-high legs are −$284/−$278 unrealized. **Ladder structure itself CONFIRMED in the
positions:** adjacent Yes buckets center-weighted (~$1.8k/$0.9k shares center, $200–270 of
0.001–0.002 tail insurance) + No legs on near-certain buckets of lowest-temp markets;
accumulates via many tiny clips ($0.02–$25) — maker-style accumulation on thin books.

What's actually worth keeping (folded into Layer 3 above): distribution-not-point framing,
D+1/D+2 horizon, fresh-model-run repricing window, ensemble underdispersion filter,
per-station bias correction. What to discard: the implied "structure creates edge" pitch —
a ladder is just buying P(range) for Σ(ask); EV comes only from forecast calibration vs the
market. His EV code ignores the 5% weather taker fee entirely.

## First empirical result (2026-07-28 13:28 UTC, single snapshot)

Fixed scanner run across 156 active events / 48 same-local-day events with obs:
**0 dead-bid violations** — 202 deterministically-dead brackets, max bid on any of them 0.001.
One borderline TAIL_CHEAP (Warsaw high, live-bracket sum 0.946 ≈ fee-sized). ⚠️ An earlier
buggy run showed 120 "violations" — all bogus (compared today's obs against tomorrow's markets;
events open ~1 day early). Date-guard now in the scanner.

**Implication: the naive standing dead-bracket arb does NOT exist at random sample times —
the books are efficient at steady state.** The surviving hypotheses are TRANSIENT:
1. the repricing window in the minutes after each new obs (METAR ~hh:51, SPECI, HKO 10-min)
   crosses a bracket boundary — requires the snapshot loop at ≥1/min around obs times;
2. Layer-2 peak-lock convergence (winner at 0.85–0.95 after the peak is in) — requires the
   full-day price path per bracket.
Both are exactly what the scheduled collector measures. Do not deploy anything before that
dataset exists.

## Open questions
- [ ] Exact `weather_fees` formula (rate 0.05, exponent 1 — on proceeds? on p(1−p)?).
- [ ] Per-city station map + tz for all 42 cities (parse from market descriptions; scanner does US+HK first).
- [ ] Wunderground rounding vs raw METAR T-group per US station (compare our max vs resolved outcome daily).
- [ ] CLOB book endpoint returned empty for a negRisk temp bracket while gamma showed bid/ask —
      check whether negRisk books need a different endpoint or the market was mid-redeploy.
- [ ] Non-US non-HK resolution sources (Seoul KMA? Tokyo JMA? Wunderground?) — parse each description.
- [ ] Add daily ensemble-forecast snapshots per station (open-meteo ensemble API is free:
      GFS ENS + ECMWF ENS point forecasts) — prerequisite for testing the underdispersion
      filter and per-station bias correction (Layer 3) against resolved outcomes.
- [ ] Watch `macau.weather` (0x4989bfed…) weekly via lb-api — if the ladder wallet's 30d
      decays like 0x331bf91c did, that's evidence the D+1 forecast edge is crowding out.

## Artifacts
- `weather_scan.py` — scanner v1 (US + HK cities): fetches events, parses stations from
  descriptions, computes running max, flags dead-bracket violations, appends snapshots to
  `snapshots/weather_snapshots_YYYY_MM_DD.csv`.
- June wallet decodes: `strategy_lab/reports/WALLET_331BF91C_WEATHER_2026_06_03.md`,
  `strategy_lab/reports/WALLET_6011655C_HIGHTEMPTATION_2026_06_03.md`.
