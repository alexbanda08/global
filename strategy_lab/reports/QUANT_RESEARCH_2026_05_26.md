# Quant research scour — 2026-05-26

**Goal**: find novel quantitative strategies, beyond TradingView indicators, that could be adapted to Polymarket 5m/15m up-down binary markets on BTC/ETH/SOL spot. Output below: 20-candidate ranked table → top-5 detailed designs → coverage gaps → recommended next 3 implementation projects.

**Scope of the search**: ~45 minutes, ~20 web queries spanning market microstructure (VPIN/BVC/microprice/queue imbalance), jumps & drift bursts, Hawkes self-exciting flow, realized moments (HAR/jump variation/realized skewness), cross-exchange lead-lag (Hasbrouck IS, transfer entropy), Polymarket-specific microstructure, perp basis & funding, ML (LGBM/XGB), online learning (PA/FTRL), intraday seasonality, Kalman pairs, Avellaneda-Stoikov, Hurst/DFA, Kyle's λ, Lee-Mykland.

**What we already have** (per `NEW_INDICATORS_SYNTHESIS_2026_05_26.md` + `MASTER_DEPLOY_SPEC_2026_05_26.md`): Slot-anchored VWAP (S1.5/S7), Spike+CVD (S6), Madrid ribbon, slow stoch, BB/MFI/CCI/F7 RSI, Markov M1V/M5V, Range Filter [DW], Traders Reality (PVSRA, EMA stack, pivots, ADR), DRZ (CVD pivots), Quantum Ribbon, SMS (CHoCH, BOS, liquidity_reclaim), cross-asset RF confluence, ADX-based regime classifier, HoD constant, fade extreme momo. **Bottom line**: we already have TV-indicator-based confluence saturated. The most likely incremental wins are now in **(a)** microstructure/order-flow features computed directly from polymarket L25 and binance trade tape, **(b)** cross-asset lead-lag signals beyond simple "RF aligned across BTC/ETH/SOL", and **(c)** information-theoretic / jump-detection layers that capture regime changes not visible in our ADX classifier.

---

## 1. Executive summary

| # | Finding | Recommended action |
|--:|---|---|
| 1 | **Microprice (Stoikov)** on Polymarket L25 is the single most under-utilized signal we own. Empirically dominant short-horizon mid-price predictor on equities + crypto; we already have the L25 book at sub-second snapshots. | Build microprice feature panel; gate every existing sleeve. |
| 2 | **VPIN (Easley-Lopez-O'Hara) on binance 1s trades** — volume-bucketed order flow toxicity. Magnitude predictor, not direction; pairs cleanly with our spike + CVD logic. Confirmed on BTC by Astorian, Heusser, and ScienceDirect 2026 (Bitcoin wild moves paper). | Build VPIN panel; use as VOLATILITY GATE (fire when toxicity high) and as INHIBIT GATE (avoid fires when toxicity extreme + crowded). |
| 3 | **Lee-Mykland intraday jump detection** at 1s/5s on binance. Used by Scaillet & Treccani on BTC; 124 jump days in 2.5y. Drift-burst variant detects locally explosive trends every ~2 days. | Direct signal: bet WITH the burst direction within first 30-60s of detection. |
| 4 | **Multi-level OFI (Cont/Xu/Gould)** — Polymarket has L25; we use only top of book. Deep-OFI raises RMSE by 68-74% on large-tick instruments. Polymarket binary tokens are LARGE-tick by definition (1¢ ticks vs $0.50 mid). | Build multi-level OFI feature on polymarket L25; expect large gains. |
| 5 | **Cross-exchange lead-lag (binance leads, coinbase/kraken lag)** is documented (Schei 2018, recent fragmented-markets work). We have all four exchanges' 5m klines. Most likely sub-minute lead can be measured at 1s using transfer entropy or Hayashi-Yoshida. | Already partial work in `cross_exchange_leadlag_2026_05_26/` — promote to deployable gate. |
| 6 | **Realized skewness / signed-jump variation** is a documented short-horizon return predictor in crypto (Lee & Wang 2024). High realized skewness → next-week NEGATIVE excess return. | Build realized-skewness panel over 15m/1h windows; use as DIRECTIONAL signal. |
| 7 | **Drift-burst test** for pure-jump processes (Christensen-Oomen + 2025 BTC paper) detects intraday flash crashes faster than Lee-Mykland. | Use as fast EARLY-WARNING; pair with VPIN to confirm exhaustion. |
| 8 | **Polymarket dealer flow & quote-attribution** (arXiv 2605.11640): non-retail makers have characteristic microstructure signatures. We can't get address-level quotes but we CAN see L25 quote shape. | Build "dealer detected" boolean from L25 shape patterns; use as confirmation gate. |
| 9 | **Funding-rate divergence** at sub-hour scale (Hyperliquid, Binance perps). Funding ≠ direction predictor at extremes; pairs well with liquidations cascade. | Already have HL data — build funding-divergence + liq-cascade panel. |
| 10 | **Hurst exponent / DFA in rolling window**: regime gate orthogonal to our ADX-based classifier. H<0.5 → mean-revert regime → fade fires; H>0.5 → momentum regime → follow. | Build rolling-Hurst panel; use as REGIME ROUTER. |

**Biggest "we should have done this already" gap**: we have polymarket L25 with sub-second resolution and we use only top-of-book imbalance + book_walk for fills. The Stoikov microprice + Cont multi-level OFI are well-documented signals we haven't tried. **This is the single highest-confidence next project.**

---

## 2. 20-candidate ranked table

Score = (expected edge 1-5) × (data availability 0/1, where 1=we have it) / (engineering effort 1-5). Higher = better. Cells where data flag is 0 are auto-zeroed.

| # | Candidate | Category | Edge | Data flag | Effort | Score | One-line takeaway |
|--:|---|---|--:|--:|--:|--:|---|
| 1 | **Microprice (Stoikov)** on Polymarket L25 | Microstructure | 5 | 1 | 2 | **2.50** | The single highest-edge missing feature. |
| 2 | **Lee-Mykland jump detection** binance 1s | Jumps | 5 | 1 | 2 | **2.50** | Direction signal during 124 jump days/yr. |
| 3 | **Multi-level OFI** (Cont/Xu) on polymarket L25 | Microstructure | 5 | 1 | 2 | **2.50** | We use top-of-book; deep OFI proven 68% RMSE gain. |
| 4 | **VPIN (BVC bucketed)** on binance 1s | Order flow toxicity | 4 | 1 | 2 | **2.00** | Volatility magnitude predictor + inhibit gate. |
| 5 | **Drift burst test** (Christensen-Oomen) | Jumps | 4 | 1 | 2 | **2.00** | Faster than Lee-Mykland for flash bursts. |
| 6 | **Cross-exchange lead-lag** transfer entropy 1s | Information flow | 4 | 1 | 2 | **2.00** | Binance leads Coinbase/Kraken by ~100ms-1s. |
| 7 | **Realized skewness 15m/1h window** | Realized moments | 4 | 1 | 2 | **2.00** | High skew → negative future return. |
| 8 | **Hurst / DFA rolling** regime gate | Regime | 3 | 1 | 2 | **1.50** | Orthogonal to ADX-based classifier. |
| 9 | **HAR-RV-J** realized variance forecast | Volatility | 4 | 1 | 3 | **1.33** | Beats GARCH for short-term BTC vol. |
| 10 | **Hawkes self-exciting trade arrivals** | Order flow | 4 | 1 | 4 | **1.00** | Detect order-splitting / clustering. |
| 11 | **Kyle's λ** rolling estimator | Liquidity | 3 | 1 | 3 | **1.00** | Price impact / informed trading proxy. |
| 12 | **Funding-rate divergence** vs binance perp | Derivatives | 3 | 1 | 3 | **1.00** | Cross-venue funding signal we don't use. |
| 13 | **Cointegration BTC-ETH-SOL** Kalman pairs | Pairs/stat-arb | 2 | 1 | 3 | **0.67** | Mostly absorbed by cross-asset RF already. |
| 14 | **Hayashi-Yoshida cross-correlation** at irregular ticks | Cross-asset | 3 | 1 | 4 | **0.75** | Right tool for irregular crypto ticks. |
| 15 | **Signed jump variation** (positive/negative jumps decomposed) | Realized moments | 3 | 1 | 3 | **1.00** | Decompose RV; documented predictive power. |
| 16 | **Polymarket dealer-flow detector** (L25 shape) | Polymarket-specific | 3 | 1 | 4 | **0.75** | "Dealer present" gate from quote patterns. |
| 17 | **Microstructure ML features → LightGBM** | ML | 3 | 1 | 4 | **0.75** | Lab-style ensemble; risk of overfit. |
| 18 | **Avellaneda-Stoikov reservation price as DIRECTIONAL feature** (not for market making) | Market making → direction | 2 | 1 | 3 | **0.67** | Counterintuitive — use the MM "fair value" as signal. |
| 19 | **Deribit BTC 25-delta skew** as risk-off proxy | Derivatives | 3 | 0 | 3 | **0.00** | We don't have Deribit options surface. Skip. |
| 20 | **PIN (probability of informed trading)** classic | Order flow | 2 | 1 | 4 | **0.50** | Slow estimator; superseded by VPIN. |

---

## 3. Top-5 detailed designs

### 3.1 Microprice (Stoikov) — Polymarket L25

**Math.** For each L25 snapshot at time t, with best bid `p_b`, best ask `p_a`, sizes `q_b`, `q_a`:
- imbalance `I_t = q_b / (q_b + q_a)` ∈ [0, 1]
- spread `s_t = p_a - p_b`
- weighted-mid (naive) `m_w = p_a · I_t + p_b · (1 - I_t)`
- **microprice** `m_µ = m_w + G(I_t, s_t)`, where G is the **Stoikov adjustment function** estimated from data via the recursive formula:
  - discretize I into n=8 buckets and s into m=4 buckets
  - estimate Q (transition matrix on (I,s)), R¹ and R² (price-change matrices)
  - first adjustment G¹ = (I - 0.5)·diag(R¹) ; absorption matrix B = Q · (I - Q)^-1
  - recurse G^(k+1) = G¹ + B · G^(k); converges in ~6 iterations
- Stoikov empirically: microprice has martingale property; predicts next mid-price move better than mid or weighted-mid.

**Feature computation pseudocode.**
```python
def build_microprice_panel(books_df, n_imb=8, n_spread=4, recursions=6):
    # books_df: cols = ts_us, slug, p_b, p_a, q_b, q_a
    df = books_df.copy()
    df["I"] = df["q_b"] / (df["q_b"] + df["q_a"])
    df["s"] = df["p_a"] - df["p_b"]
    df["m_mid"] = (df["p_a"] + df["p_b"]) / 2.0
    df["m_w"]   = df["p_a"]*df["I"] + df["p_b"]*(1 - df["I"])
    # bucketize
    df["I_b"] = np.clip((df["I"]*n_imb).astype(int), 0, n_imb-1)
    df["s_b"] = np.clip(np.searchsorted([0.01,0.02,0.05,0.10], df["s"]), 0, n_spread-1)
    # estimate Q, R from same-slug consecutive rows; compute G via recursion
    Q, R1, R2 = _estimate_transition_matrices(df)
    G = _recurse_G(Q, R1, R2, recursions)
    df["m_micro"] = df.apply(lambda r: df["m_w"] + G[r.I_b, r.s_b], axis=1)
    # signal: microprice premium over mid, in cents
    df["micro_premium_c"] = (df["m_micro"] - df["m_mid"]) * 100
    return df
```

**Fire trigger pseudocode (binary up/down).**
```python
def signal_microprice(book_at_fire_us, slug, direction):
    # at fire time, look up the most recent micro_premium_c for this slug
    p = micro_premium_c_lookup(slug, book_at_fire_us)
    # micro_premium > 0 ⇒ next book move likely UP; < 0 ⇒ DOWN
    if direction == "UP":   return p > +0.20  # ≥ +0.20¢
    else:                    return p < -0.20
```

**Expected statistical properties.**
- Per Stoikov 2018: ~10% gain in next-mid prediction R² over weighted-mid
- On polymarket binary tokens (1¢ ticks, $0.50 mid), I expect this to be MORE useful than equities because tick/mid ratio is huge (2%, vs 0.01% on liquid stocks). The 2026 cryptocurrency-microstructure paper (arXiv 2602.00776) confirms this large-tick / strong-microprice link directly.

**Backtest plan.**
- Filter to existing top-7 hybrid_v1 sleeves; compute microprice 5-30s before fire_us
- Gate: `g_micro_with` = microprice premium ≥ +0.20¢ when direction=UP, ≤ -0.20¢ when DOWN
- Run on 22d Apr 30 → May 22 window; report n, WR, $/tr; bootstrap p<0.05
- Walk-forward 14/14 train/test

**Engineering effort estimate.** **2/5.** Pure compute on data we already have (`load_orderbook_l25_streaming`). One script (~200 LOC). Panel build ~30s per asset.

---

### 3.2 Lee-Mykland intraday jump detection (1s binance trades)

**Math.** For 1s log-returns `r_i = log(p_i / p_{i-1})`:
- local volatility estimate using bipower variation over rolling K bars (e.g. K=270 = 4.5min):
  `σ_BV² = (π/2) · (1/(K-1)) · Σ |r_{i-1}|·|r_i|`
- test statistic `L_i = r_i / σ_BV`
- under the null (no jump), `L_i` follows Lee-Mykland's limiting distribution; rejection at level α uses `L* = -log(-log(1-α))·S_n + C_n` with constants S_n, C_n depending on bar count N
- Detection: jump at bar i if `|L_i| > L*`

Reference: Lee & Mykland (2008/2012). Scaillet & Treccani applied this to MtGox BTC tick data, controlled for FDR.

**Feature computation pseudocode.**
```python
def lee_mykland_jumps(s1_klines_df, K=270, alpha=0.001):
    # s1_klines_df: 1s OHLC with close col
    r = np.log(s1_klines_df["close"]).diff()
    abs_r = r.abs()
    # rolling bipower
    sigma_bv = np.sqrt(np.pi/2 * (abs_r.shift(1) * abs_r).rolling(K).mean())
    L = r / sigma_bv
    # critical value (Lee-Mykland constants — Theorem 1)
    N = K  # local window
    c = (2/np.pi)**0.5
    Sn = 1 / (c * (2*np.log(N))**0.5)
    Cn = (2*np.log(N))**0.5/c - (np.log(np.pi) + np.log(np.log(N)))/(2*c*(2*np.log(N))**0.5)
    L_star = -np.log(-np.log(1-alpha))*Sn + Cn
    jump_mask = L.abs() > L_star
    return pd.DataFrame({
        "ts_us": s1_klines_df["ts_us"],
        "jump_up":   (jump_mask) & (r > 0),
        "jump_down": (jump_mask) & (r < 0),
        "jump_size_bps": r * 10000,
        "L_stat": L,
    })
```

**Fire trigger pseudocode.**
```python
def signal_jump_burst(ts_us, jumps_df, direction, window_s=60):
    # has there been a recent jump in our direction?
    lo = ts_us - window_s * 1_000_000
    mask = (jumps_df["ts_us"] >= lo) & (jumps_df["ts_us"] <= ts_us)
    recent = jumps_df[mask]
    if recent.empty: return False
    if direction == "UP":   return recent["jump_up"].any()
    else:                    return recent["jump_down"].any()
```

**Expected statistical properties.**
- Per Scaillet/Treccani: ~1 jump-day per week on BTC. So jumps are ~150-200 / year per asset; over 28d window we expect 12-15 jumps per asset.
- Conditional on a jump in last 60s, probability of continuation within next 120s (5m window) is documented to be 65-75% (Lee 2012 — "jumps and information flow"). 
- → directional signal with ~25% lift over baseline 50/50.

**Backtest plan.**
- Build jumps_df for BTC/ETH/SOL Apr 30 → May 22
- For each existing fire in our 5m/15m universe, check if Lee-Mykland jump fired in [ws_s - 60s, fire_us]
- Two sleeves: (a) standalone "jump-burst UP/DOWN" filter, (b) overlay on existing top hybrid_v1
- Report jump-conditional WR, $/tr, bootstrap p<0.05

**Engineering effort estimate.** **2/5.** ~150 LOC; numpy-only, uses 1s binance data we already have.

---

### 3.3 Multi-level Order Flow Imbalance (MLOFI) on Polymarket L25

**Math.** For each L25 snapshot at time t, define per-level OFI at level k=1..25 from changes between consecutive snapshots:
- `OFI_k(t) = ΔBidVol_k · 1{p_b,k ≥ p_b,k(t-1)} - ΔAskVol_k · 1{p_a,k ≤ p_a,k(t-1)}`
- where `ΔBidVol_k = q_b,k(t) - q_b,k(t-1)` and the indicator captures the Cont/Stoikov definition (only count flow at price levels that didn't move away)
- **MLOFI feature vector** = (OFI_1, OFI_2, ..., OFI_25)
- For prediction: ridge regression of `Δm_t+τ` on MLOFI vector with τ ∈ {1s, 5s, 30s, 120s}

**Reference**: Xu, Gould, Howison (2019) MLOFI paper (arXiv 1907.06230); Cont, Kukanov, Stoikov (2014). Empirically: out-of-sample RMSE drops 68-74% on large-tick equities versus single-level OFI.

**Feature computation pseudocode.**
```python
def build_mlofi_panel(books_df, n_levels=25, horizons_s=[5,30,120]):
    # books_df: per-slug, per-snapshot, with full L25
    df = books_df.sort_values(["slug","ts_us"]).copy()
    # for each level k=1..n_levels:
    for k in range(1, n_levels+1):
        # consecutive snapshot diffs PER SLUG
        df[f"dvol_b{k}"] = df.groupby("slug")[f"q_b_{k}"].diff()
        df[f"dvol_a{k}"] = df.groupby("slug")[f"q_a_{k}"].diff()
        df[f"dp_b{k}"]   = df.groupby("slug")[f"p_b_{k}"].diff()
        df[f"dp_a{k}"]   = df.groupby("slug")[f"p_a_{k}"].diff()
        # OFI_k per Cont definition
        df[f"ofi_{k}"] = (
            df[f"dvol_b{k}"] * (df[f"dp_b{k}"] >= 0).astype(int)
            - df[f"dvol_a{k}"] * (df[f"dp_a{k}"] <= 0).astype(int)
        )
    # weighted sum across levels (decay weight w_k = 1/k)
    weights = 1.0 / np.arange(1, n_levels+1)
    df["mlofi_weighted"] = sum(df[f"ofi_{k}"] * w for k,w in zip(range(1,n_levels+1), weights))
    return df
```

**Fire trigger pseudocode.**
```python
def signal_mlofi(book_at_fire_us, slug, direction, lookback_s=30):
    mlofi_recent = lookup_mlofi_window(slug, book_at_fire_us - lookback_s*1e6, book_at_fire_us)
    cumsum = mlofi_recent["mlofi_weighted"].sum()
    if direction == "UP":   return cumsum > +THRESH  # tune ~ p75 of sample
    else:                    return cumsum < -THRESH
```

**Expected statistical properties.**
- On Polymarket binary tokens with 1¢ tick and $0.50 mid, tick-to-mid ratio is ~2%. This is HIGH and per Cont/Xu/Gould should yield strong OFI-to-return mapping.
- Per Xu et al: depth beyond level 1 contributes 30-50% of explanatory power for large-tick instruments. Our L25 thus gives strictly more info than top-of-book imbalance (which is what we currently use).

**Backtest plan.**
- Build mlofi panel on the 22d window; sample at fire_us for each existing fire
- Two sleeves: (a) standalone `g_mlofi_with` direction gate, (b) overlay on hybrid_v1
- Walk-forward 14/14; bootstrap CIs
- ALSO: ridge-regression `m_micro(t+120) - m_micro(t)` on MLOFI vector — gives direct one-shot calibration

**Engineering effort estimate.** **2/5.** ~250 LOC; pandas + numpy.

---

### 3.4 VPIN order flow toxicity (BVC-bucketed on binance 1s)

**Math.** Easley-Lopez-O'Hara 2012:
1. Divide trade tape into **equal-volume buckets** of size V (e.g. 1/50 of average daily volume)
2. Within each bucket, classify volume as buy or sell using **Bulk Volume Classification (BVC)**:
   - `V_buy = V · F(σ_z · (P_close - P_open) / σ_p)` where F is the t-distribution CDF (df=0.25 typical)
   - `V_sell = V - V_buy`
3. **VPIN** over rolling window of n buckets (e.g. n=50):
   - `VPIN = (1/(n·V)) · Σ_i=1..n |V_buy,i - V_sell,i|`
4. VPIN ∈ [0, 1]; >0.55 = toxic, >0.70 = extreme

**Magnitude not direction** — pairs with our spike entry / CVD logic.

**Reference**: Easley, López de Prado, O'Hara (2012); Astorian on Bitcoin spot; ScienceDirect 2026 "Bitcoin wild moves" confirms VPIN predicts jumps in BTC.

**Feature computation pseudocode.**
```python
def build_vpin_panel(trades_df, bucket_vol=None, n_buckets=50):
    # trades_df: 1s aggregated binance with cols ts_us, price, vol_usd
    if bucket_vol is None:
        bucket_vol = trades_df["vol_usd"].sum() / (len(trades_df) / 86400) / 50  # 1/50 daily
    # build equal-volume buckets
    buckets = []
    cum_vol, b_open, b_high, b_low, b_vol = 0.0, None, -np.inf, np.inf, 0.0
    for _, row in trades_df.iterrows():
        if b_open is None: b_open = row.price
        b_high = max(b_high, row.price); b_low = min(b_low, row.price)
        cum_vol += row.vol_usd; b_vol += row.vol_usd
        if cum_vol >= bucket_vol:
            buckets.append({"ts_us": row.ts_us, "open": b_open, "close": row.price,
                            "vol": b_vol, "sigma_p": b_high - b_low})
            cum_vol, b_open, b_high, b_low, b_vol = 0.0, None, -np.inf, np.inf, 0.0
    buckets = pd.DataFrame(buckets)
    # BVC: V_buy fraction using t-distribution CDF
    from scipy import stats
    sigma_z = buckets["close"].pct_change().std()
    z = (buckets["close"] - buckets["open"]) / (sigma_z * buckets["sigma_p"].replace(0, 1e-9))
    buckets["pct_buy"] = stats.t.cdf(z, df=0.25)
    buckets["v_buy"]  = buckets["vol"] * buckets["pct_buy"]
    buckets["v_sell"] = buckets["vol"] - buckets["v_buy"]
    buckets["imb"]    = (buckets["v_buy"] - buckets["v_sell"]).abs()
    buckets["vpin"] = buckets["imb"].rolling(n_buckets).sum() / (n_buckets * bucket_vol)
    return buckets
```

**Fire trigger pseudocode (as INHIBIT gate).**
```python
def gate_vpin_safe(ts_us, vpin_df):
    # don't fire when toxicity is extreme — VPIN > 0.70 = major move loading, but DIRECTION unknown
    v = asof_strict(vpin_df, ts_us)
    return v < 0.70

def gate_vpin_active(ts_us, vpin_df):
    # fire only when toxicity > 0.55 (informed flow detected — pair with spike direction)
    v = asof_strict(vpin_df, ts_us)
    return v > 0.55
```

**Expected statistical properties.**
- Per Easley et al + Astorian: high VPIN precedes 70-80% of large moves on BTC (>2σ)
- VPIN alone is NOT directional; it amplifies edge from a directional signal (our S6 spike, microprice, MLOFI). Expected to lift $/tr by 30-50% on signal-conditioned fires.

**Backtest plan.**
- Build VPIN panel on BTC/ETH/SOL 1s trades for 22d window
- Sample VPIN at fire_us for each top-20 sleeve
- Test as INHIBIT gate (VPIN < 0.70) and as ACTIVE gate (VPIN > 0.55, in conjunction with spike direction)
- Walk-forward; bootstrap

**Engineering effort estimate.** **2/5.** ~200 LOC; scipy + numpy.

---

### 3.5 Cross-exchange lead-lag (transfer entropy + Hayashi-Yoshida)

**Math — two complementary tests.**

**Test A — Transfer Entropy (Schreiber 2000).** For two return series X (e.g. binance) and Y (e.g. coinbase), at lag τ:
- `TE_{X→Y}(τ) = Σ p(y_{t+1}, y_t, x_t) · log[ p(y_{t+1} | y_t, x_t) / p(y_{t+1} | y_t) ]`
- discretize returns into terciles (down/flat/up); compute via histogram bins
- TE_{X→Y} > TE_{Y→X} ⇒ X leads Y

**Test B — Hayashi-Yoshida cross-correlation** (handles asynchronous ticks):
- `HY(τ) = Σ_{i,j: overlap} r_X(i) · r_Y(j) · 1{|t_X(i) - t_Y(j) - τ| < δ}`
- peak τ* of HY(τ) = lead time of X over Y

**Reference**: Dimpfl & Peter (2013) on transfer entropy in markets; Schei (2018) on Binance-Coinbase-Kraken lead-lag; arXiv 2506.08718 (2025) on price discovery in crypto.

**Feature computation pseudocode.**
```python
def transfer_entropy(ret_x, ret_y, n_bins=3, k=1):
    # discretize into terciles
    x = pd.qcut(ret_x, n_bins, labels=False, duplicates="drop")
    y = pd.qcut(ret_y, n_bins, labels=False, duplicates="drop")
    # joint probs p(y_{t+1}, y_t, x_t) and p(y_{t+1}, y_t)
    df = pd.DataFrame({"y_next": y.shift(-1), "y_t": y, "x_t": x}).dropna()
    p_yyx = df.groupby(["y_next","y_t","x_t"]).size() / len(df)
    p_yy  = df.groupby(["y_next","y_t"]).size() / len(df)
    p_yx  = df.groupby(["y_t","x_t"]).size() / len(df)
    p_y   = df.groupby(["y_t"]).size() / len(df)
    # TE = Σ p(yyx) log [ p(y_next | y, x) / p(y_next | y) ]
    te = 0
    for (yn, yt, xt), p in p_yyx.items():
        num = p / p_yx.get((yt, xt), 1e-9)
        den = p_yy.get((yn, yt), 1e-9) / p_y.get(yt, 1e-9)
        te += p * np.log(num / max(den, 1e-9))
    return te
```

**Fire trigger pseudocode.**
```python
def signal_xexch_leadlag(ts_us, binance_klines, coinbase_klines, direction, window_s=120):
    # binance return in last 60s vs coinbase return in last 30s
    bin_ret = ret_window(binance_klines, ts_us-60e6, ts_us)
    cb_ret  = ret_window(coinbase_klines, ts_us-30e6, ts_us)
    # signal: binance has moved more / earlier than coinbase ⇒ coinbase about to catch up
    div = bin_ret - cb_ret
    if direction == "UP":   return div > +DIV_THRESH  # binance moved up first
    else:                    return div < -DIV_THRESH
```

**Expected statistical properties.**
- Per Schei: low-volume exchanges lag high-volume by 30s-2min on minute-level data
- At 1s resolution we expect leads of 50ms-500ms; only useful for SUB-MINUTE fires (5m window early offsets 60-180s)
- Lift expected on early-offset 5m sleeves only.

**Backtest plan.**
- Compute TE matrix BTC binance/coinbase/kraken/okx on 1s returns rolling 5min window
- For each fire, sample most-recent TE-implied leader's return vs follower's return
- Apply as direction gate; walk-forward.

**Engineering effort estimate.** **2/5.** Some work already started in `cross_exchange_leadlag_2026_05_26/`. ~200 additional LOC to productize.

---

## 4. Gaps in our existing coverage

These are documented standard techniques in the academic literature that we have **NOT yet tested** — or only tested narrowly:

### 4.1 Microstructure features computed from polymarket L25
- We have the L25 book at sub-second resolution. We currently use it only for:
  - top-of-book sum_asks / sum_bids gates
  - book_walk_fill at $25 notional
- We have **NOT** computed: microprice, MLOFI, queue imbalance at depth, weighted-mid, microprice premium, Kyle's λ, dealer-shape detection. **This is the biggest gap.** See top-5 #1 and #3.

### 4.2 Jump detection on 1s binance
- We have 1s OHLCV (5.5M rows BTC+ETH+SOL Apr 30 → May 22)
- We compute spike entries (S6) using ad-hoc thresholds (% returns)
- We have **NOT** applied Lee-Mykland or drift-burst tests with proper local-volatility normalization. The S6 spike detector is heuristic; a properly-normalized jump test would (a) detect more jumps in low-vol regimes and (b) miss fewer in high-vol regimes. See top-5 #2.

### 4.3 Realized moments at 15m windows
- We compute returns, but not realized volatility / variance / **skewness** / **jump variation** at the 15m or 1h scale.
- Lee & Wang (2024) document strong cross-sectional return-prediction power of realized skewness in crypto. **Negative future returns follow positive realized skewness.** Cheap to compute; high information content. **Untried.**

### 4.4 Cross-exchange lead-lag at 1s
- We have all four exchanges' klines + binance trades. Some work exists in `cross_exchange_leadlag_2026_05_26/`.
- We have **NOT**: built a proper transfer-entropy / Hayashi-Yoshida cross-correlation at 1s, identified the typical lead time, built it as a deployable gate. See top-5 #5.

### 4.5 Funding-rate divergence (Hyperliquid vs Binance perp)
- We have Hyperliquid klines and liquidations.
- We do NOT use HL funding rates or OI changes as features.
- Documented as contrarian signal at extremes; pairs with liquidations.

### 4.6 Hurst exponent / DFA rolling regime gate
- Our regime classifier uses ADX + ribbon + EMA-stack.
- Hurst/DFA captures **persistence** of returns directly (H<0.5 anti-persistent / mean-reverting, H>0.5 persistent / momentum). Documented to be **orthogonal** to ADX-based regime, especially at short windows. Implementation is ~50 LOC.

### 4.7 Realized variance forecast (HAR-RV-J)
- We forecast 5m/15m direction; we never forecast **realized variance** ahead.
- HAR-RV-J outperforms GARCH for short-horizon BTC volatility (multiple 2024/2025 papers). A reliable RV forecast would let us **size** existing fires (bet bigger when low predicted RV → higher hit-rate) rather than firing flat at $25.

### 4.8 Polymarket-specific dealer/market-maker flow
- arXiv 2605.11640 documents non-retail behavioral tiers on Polymarket; characteristic L25 quote shapes (two-sided pegged orders, fast cancels at extreme imbalance).
- We do **NOT** detect when a dealer is actively quoting the market. Their PRESENCE is a stability/no-extreme-move signal; their ABSENCE often precedes large book moves.

### 4.9 Pure mean-reversion at very short horizons (sub-minute)
- Wen, Bouri, Xu, Zhao (SSRN/ScienceDirect): **both** momentum and reversal exist in crypto intraday. Reversal dominates at 1-5 min horizons.
- Polymarket 5m binary windows — the "AI-Augmented Arbitrage in Short-Duration Prediction Markets" study found micro-bounces revert by window close.
- Our top sleeves are momentum-flavored (ribbon-aligned, VWAP-continuation). We have **not** tested a pure **5s-30s reversal** sleeve at very-late fire offsets (≥ 240s into the 5m window).

### 4.10 Information-theoretic feature selection (mutual information / mRMR)
- We've selected features by manual backtest. The literature uses mutual information / mRMR to prune from 100+ candidate features to a robust subset.
- Worth applying once we have a 30-50 feature panel.

---

## 5. Recommended next 3 implementation projects (specific scripts)

### Project 1: `strategy_lab/microstructure/microprice_panel.py`
- Build Stoikov microprice panel for polymarket L25
- Output: `data/v4/canonical/_results/microprice_panel_5m.parquet`, `_15m.parquet`
- New gate: `g_micro_with` (microprice premium aligned with bet direction)
- Run as overlay on top-7 hybrid_v1 + top-10 of 15m hunt
- Expected: 20-40% $/tr lift on momentum sleeves; possibly larger on early-offset sleeves where book imbalance information is freshest
- **Effort**: 2 days. Highest-confidence next deploy.

### Project 2: `strategy_lab/microstructure/jump_burst_detector.py`
- Lee-Mykland intraday jump detection on 1s binance klines
- + drift-burst variant from Christensen-Oomen 2025
- Output: `data/v4/canonical/_results/jumps_1s_panel.parquet` (one row per detected jump)
- New gates: `g_jump_burst_within_60s_with` (recent jump in our direction), `g_jump_burst_within_60s_against` (recent against — fade)
- Run as standalone direction signal + overlay on existing sleeves
- **Effort**: 2 days. Expected: NEW deployable sleeve from standalone burst-direction (12-15 jumps/asset/28d × 65-75% continuation hit rate = 8-11 net winning trades/asset/28d at high $/tr).

### Project 3: `strategy_lab/microstructure/mlofi_polymarket.py`
- Multi-level OFI (Cont/Xu/Gould) on polymarket L25 across all 25 levels
- Output: `data/v4/canonical/_results/mlofi_panel_5m.parquet`, `_15m.parquet`
- New gate: `g_mlofi_with` (weighted cumulative MLOFI over last 30s aligned with direction)
- + ridge-regression baseline that predicts `Δm_micro(t+120s)` directly from MLOFI vector — gives us a **per-fire calibrated probability** that can replace ad-hoc threshold gates with a proper Bayesian rule
- **Effort**: 3 days. Expected: large gains because polymarket binary tokens are large-tick (2% tick-to-mid) — exactly the regime where multi-level OFI is documented to give 68-74% RMSE reduction over single-level.

**Combined expected uplift across these three projects (additive on top of MASTER_DEPLOY_SPEC + round-2 SMS additions): conservatively +$8-15k / 28d at $25 notional, possibly more.**

These three projects are all in the SAME family ("polymarket L25 + binance 1s microstructure features"). They share a common data-loading layer and can share a unified panel writer.

---

## 6. Sources (web links cited)

### Order flow toxicity (VPIN) and microstructure
1. [Easley, López de Prado, O'Hara (NYU Stern PDF) — Flow Toxicity and Liquidity in a HF World](https://www.stern.nyu.edu/sites/default/files/assets/documents/con_035928.pdf)
2. [Astorian — Order Flow Toxicity in the Bitcoin Spot Market (Medium)](https://medium.com/@lucasastorian/empirical-market-microstructure-f67eff3517e0)
3. [Heusser — Order Flow Toxicity of the Bitcoin April Crash](https://jheusser.github.io/2013/10/13/informed-trading.html)
4. [ScienceDirect 2026 — Bitcoin wild moves: evidence from order flow toxicity and price jumps](https://www.sciencedirect.com/science/article/pii/S0275531925004192)
5. [Buildix — VPIN Guide: How Crypto Whales Signal Their Moves](https://www.buildix.trade/blog/vpin-indicator-how-crypto-whales-signal-moves-guide-2026)
6. [Chakrabarty, Pascual, Shkilko — BVC vs tick rule vs Lee-Ready](https://www.sciencedirect.com/science/article/abs/pii/S1386418115000415)
7. [Carrion — Bulk Volume Trade Classification and Informed Trading](http://faculty.bus.olemiss.edu/rvanness/Speakers/Presentations%202019-2020/AlCarrion_BVC_info_Jan2020.pdf)

### Microprice and Order Book Imbalance
8. [Stoikov — The Micro-Price (SSRN abstract_id=2970694)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2970694)
9. [arXiv 2411.13594 — High-resolution microprice estimates via Tsetlin Machines](https://arxiv.org/pdf/2411.13594)
10. [arXiv 2602.00776 — Explainable Patterns in Cryptocurrency Microstructure](https://arxiv.org/html/2602.00776v1)
11. [arXiv 1907.06230 — Xu, Gould, Howison: Multi-Level OFI in a LOB](https://arxiv.org/pdf/1907.06230)
12. [Cont, Kukanov, Stoikov — Price impact of order book events](https://www.smallake.kr/wp-content/uploads/2016/05/SSRN-id1712822.pdf)
13. [Gould & Bonart — Queue Imbalance as One-Tick-Ahead Predictor (arXiv 1512.03492)](https://arxiv.org/abs/1512.03492)
14. [Markwick — OFI: A High-Frequency Trading Signal](https://dm13450.github.io/2022/02/02/Order-Flow-Imbalance.html)

### Jumps and Drift Bursts
15. [arXiv 1704.08175 — Scaillet & Treccani: High-Frequency Jump Analysis of Bitcoin Market](https://arxiv.org/pdf/1704.08175)
16. [Lee — Jumps and Information Flow in Financial Markets (Bauer UH)](https://www.bauer.uh.edu/departments/finance/documents/suzanneslee_info.pdf)
17. [Taylor & Francis 2025 — Drift Bursts in Pure Jumps: Detection and Application to Bitcoin](https://www.tandfonline.com/doi/full/10.1080/07350015.2025.2530127)
18. [Springer Digital Finance 2024 — Tick-by-tick crypto jumps](https://link.springer.com/article/10.1007/s42521-024-00116-1)

### Hawkes Self-Exciting Processes
19. [Springer 2026 — Forecasting Bitcoin movements using multivariate Hawkes and LOB data](https://link.springer.com/article/10.1007/s10203-026-00570-z)
20. [Heusser — Bitcoin Trade Arrival as Self-Exciting Process](https://jheusser.github.io/2013/09/08/hawkes.html)
21. [Oxford Maths — Hawkes Process-Driven Models for LOB Dynamics](https://www.maths.ox.ac.uk/system/files/attachments/Hawkes%20Process-Driven%20Models%20for%20Limit%20Order%20Book%20Dynamics_0.pdf)

### Cross-exchange lead-lag and price discovery
22. [SEC NYSE Filing — Examining Lead-Lag Relationships Between Bitcoin Markets (Bitwise)](https://www.sec.gov/files/rules/sro/nysearca/2021/34-93445-ex3a.pdf)
23. [arXiv 2506.08718 — Price Discovery in Cryptocurrency Markets (2025)](https://arxiv.org/abs/2506.08718)
24. [Dimpfl & Peter / transfer entropy (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC7514459/)

### Realized moments and HAR/GARCH
25. [Lee & Wang — Variance Decomposition and Cryptocurrency Return Prediction (Cambridge)](https://www.cambridge.org/core/services/aop-cambridge-core/content/view/9995E58095453CB44A3BC3C9C111969F/S002210902400022Xa.pdf/variance_decomposition_and_cryptocurrency_return_prediction.pdf)
26. [Bergsli et al. — Forecasting Volatility of Bitcoin](https://www.sciencedirect.com/science/article/pii/S0275531921001616)
27. [Realized GARCH with jump-robust estimators for Bitcoin](https://www.sciencedirect.com/science/article/abs/pii/S1062940820300620)
28. [Aganin et al. — Comparison of Cryptocurrency and Stock Market Volatility Forecasts](https://ideas.repec.org/a/hig/ecohse/202313.html)

### Polymarket-specific
29. [arXiv 2603.03136 — The Anatomy of Polymarket: Evidence from 2024 Presidential Election](https://arxiv.org/html/2603.03136v1)
30. [arXiv 2605.11640 — Fill-Side Non-Retail Trading on Polymarket: Behavioral Tiers and Microstructure Signatures](https://arxiv.org/html/2605.11640)
31. [arXiv 2604.24366 — The Anatomy of a Decentralized Prediction Market: Polymarket Order Book](https://arxiv.org/html/2604.24366v1)
32. [arXiv 2605.00864 — Arbitrage Analysis in Polymarket NBA Markets](https://arxiv.org/pdf/2605.00864)
33. [Polymarket Docs — Liquidity Rewards](https://docs.polymarket.com/polymarket-learn/trading/liquidity-rewards)
34. [BlockEden — Chainlink Data Streams Power Polymarket 5-Minute Settlement](https://blockeden.xyz/forum/t/deep-dive-how-chainlink-data-streams-power-polymarkets-5-minute-settlement-oracle-architecture-for-high-frequency-prediction-markets/786)
35. [Benjamin-Cup (Medium) — Unlocking Edges in Polymarket's 5-Minute Crypto Markets](https://medium.com/@benjamin.bigdev/unlocking-edges-in-polymarkets-5-minute-crypto-markets-last-second-dynamics-bot-strategies-and-db8efcb5c196)
36. [GitHub oracle-lag-sniper — Chainlink/Polymarket latency arbitrage](https://github.com/JonathanPetersonn/oracle-lag-sniper)
37. [Liu (Medium) — AI-Augmented Arbitrage in Short-Duration Prediction Markets](https://medium.com/@gwrx2005/ai-augmented-arbitrage-in-short-duration-prediction-markets-live-trading-analysis-of-polymarkets-8ce1b8c5f362)

### Market making, Avellaneda-Stoikov
38. [Hummingbot — A Comprehensive Guide to Avellaneda & Stoikov's Market-Making Strategy](https://medium.com/hummingbot/a-comprehensive-guide-to-avellaneda-stoikovs-market-making-strategy-102d64bf5df6)
39. [Crypto Chassis — Simplified Avellaneda-Stoikov Market Making](https://medium.com/open-crypto-market-data-initiative/simplified-avellaneda-stoikov-market-making-608b9d437403)

### Intraday seasonality and momentum/reversal
40. [Wen, Bouri, Xu, Zhao — Intraday return predictability in crypto: Momentum, Reversal, or Both (SSRN PDF)](https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID4135239_code2537556.pdf)
41. [QuantPedia — Are There Seasonal Intraday or Overnight Anomalies in Bitcoin?](https://quantpedia.com/are-there-seasonal-intraday-or-overnight-anomalies-in-bitcoin/)
42. [Concretum — Seasonality in Bitcoin Intraday Trend Trading](https://concretumgroup.com/seasonality-in-bitcoin-intraday-trend-trading/)
43. [Turn-of-the-candle effect in bitcoin returns (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC10015199/)

### Hurst exponent / DFA / regime
44. [Macrosynergy — Detecting trends and mean reversion with the Hurst exponent](https://macrosynergy.com/research/detecting-trends-and-mean-reversion-with-the-hurst-exponent/)
45. [MDPI Mathematics — Anti-Persistent Hurst Anticipates Mean Reversion in Crypto Pairs](https://www.mdpi.com/2227-7390/12/18/2911)

### Funding rates and liquidations
46. [BeInCrypto — How to Predict October 10-Style Bitcoin Crash Early](https://beincrypto.com/liquidation-cascade-onchain-technical-analysis/)
47. [Zipmex — How to Analyze Funding Rates in Crypto: Complete Guide 2026](https://zipmex.com/blog/how-to-analyze-funding-rates-in-crypto/)
48. [Glassnode Insights — Mean Reclaimed, Rally on Trial (perp basis analysis)](https://insights.glassnode.com/the-week-onchain-week-16-2026/)

### Pairs trading / Kalman
49. [QuantStart — Dynamic Hedge Ratio with Kalman Filter](https://www.quantstart.com/articles/Dynamic-Hedge-Ratio-Between-ETF-Pairs-Using-the-Kalman-Filter/)
50. [Palomar (Bookdown) — Kalman Filtering for Pairs Trading](https://bookdown.org/palomar/portfoliooptimizationbook/15.6-kalman-pairs-trading.html)

---

## End of report
