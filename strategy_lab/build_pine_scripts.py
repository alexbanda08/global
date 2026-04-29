"""
Generate Pine v5 scripts for each coin's V23 winning strategy.
Pulls config from v23_results_with_oos.pkl, writes to pine/.
"""
from __future__ import annotations
import pickle
from pathlib import Path

LAB = Path(__file__).resolve().parent
RES = LAB / "results" / "v23"
PINE = LAB / "pine"
PINE.mkdir(exist_ok=True)


# ---------- Templates ----------

BB_TEMPLATE = '''//@version=5
// ============================================================================
//  {sym_short}  —  V23 Bollinger-Band Breakout Long+Short  ({tf}, perps, Hyperliquid-style)
// ============================================================================
//  Python backtest ({range}, $10,000 start):
//    FULL   n={full_n}  CAGR (net) {full_cagr:+.1f}%   Sharpe {full_sh:+.2f}   DD {full_dd:+.1f}%
//      IS  n={is_n}   CAGR {is_cagr:+.1f}%   Sharpe {is_sh:+.2f}
//      OOS n={oos_n}  CAGR {oos_cagr:+.1f}%   Sharpe {oos_sh:+.2f}   {verdict}
//  Caveats: grid-selected config. Paper-trade 4 weeks before real capital.
// ============================================================================

strategy("{sym_short}  V23 BB-Break L/S",
     overlay             = true,
     initial_capital     = 10000,
     currency            = currency.USD,
     default_qty_type    = strategy.percent_of_equity,
     default_qty_value   = 100,
     commission_type     = strategy.commission.percent,
     commission_value    = 0.045,
     slippage            = 3,
     pyramiding          = 0,
     process_orders_on_close = false,
     close_entries_rule  = "ANY",
     margin_long         = 33,
     margin_short        = 33)

grpSig  = "Signal (Bollinger breakout)"
bbN     = input.int({bb_n},  "BB length ({tf})",          minval = 5,  group = grpSig)
bbK     = input.float({bb_k}, "BB std-dev multiplier",    step = 0.1,  group = grpSig)
regLen  = input.int({bb_rg}, "Regime SMA length ({tf})",  minval = 50, group = grpSig)

grpExit = "Exits (ATR)"
atrLen  = input.int(14,    "ATR length", minval = 2, group = grpExit)
tpAtr   = input.float({tp}, "TP x ATR",  step = 0.5, group = grpExit)
slAtr   = input.float({sl}, "SL x ATR",  step = 0.1, group = grpExit)
trlAtr  = input.float({tr}, "Trail x ATR", step = 0.5, group = grpExit)
maxHold = input.int({mh},   "Max hold (bars @ {tf})", minval = 4, group = grpExit)

grpRisk = "Sizing"
riskPct = input.float({risk_pct}, "Risk per trade (% eq.)", step = 0.5, group = grpRisk)
levCap  = input.float({lev},      "Max leverage",            step = 0.5, group = grpRisk)

grpSide = "Sides"
useLong  = input.bool(true, "Longs",  group = grpSide)
useShort = input.bool(true, "Shorts", group = grpSide)

// ---- Bollinger band breakout ----
basis = ta.sma(close, bbN)
dev   = ta.stdev(close, bbN)
upper = basis + bbK * dev
lower = basis - bbK * dev

regimeSma = ta.sma(close, regLen)
regimeUp  = close > regimeSma
regimeDn  = close < regimeSma

crossUp = close > upper and close[1] <= upper[1]
crossDn = close < lower and close[1] >= lower[1]

longSig  = useLong  and crossUp and regimeUp
shortSig = useShort and crossDn and regimeDn

atrVal = ta.atr(atrLen)
stopDist = slAtr * atrVal
riskDollars = strategy.equity * (riskPct / 100.0)
qtySized = stopDist > 0 ? math.min(riskDollars / stopDist, strategy.equity * levCap / close) : 0

if longSig and strategy.position_size == 0
    strategy.entry("L", strategy.long, qty = qtySized,
                   alert_message = '{{"action":"buy","ticker":"{{{{ticker}}}}","qty":"{{{{strategy.order.contracts}}}}","price":"{{{{close}}}}"}}')

if shortSig and strategy.position_size == 0
    strategy.entry("S", strategy.short, qty = qtySized,
                   alert_message = '{{"action":"sell","ticker":"{{{{ticker}}}}","qty":"{{{{strategy.order.contracts}}}}","price":"{{{{close}}}}"}}')

var float trailStop = na
var int   barsIn    = 0

if strategy.position_size > 0
    barsIn := barsIn + 1
    tp    = strategy.position_avg_price + tpAtr * atrVal
    hsl   = strategy.position_avg_price - slAtr * atrVal
    trail = high - trlAtr * atrVal
    trailStop := na(trailStop) ? hsl : math.max(trailStop, trail)
    trailStop := math.max(trailStop, hsl)
    strategy.exit("X-L", "L", limit = tp, stop = trailStop)
    if barsIn >= maxHold
        strategy.close("L", comment = "maxHold")
else if strategy.position_size < 0
    barsIn := barsIn + 1
    tp    = strategy.position_avg_price - tpAtr * atrVal
    hsl   = strategy.position_avg_price + slAtr * atrVal
    trail = low + trlAtr * atrVal
    trailStop := na(trailStop) ? hsl : math.min(trailStop, trail)
    trailStop := math.min(trailStop, hsl)
    strategy.exit("X-S", "S", limit = tp, stop = trailStop)
    if barsIn >= maxHold
        strategy.close("S", comment = "maxHold")
else
    trailStop := na
    barsIn := 0

plot(basis, "BB mid",    color = color.new(color.yellow, 0))
plot(upper, "BB upper",  color = color.new(color.lime,   40))
plot(lower, "BB lower",  color = color.new(color.red,    40))
plot(regimeSma, "Regime SMA", color = color.new(color.aqua, 60))
plotshape(longSig,  title = "Long",  style = shape.triangleup,   location = location.belowbar, color = color.lime, size = size.tiny)
plotshape(shortSig, title = "Short", style = shape.triangledown, location = location.abovebar, color = color.red,  size = size.tiny)
'''


RK_TEMPLATE = '''//@version=5
// ============================================================================
//  {sym_short}  —  V23 Range-Kalman Long+Short  ({tf}, perps, Hyperliquid-style)
// ============================================================================
//  Python backtest ({range}, $10,000 start):
//    FULL   n={full_n}  CAGR (net) {full_cagr:+.1f}%   Sharpe {full_sh:+.2f}   DD {full_dd:+.1f}%
//      IS  n={is_n}   CAGR {is_cagr:+.1f}%   Sharpe {is_sh:+.2f}
//      OOS n={oos_n}  CAGR {oos_cagr:+.1f}%   Sharpe {oos_sh:+.2f}   {verdict}
// ============================================================================

strategy("{sym_short}  V23 RangeKalman L/S",
     overlay = true, initial_capital = 10000, currency = currency.USD,
     default_qty_type = strategy.percent_of_equity, default_qty_value = 100,
     commission_type = strategy.commission.percent, commission_value = 0.045,
     slippage = 3, pyramiding = 0, process_orders_on_close = false,
     close_entries_rule = "ANY", margin_long = 33, margin_short = 33)

grpSig  = "Signal (Range Kalman)"
alphaK  = input.float({alpha}, "Kalman alpha",             step = 0.01, group = grpSig)
rngLen  = input.int({rng_len}, "Range avg length ({tf})",  minval = 20, group = grpSig)
rngMult = input.float({rng_mult}, "Range multiplier",      step = 0.1,  group = grpSig)
regLen  = input.int({regime_len}, "Regime SMA length ({tf})", minval = 50, group = grpSig)

grpExit = "Exits (ATR)"
atrLen  = input.int(14, "ATR length", minval = 2, group = grpExit)
tpAtr   = input.float({tp}, "TP x ATR", step = 0.5, group = grpExit)
slAtr   = input.float({sl}, "SL x ATR", step = 0.1, group = grpExit)
trlAtr  = input.float({tr}, "Trail x ATR", step = 0.5, group = grpExit)
maxHold = input.int({mh}, "Max hold (bars @ {tf})", minval = 4, group = grpExit)

grpRisk = "Sizing"
riskPct = input.float({risk_pct}, "Risk per trade (% eq.)", step = 0.5, group = grpRisk)
levCap  = input.float({lev},      "Max leverage",            step = 0.5, group = grpRisk)

var float kal = na
kal := na(kal) ? close : kal[1] + alphaK * (close - kal[1])
devAbs = math.abs(close - kal)
rngAvg = ta.sma(devAbs, rngLen)
upper  = kal + rngAvg * rngMult
lower  = kal - rngAvg * rngMult

regimeSma = ta.sma(close, regLen)
regimeUp  = close > regimeSma
regimeDn  = close < regimeSma

crossUp = close > upper and close[1] <= upper[1]
crossDn = close < lower and close[1] >= lower[1]

longSig  = crossUp and regimeUp
shortSig = crossDn and regimeDn

atrVal = ta.atr(atrLen)
riskDollars = strategy.equity * (riskPct / 100.0)
qty = slAtr * atrVal > 0 ? math.min(riskDollars / (slAtr*atrVal), strategy.equity*levCap/close) : 0

if longSig and strategy.position_size == 0
    strategy.entry("L", strategy.long, qty = qty)
if shortSig and strategy.position_size == 0
    strategy.entry("S", strategy.short, qty = qty)

var float trailStop = na
var int   barsIn    = 0

if strategy.position_size > 0
    barsIn := barsIn + 1
    tp = strategy.position_avg_price + tpAtr*atrVal
    hsl = strategy.position_avg_price - slAtr*atrVal
    trail = high - trlAtr*atrVal
    trailStop := na(trailStop) ? hsl : math.max(trailStop, trail)
    trailStop := math.max(trailStop, hsl)
    strategy.exit("X-L", "L", limit = tp, stop = trailStop)
    if barsIn >= maxHold
        strategy.close("L", comment = "maxHold")
else if strategy.position_size < 0
    barsIn := barsIn + 1
    tp = strategy.position_avg_price - tpAtr*atrVal
    hsl = strategy.position_avg_price + slAtr*atrVal
    trail = low + trlAtr*atrVal
    trailStop := na(trailStop) ? hsl : math.min(trailStop, trail)
    trailStop := math.min(trailStop, hsl)
    strategy.exit("X-S", "S", limit = tp, stop = trailStop)
    if barsIn >= maxHold
        strategy.close("S", comment = "maxHold")
else
    trailStop := na
    barsIn := 0

plot(kal, "Kalman", color = color.new(color.yellow, 0))
plot(upper, "Upper", color = color.new(color.lime, 40))
plot(lower, "Lower", color = color.new(color.red, 40))
plot(regimeSma, "Regime", color = color.new(color.aqua, 60))
'''


KEL_TEMPLATE = '''//@version=5
// ============================================================================
//  {sym_short}  —  V23 Keltner+ADX Long+Short  ({tf}, perps, Hyperliquid-style)
// ============================================================================
//  Python backtest ({range}, $10,000 start):
//    FULL   n={full_n}  CAGR (net) {full_cagr:+.1f}%   Sharpe {full_sh:+.2f}   DD {full_dd:+.1f}%
//      IS  n={is_n}   CAGR {is_cagr:+.1f}%   Sharpe {is_sh:+.2f}
//      OOS n={oos_n}  CAGR {oos_cagr:+.1f}%   Sharpe {oos_sh:+.2f}   {verdict}
// ============================================================================

strategy("{sym_short}  V23 Keltner+ADX L/S",
     overlay = true, initial_capital = 10000, currency = currency.USD,
     default_qty_type = strategy.percent_of_equity, default_qty_value = 100,
     commission_type = strategy.commission.percent, commission_value = 0.045,
     slippage = 3, pyramiding = 0, process_orders_on_close = false,
     close_entries_rule = "ANY", margin_long = 33, margin_short = 33)

grpSig  = "Signal (Keltner + ADX)"
kN      = input.int({k_n},    "Keltner length",         minval = 5,  group = grpSig)
kMult   = input.float({k_mult},"Keltner multiplier",    step = 0.1,  group = grpSig)
adxMin  = input.float({adx_min},"ADX threshold",         step = 1.0,  group = grpSig)
regLen  = input.int({regime_len},"Regime SMA length",   minval = 50, group = grpSig)

grpExit = "Exits (ATR)"
atrLen  = input.int(14, "ATR length", minval = 2, group = grpExit)
tpAtr   = input.float({tp}, "TP x ATR", step = 0.5, group = grpExit)
slAtr   = input.float({sl}, "SL x ATR", step = 0.1, group = grpExit)
trlAtr  = input.float({tr}, "Trail x ATR", step = 0.5, group = grpExit)
maxHold = input.int({mh}, "Max hold (bars @ {tf})", minval = 4, group = grpExit)

grpRisk = "Sizing"
riskPct = input.float({risk_pct}, "Risk % eq.", step = 0.5, group = grpRisk)
levCap  = input.float({lev},      "Max lev",    step = 0.5, group = grpRisk)

midEma = ta.ema(close, kN)
atrK   = ta.atr(kN)
kelUp  = midEma + kMult * atrK
kelLo  = midEma - kMult * atrK

[dip, dim, adx14] = ta.dmi(14, 14)

regimeSma = ta.sma(close, regLen)
regimeUp  = close > regimeSma
regimeDn  = close < regimeSma

crossUp = close > kelUp and close[1] <= kelUp[1] and adx14 > adxMin and regimeUp
crossDn = close < kelLo and close[1] >= kelLo[1] and adx14 > adxMin and regimeDn

atrVal = ta.atr(atrLen)
riskDollars = strategy.equity * (riskPct / 100.0)
qty = slAtr * atrVal > 0 ? math.min(riskDollars / (slAtr*atrVal), strategy.equity*levCap/close) : 0

if crossUp and strategy.position_size == 0
    strategy.entry("L", strategy.long, qty = qty)
if crossDn and strategy.position_size == 0
    strategy.entry("S", strategy.short, qty = qty)

var float trailStop = na
var int   barsIn    = 0

if strategy.position_size > 0
    barsIn := barsIn + 1
    tp = strategy.position_avg_price + tpAtr*atrVal
    hsl = strategy.position_avg_price - slAtr*atrVal
    trail = high - trlAtr*atrVal
    trailStop := na(trailStop) ? hsl : math.max(trailStop, trail)
    trailStop := math.max(trailStop, hsl)
    strategy.exit("X-L", "L", limit = tp, stop = trailStop)
    if barsIn >= maxHold
        strategy.close("L", comment = "maxHold")
else if strategy.position_size < 0
    barsIn := barsIn + 1
    tp = strategy.position_avg_price - tpAtr*atrVal
    hsl = strategy.position_avg_price + slAtr*atrVal
    trail = low + trlAtr*atrVal
    trailStop := na(trailStop) ? hsl : math.min(trailStop, trail)
    trailStop := math.min(trailStop, hsl)
    strategy.exit("X-S", "S", limit = tp, stop = trailStop)
    if barsIn >= maxHold
        strategy.close("S", comment = "maxHold")
else
    trailStop := na
    barsIn := 0

plot(midEma, "Keltner mid", color = color.new(color.yellow, 0))
plot(kelUp,  "Upper", color = color.new(color.lime, 40))
plot(kelLo,  "Lower", color = color.new(color.red, 40))
plot(regimeSma, "Regime", color = color.new(color.aqua, 60))
'''


def main():
    with open(RES / "v23_results_with_oos.pkl", "rb") as f:
        data = pickle.load(f)

    for sym, d in data.items():
        fam = d["family"]; p = d["params"]; e = d["exits"]
        m_full = d["metrics"]; r_is = d["is"]; r_oos = d["oos"]
        sym_short = sym.replace("USDT", "")
        # Get range from IS + OOS
        first_is = pd.Timestamp(d.get("eq_is_idx", [0])[0]) if d.get("eq_is_idx") else None
        last_oos = pd.Timestamp(d["eq_oos_idx"][-1]) if d.get("eq_oos_idx") else None
        rng_str = (f"{first_is.strftime('%Y-%m') if first_is else '2024-08'} -> "
                   f"{last_oos.strftime('%Y-%m') if last_oos else '2026-04'}")
        ctx = dict(
            sym_short=sym_short, tf=d["tf"], range=rng_str,
            full_n=m_full["n"], full_cagr=m_full["cagr_net"]*100,
            full_sh=m_full["sharpe"], full_dd=m_full["dd"]*100,
            is_n=r_is["n"], is_cagr=r_is["cagr_net"]*100, is_sh=r_is["sharpe"],
            oos_n=r_oos["n"], oos_cagr=r_oos["cagr_net"]*100, oos_sh=r_oos["sharpe"],
            verdict=d["verdict"],
            tp=e["tp"], sl=e["sl"], tr=e["trail"], mh=e["mh"],
            risk_pct=d["risk"]*100, lev=d["lev"],
        )
        if fam == "BBBreak_LS":
            ctx.update(bb_n=p["n"], bb_k=p["k"], bb_rg=p["regime_len"])
            out = BB_TEMPLATE.format(**ctx)
        elif fam == "RangeKalman_LS":
            ctx.update(alpha=p["alpha"], rng_len=p["rng_len"],
                        rng_mult=p["rng_mult"], regime_len=p["regime_len"])
            out = RK_TEMPLATE.format(**ctx)
        elif fam == "KeltnerADX_LS":
            ctx.update(k_n=p["k_n"], k_mult=p["k_mult"],
                        adx_min=p["adx_min"], regime_len=p["regime_len"])
            out = KEL_TEMPLATE.format(**ctx)
        else:
            print(f"  ? unknown family for {sym}: {fam}")
            continue
        path = PINE / f"{sym_short}_V23_{fam.replace('_LS','LS')}.pine"
        path.write_text(out)
        print(f"  ✓ {path.name}")


if __name__ == "__main__":
    import pandas as pd
    main()
