# Shadow Trades Analysis — 2026-05-04

**Pull:** 10,378 paper resolutions across both VPS (VPS3=5,454 + VPS2=4,924).
**Window:** 2026-04-30 06:10 UTC → 2026-05-04 17:31 UTC (~4.5 days continuous).
**Mode breakdown:** 100% `paper`. **Zero `live` rows.**
**Sleeves:** 21 distinct (vs doc's 19 — V3 patch family adds BTC/ETH × {v3, v3_1, v3_2, v4} and SOL × {v3_2}).

Source CSVs:
- `data/v4/shadow_trades_2026_05_02/vps3.csv`
- `data/v4/shadow_trades_2026_05_02/vps2.csv`

---

## 1. TL;DR

1. **Live launch never fired.** All 10,378 trades are `mode=paper`. The doc planned $10/$1 live launch on 2026-05-01 — 3 days later, no `mode=live` row exists.
2. **BTC V3 patch ladder is clearly working** — monotonic improvement v3 → v3_1 → v3_2 → v4 in both hit rate (65 → 65 → 80 → 84.6%) and avg PnL ($6.41 → $6.50 → $13.77 → $16.00 per trade). Small samples (n=13–40) but direction is unambiguous.
3. **SOL V3 patch deployment is incomplete.** Only `sol_5m_v3_2` exists (5 fires, -$30). The v3, v3_1, v4 SOL variants are MISSING — TV agent didn't ship them or sleeve mapping is wrong.
4. **DOWN ≫ UP claim weakened on the extended sample.** Doc reported alts skew DOWN by 10-30pp; on 4.5d of data only SOL 15m sniper still shows it (DOWN 60.9% vs UP 44.4%). ETH 5m sniper INVERTED (DOWN 32.4% / UP 51.1%). Most other sleeves now favour UP slightly or are flat.
5. **Volume sleeves bleeding -$17k total** on ~7,000 paper fires. Largest losers: `sol_5m_volume` (-$7,570), `eth_5m_volume` (-$6,789).
6. **SOL 15m volume UP edge collapsed** — was claimed 64% UP / +$472 / n=237 in the prior report; new sample shows 53.1% UP / -$83.78 / n=358. Sample variance, as the doc cautioned.

---

## 2. V3 patch ladder (the headline)

| Asset | Variant | n | Hit% | PnL $ | Avg/trade |
|---|---|---:|---:|---:|---:|
| BTC | v3   | 40 | 65.0% | +256.57 | +6.41 |
| BTC | v3_1 | 20 | 65.0% | +130.09 | +6.50 |
| BTC | v3_2 | 15 | **80.0%** | **+206.55** | **+13.77** |
| BTC | v4   | 13 | **84.6%** | **+208.01** | **+16.00** |
| ETH | v3   | 9  | 44.4% | -33.75 | -3.75 |
| ETH | v3_1 | 6  | 50.0% | -6.75 | -1.12 |
| ETH | v3_2 | 7  | 57.1% | +16.60 | +2.37 |
| ETH | v4   | 6  | 50.0% | -7.25 | -1.21 |
| SOL | v3   | **0** | — | — | — |
| SOL | v3_1 | **0** | — | — | — |
| SOL | v3_2 | 5  | 40.0% | -30.50 | -6.10 |
| SOL | v4   | **0** | — | — | — |

**Interpretation:**
- BTC patches are the strongest signal in the entire dataset. Avg/trade for v4 is **2.5× the BTC 5m sniper baseline** ($16.00 vs ~$1.25 historical).
- ETH patches are too small to conclude (n=6–9). v3_2 is barely positive.
- **SOL deployment hole** — TV agent ships only v3_2 for SOL. Investigate: is this intentional (SOL-specific gating), a config bug, or a coverage gap that needs to be filled?

---

## 3. Live launch status — NOT FIRED

```
mode breakdown across all 10,378 rows:
  paper: 10378
  live:  0
```

**Action required:** confirm with operator whether the live launch was deferred, whether `mode=live` is filtered upstream of `trading.events`, or whether the live trades use a different `kind` (we filtered on `kind='poly_updown_resolution'`).

---

## 4. Direction asymmetry update — DOWN ≫ UP claim weakened

Doc had:
| Asset | Backtest UP / DOWN | Live UP / DOWN |
|---|---|---|
| BTC 5m | 73% / 71% | 78% / 80% |
| ETH | 54% / 77% | 25% / 50% |
| SOL | 70% / 85% | 7.7% / 67% |

Extended sample (4.5d, both hosts merged, snipers only):

| Sleeve | DOWN n / hit% | UP n / hit% | Direction |
|---|---|---|---|
| btc_5m_sniper  | 52 / 48.1% | 57 / 57.9% | UP > DOWN |
| btc_15m_sniper | 22 / 50.0% | 23 / 60.9% | UP > DOWN |
| eth_5m_sniper  | 34 / **32.4%** | 45 / 51.1% | UP > DOWN (DOWN catastrophic) |
| eth_15m_sniper | 16 / 50.0% | 17 / 58.8% | UP > DOWN |
| sol_5m_sniper  | 41 / 41.5% | 43 / 44.2% | flat |
| sol_15m_sniper | 23 / 60.9% | 27 / 44.4% | **DOWN > UP** (only one) |

Only **SOL 15m sniper** preserves the doc's DOWN ≫ UP pattern. ETH 5m sniper has the OPPOSITE — DOWN is now the worst single side (32.4% hit). Hypothesis #1 from doc ("crypto asymmetric vol structure") doesn't fit; hypothesis #3 ("regime artifact") fits the new data.

---

## 5. Volume sleeves — still hemorrhaging

| Sleeve | n (combined) | Hit% | PnL $ | Avg/trade |
|---|---:|---:|---:|---:|
| sol_5m_volume   | 2,356 | 46.5% | -7,570 | -3.21 |
| eth_5m_volume   | 2,525 | 46.3% | -6,789 | -2.69 |
| btc_5m_volume   | 2,511 | 49.1% | -2,196 | -0.87 |
| sol_15m_volume  | 779 | 51.1% | -834 | -1.07 |
| eth_15m_volume  | 846 | 51.8% | -221 | -0.26 |
| btc_15m_volume  | 840 | 49.0% | -1,176 | -1.40 |

5m alts volume sleeves are the worst single drain. **Recommendation:** either gate them through the V3 patch family (which is profitable) or kill them. Currently they collectively lose ~$3.8k/day in paper at the $25/trade nominal.

---

## 6. SOL 15m volume UP edge — collapsed

| Source | n | UP hit% | PnL $ |
|---|---:|---:|---:|
| Doc (2026-05-01) | 237 | 64% | +472 |
| Now (2026-05-04, both hosts) | 358 | 53.1% | -83.78 |

**Verdict:** the prior 64% UP rate was sample variance. Edge gone on extended window. No structural SOL-specific UP signal. Drop the planned "dedicated SOL 15m UP-only sleeve."

---

## 7. Last-24h leaderboard

Top 5 (PnL +):
1. `btc_5m_v4`     n=13, 84.6%, +$208.01
2. `btc_5m_v3_2`   n=15, 80.0%, +$206.55
3. `btc_5m_v3_1`   n=20, 65.0%, +$130.09
4. `btc_5m_v3`     n=27, 59.3%, +$99.03
5. `btc_15m_sniper` n=25, 56.0%, +$47.28

Bottom 5 (PnL −):
1. `eth_5m_volume`    n=552, 44.4%, -$1,978.12
2. `sol_5m_volume`    n=527, 48.0%, -$1,251.99
3. `sol_15m_volume`   n=177, 43.5%, -$826.47
4. `btc_15m_volume`   n=186, 46.2%, -$500.91
5. `eth_15m_volume`   n=185, 48.1%, -$368.27

The V3 patches are the only meaningful winners; everything else is treading water or losing.

---

## 8. Open questions for next session

1. **Why no `mode=live` rows?** Is the live launch deferred, filtered out of `trading.events`, or stored under a different `kind`? Check operator log + `trading.events` raw schema.
2. **SOL V3 patch coverage hole** — is `sol_5m_v3 / v3_1 / v4` not deployed by intent, by config bug, or by a SOL-specific liq_db dependency missing on VPS3?
3. **ETH 5m sniper DOWN at 32.4% is alarming.** Is this an outcome-resolution-source bug specific to one sleeve, or has the strategy genuinely degraded? Compare to ETH 5m sniper PnL on the doc's earlier window.
4. **Volume sleeve kill switch?** They're contributing $0 of edge on $17k of paper losses. Either gate or kill.
5. **BTC v4 looks too good** — 84.6% on n=13 is a small sample but extreme. Look for survivorship bias / data leakage in the v4 feature pipeline.
