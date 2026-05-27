# TV Agent Spec — New V2 Sleeves + PAT Deprecation

**Date**: 2026-05-27
**Scope**: deploy the post-fix variants as NEW sleeve_ids (V2) so they run alongside the existing V1 sleeves for A/B comparison. Deprecate PAT-SHADOW. Add eth_15m cells for ACC-H + ACC-PC.
**Effort**: ~6-8 dev-hours
**Status**: ready for TV agent

## 0. Why "new sleeve_ids" not "in-place update"

If we mutate the existing ACC-M btc 5m to disable PAT, we lose the ability to compare before/after on the same shadow data — and any future regression in V1 numbers is unattributable. By spinning up V2 variants with new sleeve_ids:

- V1 keeps running (small capital, paper-mode)
- V2 runs in parallel with the proposed config
- After 7-14 days, V2 numbers prove out before V1 is killed
- Dashboard shows both → operator sees the delta in real time

Each V2 sleeve gets its own CSV filename (`acc-m-v2_<date>.csv`) and dashboard row.

## 1. Sleeve roster after this PR

| sleeve_id | code | cell | mode | notes |
|---|---|---|---|---|
| `poly_acc_m_btc_5m_shadow` | ACC-M | btc_5m | shadow (V1 keep) | existing — paired-bid maker + PAT overlay |
| `poly_acc_m_v2_btc_5m_shadow` | ACC-M-V2 | btc_5m | shadow (NEW) | **PAT disabled** + convergence-cancel T-60s |
| `poly_acc_h_btc_15m_shadow` | ACC-H | btc_15m | shadow (V1 keep) | existing |
| `poly_acc_h_v2_btc_15m_shadow` | ACC-H-V2 | btc_15m | shadow (NEW) | + convergence-cancel T-120s |
| `poly_acc_h_v2_eth_15m_shadow` | ACC-H-V2 | eth_15m | shadow (NEW CELL) | + convergence-cancel T-120s |
| `poly_acc_pc_btc_15m_shadow` | ACC-PC | btc_15m | shadow (V1 keep) | existing |
| `poly_acc_pc_v2_btc_15m_shadow` | ACC-PC-V2 | btc_15m | shadow (NEW) | + convergence-cancel T-120s |
| `poly_acc_pc_v2_eth_15m_shadow` | ACC-PC-V2 | eth_15m | shadow (NEW CELL) | + convergence-cancel T-120s |
| `poly_mas_btc_5m_shadow` | MAS | btc_5m | shadow (V1 keep) | existing |
| `poly_mas_v2_btc_5m_shadow` | MAS-V2 | btc_5m | shadow (NEW) | + min_ask=0.52 + UTC-hour-4 block + sum_asks gates + convergence-cancel |
| `poly_mas_btc_15m_shadow` | MAS | btc_15m | shadow (V1 keep) | flat, leave running |
| `poly_pat_shadow_btc_5m_shadow` | PAT-SHADOW | btc_5m | **DEPRECATED** | stop process. Keep CSV history. See §5. |

After 14d of V2 data with clean delta, kill V1 sleeves and rename V2 → V1.

## 2. Per-sleeve V2 spec

### 2.1 ACC-M-V2 — disable PAT overlay

**Code class**: reuse `AccMStrategy` from existing `strategies/polymarket/maker/acc_m.py`. Add a config-driven PAT disable.

**Config**:
```python
class Settings(BaseSettings):
    tv_poly_maker_acc_m_v2_enabled: bool = True
    tv_poly_maker_acc_m_v2_cells: str = "btc_5m"
    tv_poly_maker_acc_m_v2_enable_pat: bool = False           # ← key change
    tv_poly_maker_acc_m_v2_pat_max_pair_cost: Decimal = Decimal("0.93")  # if pat re-enabled later
    tv_poly_maker_acc_m_v2_stop_posting_offset_s: int = 60    # convergence cancel
    tv_poly_maker_acc_m_v2_post_size: int = 20                # match V1 for clean A/B
    tv_poly_maker_acc_m_v2_max_imbalance_shares: int = 5
    tv_poly_maker_acc_m_v2_absolute_max_inventory: int = 50
    tv_poly_maker_acc_m_v2_block_hours: str = ""              # optional UTC-hour skip list
```

**Code edit** to `acc_m.py`:

Add an `__init__` parameter `variant: str = "v1"`. In `_pat_decisions` (the PAT overlay):
```python
def _pat_decisions(self, state, up_evt, dn_evt, ts_us):
    cfg = self.config
    if self.variant == "v2":
        if not getattr(cfg, "tv_poly_maker_acc_m_v2_enable_pat", True):
            return []                                          # V2 PAT disabled
        max_pair_cost = Decimal(str(getattr(cfg, "tv_poly_maker_acc_m_v2_pat_max_pair_cost", "1.00")))
    else:
        max_pair_cost = Decimal(str(getattr(cfg, "tv_poly_maker_pat_max_pair_cost", "1.00")))
    # ... existing pat logic but with the variant-aware threshold ...
```

Same pattern for `_post_decisions` to read `tv_poly_maker_acc_m_v2_post_size`, `block_hours`, `stop_posting_offset_s` when `self.variant == "v2"`.

**Strategy code attribute**:
```python
class AccMStrategy(MakerStrategyBase):
    code: str = "ACC-M"  # base — overridden by V2 subclass
```

Create a thin subclass `AccMV2Strategy(AccMStrategy)`:
```python
class AccMV2Strategy(AccMStrategy):
    code: str = "ACC-M-V2"
    variant: str = "v2"
```

Register in `engine/main.py` parallel to V1 registration (see §3).

**Expected outcome**: same template as V1 minus PAT bleed + minus convergence-window adverse selection. From agent B+A backtest: **+$1,329/day vs V1's −$446/day**.

### 2.2 ACC-H-V2 — add convergence-cancel

Smallest delta. Only adds the T-120s convergence-cancel. Everything else identical to V1.

**Config**:
```python
tv_poly_maker_acc_h_v2_enabled: bool = True
tv_poly_maker_acc_h_v2_cells: str = "btc_15m,eth_15m"          # ← extends to eth_15m
tv_poly_maker_acc_h_v2_stop_posting_offset_s: int = 120
```

**Code**: subclass `AccHV2Strategy(AccHStrategy)`, `code = "ACC-H-V2"`. Apply convergence-cancel gates per `TV_AGENT_FIX_CONVERGENCE_CANCEL_SPEC.md`.

**Expected**: btc_15m baseline +$143/day → **+$224/day**. NEW eth_15m → est. +$150-200/day (backtest under-captured edge but WR 61.6% suggests strong signal — run shadow 14d before sizing up).

### 2.3 ACC-PC-V2 — add convergence-cancel + same eth_15m

```python
tv_poly_maker_acc_pc_v2_enabled: bool = True
tv_poly_maker_acc_pc_v2_cells: str = "btc_15m,eth_15m"
tv_poly_maker_acc_pc_v2_stop_posting_offset_s: int = 120
```

Subclass `AccPCV2Strategy(AccPCStrategy)`. Expected: btc_15m baseline +$73/day → **+$228/day**.

### 2.4 MAS-V2 — min_ask + UTC block + sum_asks gates + convergence

```python
tv_poly_maker_mas_v2_enabled: bool = True
tv_poly_maker_mas_v2_cells: str = "btc_5m"
tv_poly_maker_mas_v2_min_ask_price: Decimal = Decimal("0.52")      # NEW
tv_poly_maker_mas_v2_max_ask_price: Decimal = Decimal("0.95")
tv_poly_maker_mas_v2_block_hours: str = "4"                         # NEW
tv_poly_maker_mas_v2_min_sum_asks: Decimal = Decimal("1.005")       # NEW
tv_poly_maker_mas_v2_max_sum_asks: Decimal = Decimal("1.015")       # NEW
tv_poly_maker_mas_v2_stop_posting_offset_s: int = 60
tv_poly_maker_mas_v2_pre_mint_usdc: int = 30
```

Subclass `MasV2Strategy(MasStrategy)`. In `_post_ask_decisions` (or wherever MAS posts ASKs), add:
```python
# V2 gates
if self.variant == "v2":
    cfg = self.config
    # Min ask floor (below mint cost basis = guaranteed loss)
    if ask_price < Decimal(str(cfg.tv_poly_maker_mas_v2_min_ask_price)):
        return []
    if ask_price > Decimal(str(cfg.tv_poly_maker_mas_v2_max_ask_price)):
        return []
    # Sum-asks band
    sum_asks = best_ask_up + best_ask_dn
    if not (Decimal(str(cfg.tv_poly_maker_mas_v2_min_sum_asks)) <= sum_asks <= Decimal(str(cfg.tv_poly_maker_mas_v2_max_sum_asks))):
        return []
    # UTC hour block
    utc_hour = (ts_us // 1_000_000 // 3600) % 24
    block = {int(h) for h in str(cfg.tv_poly_maker_mas_v2_block_hours).split(",") if h.strip()}
    if utc_hour in block:
        return []
```

**Expected**: V1 −$34/day → V2 **+$60-100/day**.

### 2.5 ACC-H-V2 on eth_15m + ACC-PC-V2 on eth_15m

Same code as btc_15m variants. New cell registration only — covered by `_cells = "btc_15m,eth_15m"` in §2.2 and §2.3.

**Shadow mode 14 days before any live promotion**. Hard gates:
- WR ≥ 55% over last 100 fires per cell
- Mean honest cash $/slug ≥ +$0.50
- Total cell $/day ≥ +$30
- 3σ DD ≤ −$200/day

## 3. Engine wiring (`engine/main.py`)

After existing V1 strategy registration, add:

```python
# === V2 sleeve registrations ===
if settings.tv_poly_maker_acc_m_v2_enabled:
    for _cell in settings.tv_poly_maker_acc_m_v2_cells.split(","):
        _asset, _tf = _parse_cell(_cell.strip())
        _maker_strategies.append(AccMV2Strategy(settings, _asset, _tf))

if settings.tv_poly_maker_acc_h_v2_enabled:
    for _cell in settings.tv_poly_maker_acc_h_v2_cells.split(","):
        _asset, _tf = _parse_cell(_cell.strip())
        _maker_strategies.append(AccHV2Strategy(settings, _asset, _tf))

if settings.tv_poly_maker_acc_pc_v2_enabled:
    for _cell in settings.tv_poly_maker_acc_pc_v2_cells.split(","):
        _asset, _tf = _parse_cell(_cell.strip())
        _maker_strategies.append(AccPCV2Strategy(settings, _asset, _tf))

if settings.tv_poly_maker_mas_v2_enabled:
    for _cell in settings.tv_poly_maker_mas_v2_cells.split(","):
        _asset, _tf = _parse_cell(_cell.strip())
        _maker_strategies.append(MasV2Strategy(settings, _asset, _tf))
```

Add shadow loggers for each V2 code:

```python
_maker_shadow_loggers["ACC-M-V2"] = AsyncShadowLogger("acc-m-v2", _maker_log_dir, ...)
_maker_shadow_loggers["ACC-H-V2"] = AsyncShadowLogger("acc-h-v2", _maker_log_dir, ...)
_maker_shadow_loggers["ACC-PC-V2"] = AsyncShadowLogger("acc-pc-v2", _maker_log_dir, ...)
_maker_shadow_loggers["MAS-V2"] = AsyncShadowLogger("mas-v2", _maker_log_dir, ...)
```

Result: separate CSV files at `/var/log/tv/maker/acc-m-v2_<date>.csv` etc.

## 4. sleeve_id naming

Each strategy's `sleeve_id` building convention (in `base.py` or wherever it's constructed):

```python
sleeve_id = f"poly_{self.code.lower().replace('-','_')}_{self.asset.lower()}_{self.tf}_shadow"
```

This yields:
- `poly_acc_m_v2_btc_5m_shadow`
- `poly_acc_h_v2_btc_15m_shadow`
- `poly_acc_h_v2_eth_15m_shadow`
- `poly_acc_pc_v2_btc_15m_shadow`
- `poly_acc_pc_v2_eth_15m_shadow`
- `poly_mas_v2_btc_5m_shadow`

API endpoint `/maker_sleeves` will auto-pick these up — no separate dashboard changes needed (CSV-discovery handles it).

## 5. PAT-SHADOW deprecation

PAT-SHADOW is `poly_pat_shadow_btc_5m_shadow`. Standalone PnL is **−$2,983/day** (May 25-27 honest cash). Structural bleed at current config. No fix path identified.

**Action**:
1. Set `TV_POLY_MAKER_KILL=PAT-SHADOW:btc_5m` in `/etc/tv/tradingvenue.env` — engine drops the strategy at boot.
2. Mark `PAT-SHADOW` code class as `@deprecated` in `pat_shadow.py` source (docstring header).
3. Move `pat_shadow.py` → `pat_shadow_DEPRECATED.py`? **NO** — leave the file in place because the inherited PAT path on ACC-M still imports from `acc_m.py`'s parent. Just disable the standalone sleeve.
4. Operator-side: keep the existing CSVs at `/var/log/tv/maker/pat-shadow_*.csv` for historical reference. New CSV files stop after restart.

Confirm kill landed: post-restart, `journalctl -u tv-engine | grep PAT-SHADOW` should show "kill set: PAT-SHADOW:btc_5m" + zero new `pat-shadow_*.csv` writes.

## 6. Smoke test after deploy

After Phase 0 fixes land + tv-engine restarts + 6h soak:

1. Verify new CSV files exist:
   ```
   ls /var/log/tv/maker/acc-m-v2_*.csv acc-h-v2_*.csv acc-pc-v2_*.csv mas-v2_*.csv
   ```
2. Verify NO new pat-shadow_*.csv:
   ```
   ls /var/log/tv/maker/pat-shadow_$(date +%F).csv 2>&1   # should error
   ```
3. Verify V1 sleeves keep running (parallel):
   ```
   ls /var/log/tv/maker/acc-m_$(date +%F).csv             # should exist
   ```
4. Verify V2 has correct config applied — pull one slug's CSV, confirm:
   - ACC-M-V2: zero TAKE rows with `trigger_reason` starting with `pat_pair_cost` (PAT disabled)
   - ACC-H-V2: cancellation rows with `trigger_reason="convergence_window_cancel"` near slug end
   - MAS-V2: zero POST_ASK rows with `price < $0.52`
   - MAS-V2: zero rows with UTC hour = 4

5. After 24h, run the re-audit runbook (`SHADOW_PNL_REAUDIT_RUNBOOK_2026_05_21.md`) — compare V2 vs V1 per-sleeve $/day.

Pass criterion: V2 sleeves' honest $/day ≥ V1 baseline + 80% of expected delta.

## 7. Rollout checklist

- [ ] Land F1 (canonical fees) — confirmed already deployed ✓
- [ ] Land F-convergence-cancel per `TV_AGENT_FIX_CONVERGENCE_CANCEL_SPEC.md` for V2 strategies
- [ ] Add V2 strategy subclasses (4 new classes + variant flag pattern in base)
- [ ] Add 4 V2 sleeve registrations in `engine/main.py`
- [ ] Add 4 V2 shadow loggers
- [ ] Extend `sleeve_id` builder if needed for V2 naming
- [ ] Update `Settings` with all V2 config fields
- [ ] Set `TV_POLY_MAKER_KILL=PAT-SHADOW:btc_5m` to disable PAT-SHADOW
- [ ] Add unit tests for the new V2 classes (mirror V1 tests with V2 config)
- [ ] Restart `tv-engine.service`
- [ ] Smoke test (§6)
- [ ] Wait 24-48h, run re-audit
- [ ] If V2 numbers hit projections (≥80% of expected delta), kill V1 in 14 days
- [ ] If V2 underperforms, investigate the gap; do NOT kill V1

## 8. Capital sizing (post-deploy, V2 active)

| Sleeve | Wallet USDC | Expected $/day |
|---|---:|---:|
| ACC-M-V2 btc_5m | $84 | +$1,329 |
| ACC-H-V2 btc_15m | $84 | +$224 |
| ACC-H-V2 eth_15m | $84 (new shadow) | +$150-200 est |
| ACC-PC-V2 btc_15m | $104 | +$228 |
| ACC-PC-V2 eth_15m | $104 (new shadow) | +$150-200 est |
| MAS-V2 btc_5m | $78 | +$60-100 |
| MAS btc_15m (V1 unchanged) | $78 | +$5 |
| **Total** | **~$616** | **~+$2,150** |

(Live deployment would use 1 wallet shared across same-cell strategies; total per-cell ~$200-300 max because ACC-H and ACC-PC posting on same cell uses one capital pool. Need cross-cell exclusivity decision before live — covered in §9.)

## 9. Cross-cell exclusivity (open question for live)

On btc_15m, V2 has both `ACC-H-V2` AND `ACC-PC-V2` registered. Shadow handles each separately (no shared wallet). LIVE would need ONE of them per cell to avoid double-posting.

**Recommendation**: in shadow keep BOTH running (gives A/B data). When promoting to live:
- Pick whichever has better last-7d $/slug
- Set `TV_POLY_MAKER_KILL=<loser>:<cell>`

Quantify the choice from shadow data after Phase 1.

## 10. Acceptance criteria (when do we consider this PR successful?)

After 14 days of post-deploy shadow:

1. ACC-M-V2 btc_5m honest cash $/day **≥ 4× ACC-M (V1)** at same volume
2. ACC-H-V2 btc_15m honest cash $/day ≥ 1.4× ACC-H (V1) — captures convergence-cancel benefit
3. ACC-PC-V2 btc_15m honest cash $/day ≥ 2× ACC-PC (V1)
4. MAS-V2 btc_5m honest cash $/day ≥ +$50 (vs V1 at −$34)
5. PAT-SHADOW shows zero new CSV writes (confirms kill)
6. Total shadow $/day across V2 sleeves: **≥ +$1,500** (vs current V1 sum: −$430)

If all 6 met → promote top 2-3 to paper-deploy at $25 stake per `TV_AGENT_FIX_F1_SPEC.md` Phase 1.

## 11. References

- Loss decomp: `migration_ireland_shadow_2026_05_27/loss_decomp/acc_m_btc_5m_optimization.md` + `mas_btc_5m_optimization.md`
- Convergence backtest: `migration_ireland_shadow_2026_05_27/convergence_backtest/CONVERGENCE_REPLAY_REPORT.md`
- Cross-cell backtest: `migration_ireland_shadow_2026_05_27/cross_cell_backtest/CROSS_CELL_BACKTEST_REPORT.md`
- Convergence cancel spec: `strategy_lab/reports/TV_AGENT_FIX_CONVERGENCE_CANCEL_SPEC.md`
- Deploy decisions: `strategy_lab/reports/MAKER_ARB_DEPLOY_DECISIONS_2026_05_27.md`
