# VPS3 Fix Plan — Apply the Recalibrated Strategy

**Goal:** Take VPS3 from its current bleeding state (HYBRID + cold-start sniper, hit 22-30%) to the recalibrated config (HEDGE_HOLD + maker entry + sniper q10 firing) that the backtest forward-walk-validated at +28-32% ROI, 78-86% hit rate.

**Owner:** TV agent (per user). This doc is the operator-facing runbook.
**Box:** VPS3 = `185.190.143.7` = `storedata-vps3`. Key `~/.ssh/vps3_ed25519`.

---

## 0. Current state (snapshot 2026-04-29 22:23 +02)

| Item | Current | Target |
|---|---|---|
| `TV_POLY_HEDGE_POLICY` | **HYBRID** (bleeding) | **HEDGE_HOLD** |
| `TV_POLY_STRATEGY_MODES` | volume,sniper | volume,sniper (unchanged — sniper just needs data) |
| `binance_klines_v2` rows for `source='binance-spot-ws'` | **1.06 days** (1,531 rows × 3 sym) | **≥14 days** (≥20,160 rows × 3 sym) |
| Sniper sleeve fires per day | **0** (cold-start NONE) | **~9 BTC 5m + ~18 BTC 15m + same per ETH/SOL ≈ 80/day** |
| Maker entry | not implemented | maker @ ask−$0.01, wait 30s, fallback taker |
| Spread filter | none | spread<2% on entry |
| UTC hour filter | none | optional: keep [0,3,5,9,10,11,12,13,14,17,19,20] |
| Hit rate | 22-30% live (deeply broken) | ≥65% live (10pp slack from backtest 78%) |

---

## 1. The blocker: sniper needs 14 days of 1m Binance data

### 1.1 Why
`backend/app/controllers/polymarket_updown.py`:
```python
SNIPER_LOOKBACK_DAYS = 14
SNIPER_MIN_SAMPLES = 50
KLINE_SOURCE = "binance-spot-ws"   # filtered in fetch_close_asof()
```
Per resolved Polymarket UpDown market in the last 14 days, the sniper computes `|ln(close_now/close_5m_prior)|` from `binance_klines_v2 WHERE source='binance-spot-ws' AND period_id='1MIN' AND symbol_id=BINANCE_SPOT_<SYM>_USDT`. With <50 samples → returns `None` → sniper sleeve fires 0.

VPS3 currently has 1.06 days of WS data (collector started 2026-04-28 20:53). Sniper has been returning `None` ever since.

### 1.2 Backfill source — Binance Vision (free, fast)

URL pattern: `https://data.binance.vision/data/spot/daily/klines/<SYM>/1m/<SYM>-1m-<YYYY-MM-DD>.zip`

**Window:** 2026-04-15 → 2026-04-28 (**14 calendar days**, all published on Vision by today). Daily Vision file for 04-29 will land tomorrow ~01:30 UTC; not needed for sniper since live WS already covers 04-28 20:53 onwards.

**Symbols:** BTCUSDT, ETHUSDT, SOLUSDT — must match `BINANCE_SYMBOL_ID_MAP`.

**Volume:** 14 days × 3 symbols × 1m = ~60,480 rows. Each daily zip ~3 MB. Total ~130 MB compressed, ~12 MB after parquet/postgres.

### 1.3 The CRITICAL source-label decision

The sniper SQL filter is hardcoded to `source='binance-spot-ws'`. A naive Vision ingest with `source='binance-vision'` will be **invisible to the sniper**.

**Pick Option A (recommended):** ingest Vision rows with `source='binance-spot-ws'` so they show up in the same query the sniper uses. This is what we did on VPS2 to close the recent gap — it works, idempotent via `ON CONFLICT DO NOTHING` on the PK `(symbol_id, period_id, time_period_start_us)`. Live WS keeps writing forward without conflict.

Alternatives (NOT recommended unless TV agent prefers):
- Option B: ingest as `binance-vision` AND patch the controller to accept multiple sources. Requires code change + redeploy.
- Option C: build a `binance_klines_unified` view that UNIONs both. Adds plumbing.

### 1.4 Backfill script (run on VPS3 itself, no laptop bandwidth needed)

There's already a tested mechanism: `/opt/storedata/scripts/binance_vision_daily.py`. Confirmed exists on VPS3 (assumed — same Storedata stack as VPS2). If absent, copy from VPS2.

```bash
# On VPS3 as root or operator (mirrors VPS2's flow)
sudo -u storedata bash -c '
  set -a; source /etc/storedata/collector.env; set +a
  cd /opt/storedata
  /opt/storedata/.venv/bin/python /opt/storedata/scripts/binance_vision_daily.py \
    --from 2026-04-15 --to 2026-04-28 \
    --symbols BTCUSDT ETHUSDT SOLUSDT \
    --intervals 1m \
    --channels klines
'
```

**This writes with whatever `source` the script defaults to** — verify before running. If it writes `source='binance-vision'`:
```sql
-- Re-label inserted rows to match sniper filter
UPDATE binance_klines_v2
SET source = 'binance-spot-ws'
WHERE source = 'binance-vision'
  AND symbol_id IN ('BINANCE_SPOT_BTC_USDT','BINANCE_SPOT_ETH_USDT','BINANCE_SPOT_SOL_USDT')
  AND period_id = '1MIN'
  AND time_period_start_us BETWEEN <2026-04-15 00:00 UTC us> AND <2026-04-28 23:59 UTC us>;
```

(VPS2 has the script writing `binance-vision` source; verified yesterday. Same pattern likely on VPS3 — check first.)

### 1.5 Acceptance check after backfill

```sql
-- Should return ≥20,160 rows per symbol (14 days × 1440 min)
SELECT symbol_id, COUNT(*) AS rows,
  to_timestamp(MIN(time_period_start_us)/1000000) AS first,
  to_timestamp(MAX(time_period_start_us)/1000000) AS last
FROM binance_klines_v2
WHERE source='binance-spot-ws'
  AND period_id='1MIN'
  AND symbol_id IN ('BINANCE_SPOT_BTC_USDT','BINANCE_SPOT_ETH_USDT','BINANCE_SPOT_SOL_USDT')
GROUP BY 1 ORDER BY 1;
```
Pass: each symbol has ≥20,160 rows, first ≤ 2026-04-15 00:00 UTC, last ≈ now.

### 1.6 Fallback if Vision script not on VPS3

Pull from VPS2 (which has full Vision-backfilled data):
```bash
# On laptop:
ssh vps2 "sudo -u postgres psql -d storedata --csv -t -c \"
  SELECT time_period_start_us, time_period_end_us, time_open_us, time_close_us,
         symbol_id, period_id, price_open, price_high, price_low, price_close,
         volume_traded, trades_count, quote_volume, taker_buy_base, taker_buy_quote,
         'binance-spot-ws' AS source
  FROM binance_klines_v2
  WHERE period_id='1MIN'
    AND time_period_start_us BETWEEN 1776182400000000 AND 1777248000000000
    AND symbol_id IN ('BINANCE_SPOT_BTC_USDT','BINANCE_SPOT_ETH_USDT','BINANCE_SPOT_SOL_USDT')
  ORDER BY symbol_id, time_period_start_us\"" \
  | ssh vps3 "cat > /tmp/sniper_backfill.csv"

ssh vps3 "sudo -u postgres psql -d storedata -v ON_ERROR_STOP=1 -c \"
  CREATE TEMP TABLE _stage (LIKE binance_klines_v2 INCLUDING DEFAULTS);
  \\copy _stage FROM '/tmp/sniper_backfill.csv' WITH (FORMAT csv);
  INSERT INTO binance_klines_v2 SELECT * FROM _stage
    ON CONFLICT (symbol_id, period_id, time_period_start_us) DO NOTHING;
\""
```

(Same pattern we used to fill VPS2's tail-end gap from VPS3. Reverse direction here.)

---

## 2. Kill the bid-exit fallback (the −20 pp tax)

### 2.1 The diff
`/etc/tv/tradingvenue.env` on VPS3:
```diff
-TV_POLY_HEDGE_POLICY=HYBRID
+TV_POLY_HEDGE_POLICY=HEDGE_HOLD
```

### 2.2 Why
Live VPS3 V2 HYBRID hit 22-30%, total PnL **−$2,820** over 648 resolutions. Same period VPS2 V1 HEDGE_HOLD hit 44-49%, PnL **−$1,857**. The 20 pp gap is the bid-exit fallback firing on noise: when the 5-bp reversal triggers and opposite ask is empty (272 `no_asks` events), the strategy sells at own bid → locks in 5% spread loss → 313 `exited_at_bid` outcomes per the live tape.

`HEDGE_HOLD` doesn't have this branch. If buy-opposite fails, position rides to resolution. Worse-case is 50/50 outcome at resolution; best-case is win-the-binary.

### 2.3 Apply
```bash
ssh vps3 "
  sed -i 's/^TV_POLY_HEDGE_POLICY=.*/TV_POLY_HEDGE_POLICY=HEDGE_HOLD/' /etc/tv/tradingvenue.env
  systemctl restart tv-engine
  sleep 5
  systemctl is-active tv-engine
  journalctl -u tv-engine --since '1 minute ago' --no-pager | grep -E 'startup|register|policy' | head -10
"
```

### 2.4 Acceptance
After restart, no new `exited_at_bid` events should appear in `trading.events` for new resolutions:
```sql
SELECT data->>'reason' AS reason, COUNT(*)
FROM trading.events
WHERE kind='poly_updown_signal' AND at > '<restart_time>'
GROUP BY 1;
```
Expect `order_placed`, `no_signal`, `held_no_hedge`. **NOT** `exited_at_bid`.

---

## 3. Code changes — apply backtest's winning overlays

These are TV-agent code changes (not env flips). Open a single PR with all three.

### 3.1 Maker entry (tick=0.01, wait=30s, fallback=taker) — +1.9 pp on holdout

**Behavior:** instead of taking the ask at signal time, place a limit buy at `(best_ask − $0.01)` with `expiry=30s`. If filled within 30 s → capture the lower entry price. If not filled → cancel and place taker market buy at current ask.

**Code:** `backend/app/executors/polymarket_paper.py` (and `polymarket_live.py` later) `place_entry_order()`. Reference impl: `strategy_lab/polymarket_maker_entry.py` already simulates this — port the fill logic.

**Env:**
```
TV_POLY_ENTRY_MODE=maker             # values: taker | maker
TV_POLY_MAKER_TICK_OFFSET=0.01       # cents below ask
TV_POLY_MAKER_WAIT_SECONDS=30
TV_POLY_MAKER_FALLBACK=taker         # values: taker | skip
```

**Gate:** off by default (`taker`). Operator flips to `maker` after deploy passes smoke.

### 3.2 Spread filter (entry-time spread < 2.0%) — +2.0 pp on holdout

**Behavior:** at signal time, compute `spread = (ask_0 − bid_0) / mid`. If spread ≥ 0.02 (2.0%), skip the entry. Treat as `no_signal` reason `wide_spread_skip`.

**Code:** `backend/app/controllers/polymarket_updown.py` in the entry-decision block. Compute spread from the same book snapshot used to fetch `entry_yes_ask`.

**Env:**
```
TV_POLY_SPREAD_FILTER_PCT=0.02      # disable by setting to 1.0 (100%)
```

### 3.3 UTC hour-of-day filter — +4 pp (optional)

**Behavior:** only fire entries during whitelisted UTC hours `[0,3,5,9,10,11,12,13,14,17,19,20]`. Skip others as `hour_skip`.

**Code:** same controller, before the threshold check.

**Env:**
```
TV_POLY_HOUR_WHITELIST=0,3,5,9,10,11,12,13,14,17,19,20    # empty = all hours
```

**Note:** UTC hour list is data-fitted on 7-day sample. Don't lock in long-term until validated on a fresh out-of-sample week. Treat as opt-in optimization, not a foundational filter.

---

## 4. Verify sniper threshold quantiles match backtest winner

Backtest forward-walk shows **q10** (top 10% |ret_5m|) on 5m markets is the cleanest cell. The V2 guide says:
> 5m markets → q10 (90th percentile of |ret_5m|)
> 15m markets → q20 (80th percentile)

Confirm controller code at `backend/app/controllers/polymarket_updown.py` line ~333:
```python
quantile = 0.90 if tf == "5m" else 0.80
```
If yes → already correct. No change needed.

---

## 5. Restart and verify all 12 sleeves register

After backfill + env flips:
```bash
ssh vps3 "systemctl restart tv-engine && sleep 8 && journalctl -u tv-engine --since '30 seconds ago' --no-pager | grep -E 'register_poly_updown|sleeve_id|sniper|volume' | head -25"
```

Expected log lines (or close):
```
register_poly_updown_v2: poly_updown_btc_5m_volume
register_poly_updown_v2: poly_updown_btc_5m_sniper
register_poly_updown_v2: poly_updown_btc_15m_volume
register_poly_updown_v2: poly_updown_btc_15m_sniper
... (same for eth, sol = 12 total)
```

DB check:
```sql
-- Within 10 minutes of restart, sniper sleeves should fire signals
SELECT sleeve_id, kind, COUNT(*)
FROM trading.events
WHERE at > '<restart_time>'
GROUP BY 1,2 ORDER BY 1,2;
```
Pass: ≥1 sniper sleeve has ≥1 `order_placed` event within 30 minutes (5m markets resolve every 5 min, so by 30 min you should have ~6 boundaries × 6 sleeves = expected hits).

---

## 6. 7-day observation window

Once the system runs at the new config:

| Day | Action |
|---|---|
| D+1 | Hit-rate sanity. Per (sleeve, mode): `wins / resolutions` for the day. Target: sniper ≥65%, volume ≥50%. |
| D+3 | Per-sleeve PnL roll-up. Target: at least 4/6 sniper sleeves positive. |
| D+7 | Full A/B vs VPS2 V1 (HEDGE_HOLD volume only). Compare cell-by-cell hit rates. Target: sniper q10 5m ≥65% live (10 pp slack from 78% backtest). |

### 6.1 Kill switches
- Per-sleeve drawdown −10% → pause that sleeve, alert.
- Whole-strategy drawdown −15% in 24h → halt all sleeves.
- Hit rate <40% on any sleeve over n≥30 → halt that sleeve.

### 6.2 What "passes" means
- Combined sniper sleeves: hit rate ≥65%, ROI ≥+15% on holdout window. Then ramp from $25→$100/sleeve.
- Combined volume sleeves: if hit rate ≥50% and ROI > 0, keep running. If <50% → disable volume mode entirely (`TV_POLY_STRATEGY_MODES=sniper`).
- If sniper fails ≥65% → strategy doesn't ship. Volume mode alone proven negative-EV live; nothing to fall back to.

---

## 7. Sequencing — exact order to apply

```
[ ] 1. Backfill 14 days of binance_klines_v2 source='binance-spot-ws' on VPS3
[ ] 2. Verify acceptance query: ≥20k rows/sym, first ≤ 2026-04-15
[ ] 3. Flip TV_POLY_HEDGE_POLICY=HEDGE_HOLD in /etc/tv/tradingvenue.env
[ ] 4. systemctl restart tv-engine; verify 12 sleeves register
[ ] 5. Within 30 min: confirm at least 1 sniper sleeve fired (order_placed event)
[ ] 6. Within 24 h: per-sleeve hit-rate sanity check
[ ] 7. (Code PR) implement maker entry + spread filter + hour filter behind env flags
[ ] 8. Deploy PR; smoke test with flags OFF; verify no behavior change
[ ] 9. Flip TV_POLY_ENTRY_MODE=maker, TV_POLY_SPREAD_FILTER_PCT=0.02
[ ] 10. Repeat 7-day observation
[ ] 11. If pass → ramp size and add hour filter. If fail → halt and reassess.
```

Steps 1-6 are operator/agent work that can happen **today**. Steps 7-9 are a code PR (~1 day of TV-agent dev work, per V2 guide estimates). Step 10 is a calendar wait.

---

## 8. What we're NOT doing (explicit non-goals)

- **Not adding feature stacks (OI, L/S, taker, etc.).** Univariate IC analysis showed they're all near 0. Edge is purely `|ret_5m|` magnitude.
- **Not asymmetrizing UP vs DOWN.** Side-asymmetry test p>0.4 across all cells.
- **Not adding take-profit.** TP simulator showed lift -0.12 pp vs revbp baseline. revbp exit is sufficient.
- **Not removing volume sleeves yet.** Keep them as the live-EV control — if they stay slightly negative, fine; gives us comparison signal. Disable only after 7 days if they're clearly negative-EV.
- **Not deploying to VPS2.** VPS2 stays as the V1 control arm for the A/B. Untouched.
