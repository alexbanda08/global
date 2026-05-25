# Wallet Decoder Fix Spec — 2026-05-21

**Scope**: fix the chain decoder + cash-PnL aggregator so it stops reporting profitable Polymarket wallets as net-negative.

**Why it matters**: official Polymarket portfolio audit (`migration_ireland_shadow_2026_05_21/portfolio_audit/PORTFOLIO_AUDIT_REPORT.md`) shows our local decoder under-reports cash PnL by ~100 % on every audited wallet. Decoder verdict: "BDH wallets lose −$348/day / −$296/day". Polymarket-official verdict: "BDH wallets earn +$1,640/day / +$1,453/day". Decoder is wrong.

**Effort**: ~3 dev-hours. Mostly trivial filter changes.

## 1. Root cause

The chain decoder + the local cash-PnL aggregator are built around the CLOB trade tape. They filter activity events on `side ∈ {BUY, SELL}` and DROP every event that carries `side=""` — which is REDEEM, MERGE, MAKER_REBATE, CONVERSION, REWARD, REFERRAL_REWARD, DEPOSIT, WITHDRAWAL, YIELD.

For a hold-to-expiry strategy (paired-bid CLOB maker that buys both sides and waits for resolution), REDEEM is **80-90 % of cash income**. Dropping it inverts the sign.

Per the audit, blind-spot $$ per wallet:

| event class | $ blind-spot for 0xeebde7a0 | for 0xb27bc932 | for 0x04b6d7e9 | for BDH cluster |
|---|---:|---:|---:|---:|
| REDEEM | $2,530,062 | $4,686,617 | $4,306,564 | $308,062 |
| MERGE | $988,456 | $154,571 | $62,061 | $0 |
| MAKER_REBATE | $45,506 | $196,303 | $82,947 | $990 |
| CONVERSION | $0 | $0 | $0 | $0 |
| REWARD | $0 | $0 | $0.47 | $0 |

REDEEM is the single biggest miss. Fix it first.

## 2. Fix #1 — index REDEEM events (HIGH)

### Files affected

Search the wallet_hunt module for the activity / fills aggregator. Candidates:

- `strategy_lab/wallet_hunt/cash_pnl.py`
- `strategy_lab/wallet_hunt/compute_pnl.py`
- `strategy_lab/wallet_hunt/decoder.py`
- `strategy_lab/wallet_hunt/analyze_wallet.py`

Find every place that loops over an activity-like dataframe and filters on `side`. Replace the BUY/SELL gating with type-based dispatch:

### Before (illustrative pattern)

```python
def cash_pnl(activity_df):
    buys  = activity_df[activity_df["side"] == "BUY"]["usdcSize"].sum()
    sells = activity_df[activity_df["side"] == "SELL"]["usdcSize"].sum()
    return sells - buys
```

### After

```python
def cash_pnl(activity_df, positions_df=None):
    """Polymarket realized + unrealized PnL from activity tape.

    Realized cash:
        + TRADE sells
        - TRADE buys
        + REDEEM    (winner-share redemption at $1)
        + MERGE     (pair claim at $1, NegRiskAdapter)
        + MAKER_REBATE
        + REWARD + REFERRAL_REWARD + YIELD
        + CONVERSION  (USDC from NegRisk yes+no conversion)
        - SPLIT     (USDC out, mints yes+no shares)
        + WITHDRAWAL
        - DEPOSIT

    Unrealized: sum of current_value over open positions (positions_df).
    """
    realized = 0.0

    trades = activity_df[activity_df["type"] == "TRADE"]
    realized -= trades[trades["side"] == "BUY"]["usdcSize"].sum()
    realized += trades[trades["side"] == "SELL"]["usdcSize"].sum()

    for income_type in ("REDEEM", "MERGE", "MAKER_REBATE",
                        "REWARD", "REFERRAL_REWARD", "YIELD",
                        "CONVERSION", "WITHDRAWAL"):
        realized += activity_df[activity_df["type"] == income_type]["usdcSize"].sum()

    for outflow_type in ("SPLIT", "DEPOSIT"):
        realized -= activity_df[activity_df["type"] == outflow_type]["usdcSize"].sum()

    unrealized = 0.0
    if positions_df is not None and len(positions_df):
        unrealized = positions_df["currentValue"].sum()

    return {"realized": realized, "unrealized": unrealized,
            "total": realized + unrealized}
```

### Test

For wallet `0x9dae874a`, after fix:

- `realized` should be approximately `+$49,205` (matches lb-api `/profit?window=all`)
- `unrealized` should be `$0` (no open positions per audit)
- Activity breakdown: 500 TRADEs, 0 MERGE, 0 SPLIT, 189 REDEEM, 0 CONVERSION, 8 MAKER_REBATE

Tolerance: within 1 % of lb-api number (decoder may miss old DEPOSITs or have rounding errors).

## 3. Fix #2 — replace `getAssetTransfers` with the official `/activity` endpoint (HIGH)

Right now the decoder reconstructs wallet history from Alchemy's `getAssetTransfers` (raw ERC-20 transfer events). This is correct on-chain but expensive to parse — you have to:
- Identify which token contract corresponds to which conditionId
- Decode CTF/NegRiskAdapter call data
- Stitch together MERGE / SPLIT / REDEEM events from EVM logs

Polymarket's `data-api.polymarket.com/activity` does all of that server-side and returns clean structured events with type, conditionId, side, usdcSize, etc. Use it as the primary source; keep `getAssetTransfers` as a cross-check only.

### Drop-in client

`strategy_lab/wallet_hunt/lb_api_*` already has API clients. Use the same `requests` + `_cache/` pattern. Per-wallet endpoint:

```python
def fetch_activity(wallet: str, types: list[str] | None = None,
                   limit: int = 500, max_total: int = 5000) -> list[dict]:
    base = "https://data-api.polymarket.com/activity"
    types = types or ["TRADE", "MERGE", "SPLIT", "REDEEM", "CONVERSION",
                      "MAKER_REBATE", "REWARD", "REFERRAL_REWARD",
                      "YIELD", "DEPOSIT", "WITHDRAWAL"]
    out = []
    for t in types:
        offset = 0
        while True:
            r = requests.get(base, params={
                "user": wallet, "limit": limit,
                "offset": offset, "type": t,
            })
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            out.extend(batch)
            if len(batch) < limit or len(out) >= max_total:
                break
            offset += limit
    return out
```

### Acceptance

For each wallet in the `_master_catalog.csv`, the `/activity`-derived realized PnL should match `lb-api /profit?window=all` within 1 % over the same time window.

## 4. Fix #3 — add `MAKER_REBATE` to the wallet income classifier (MEDIUM)

`_master_catalog.csv` classifies wallets by strategy class (mint-and-sell, paired-arb-maker, directional-taker, etc). The classifier looks at trade frequency, sides, prices. It does NOT look at MAKER_REBATE income.

After Fix #1, add a rebate-share metric:

```python
maker_rebate_share = (activity_df[activity_df["type"] == "MAKER_REBATE"]["usdcSize"].sum()
                      / total_cash_income)
```

Wallets with `maker_rebate_share > 0.05` (5 % of cash income from rebates) are confirmed MAKERS — they post resting orders. Wallets with `maker_rebate_share < 0.001` are likely pure takers or single-fire wallets. Use this as a label feature.

For our 6 audited wallets:

| wallet | rebate share | inferred role |
|---|---:|---|
| 0x9dae874a | 0.27% | pure taker (correct: BDH directional) |
| 0xa0a50783 | 0.42% | pure taker |
| 0x04b6d7e9 | 1.86% | mixed (some maker fills, mostly taker buys) |
| 0xeebde7a0 | 1.28% | mixed |
| 0xb27bc932 | 3.90% | maker-heavy |
| 0x89b5cdaa | 16.89% | **dominant maker** |

This metric alone fixes the "is this wallet a maker?" classification problem the catalog currently struggles with.

## 5. Fix #4 — correct the `convert_positions` event-type filter (LOW)

Local scripts that try to filter Polymarket activity by `type=CONVERT` get 0 results because the API expects `CONVERSION` (full word). $0 impact for the 6 audited wallets but required for any wallet using NegRisk merger of yes-shares across non-binary markets.

```python
# WRONG:
r = requests.get(url, params={"type": "CONVERT"})

# RIGHT:
r = requests.get(url, params={"type": "CONVERSION"})
```

## 6. Fix #5 — verify USDC.e vs USDC token coverage (MEDIUM)

Polymarket on Polygon settles in USDC.e (`0x2791bca1...`) but some flows now use native USDC (`0x3c499c54...`). Asset-transfer scans that watch only one contract address miss the other half.

Action: enumerate the token addresses every decoder script filters by. Confirm both `USDC.e` and `USDC` are watched. If not, add both.

This was not directly observable in the audit (we used `/activity` which is token-agnostic) but is a likely cause of any residual decoder vs `/profit` gap >1 %.

## 7. Fix #6 — populate `_master_catalog.csv` with corrected lifetime PnL (LOW)

After Fix #1-#3 land, re-run the catalog builder. Replace any "decoder estimate" columns with the lb-api numbers. Add columns:

- `pm_lifetime_profit` (from `/profit?window=all`)
- `pm_30d_profit`
- `pm_7d_profit`
- `pm_30d_volume`
- `pm_maker_rebate_share` (income fraction from rebates)
- `pm_current_value` (open inventory MTM)
- `pm_n_open_positions`

Cache the API responses in `cache/_pm_portfolio/<wallet>.json` for replay. Refresh weekly.

## 8. Rollout checklist

- [ ] Read `migration_ireland_shadow_2026_05_21/portfolio_audit/PORTFOLIO_AUDIT_REPORT.md` end-to-end.
- [ ] Apply Fix #1 to `cash_pnl.py` / `compute_pnl.py` / `analyze_wallet.py` (find all places).
- [ ] Apply Fix #2 — add `pull_polymarket_api.py` as the canonical activity source (reference: `migration_ireland_shadow_2026_05_21/portfolio_audit/pull_polymarket_api.py` already implements this).
- [ ] Apply Fix #4 (CONVERT → CONVERSION rename).
- [ ] Apply Fix #5 (USDC.e + USDC).
- [ ] Re-run `cash_pnl(wallet)` on all 6 audited wallets. Verify within 1 % of lb-api `/profit?window=all`.
- [ ] Re-run `_master_catalog.csv` builder; replace decoder columns with lb-api columns.
- [ ] Spot-check 3 other wallets from the catalog (not in audit set) for sanity.

## 9. Knock-on effects

After this fix lands, RE-AUDIT these claims from `MAKER_ARB_DEPLOY_REPORT_2026_05_21.md`:

- "ACC-M's true cash PnL is −$1.02/slug" — likely also under-stated because shadow CSV doesn't carry REDEEM income; need to wire that in the shadow engine too (separate spec).
- "ACC-M is the wrong template / 0x04b6d7e9 is sell-side mint-and-sell" — DEMONSTRATED FALSE by Fix #1's audit. 0x04b6d7e9 is a paired-bid maker hold-to-expiry, same as ACC-M.
- "MAS is structurally negative" — MAS gets rebate income that the engine doesn't fully credit; re-verify after F1 (canonical fees + rebates) lands.
- "PAT is structurally dead" — PAT-SHADOW emits 4,775 MERGE rows / 25h, each adding ~$1 in cash_recovered. The engine DOES book MERGE correctly. But it doesn't book REDEEM-equivalent income at slug close for paired residual. Re-audit.

## 10. Files written

- This spec: `strategy_lab/reports/WALLET_DECODER_FIX_SPEC_2026_05_21.md`
- Reference implementation: `migration_ireland_shadow_2026_05_21/portfolio_audit/pull_polymarket_api.py`
- Reconciliation table: `migration_ireland_shadow_2026_05_21/portfolio_audit/per_wallet_reconciled.csv`
- Audit report: `migration_ireland_shadow_2026_05_21/portfolio_audit/PORTFOLIO_AUDIT_REPORT.md`
