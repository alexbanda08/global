"""CYCLOPS DECODE MASTER — clean re-parse + WR validation + trigger decode + edge.
Run: C:/Python314/python.exe strategy_lab/_cyclops_decode_master_2026_05_30.py
"""
import sys, io, re, json
import datetime as dt
sys.path.insert(0, r"C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import numpy as np, pandas as pd
from load import load_resolutions, load_klines, load_klines_asof, asof_strict

OUT = "CYCLOPS_DECODE_MASTER_2026_05_30"
print(OUT, "OUTPUT START")

CSV = r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cyclops_signals.csv"
df = pd.read_csv(CSV)
RED, GRN = "🟥", "🟩"

# ------- ET -> UTC slot_start (EDT = UTC-4 for May) -------
MONTHS = {"Jan":1,"Feb":2,"Mar":3,"Apr":4,"May":5,"Jun":6,"Jul":7,"Aug":8,"Sep":9,"Oct":10,"Nov":11,"Dec":12}
def parse_slot_et(raw, post_ts):
    # "May 13  3:00-3:05 PM ET"
    m = re.search(r"([A-Z][a-z]{2})\s+(\d{1,2})\s+(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})\s*(AM|PM)\s*ET", raw)
    if not m:
        return None
    mon, day, h1, mi1, h2, mi2, ampm = m.groups()
    h1, mi1 = int(h1), int(mi1); day = int(day); mon = MONTHS[mon]
    # AM/PM applies to start; handle window crossing noon edge minimally (windows are 5m)
    hh = h1 % 12
    if ampm == "PM":
        hh += 12
    yr = 2026
    et = dt.datetime(yr, mon, day, hh, mi1, tzinfo=dt.timezone(dt.timedelta(hours=-4)))  # EDT
    return int(et.astimezone(dt.timezone.utc).timestamp())

def parse_signal(raw):
    o = {}
    o["btc_price"] = _money(re.search(r"BTC\s+\$([\d,]+)", raw))
    o["strike"]    = _money(re.search(r"Beat\s+\$([\d,]+)", raw))
    pm = re.search(r"BTC\s*([▲▼≈])\s*PTB\s*([🟥🟩]*)", raw)
    if pm:
        o["ptb_arrow"] = pm.group(1)
        sq = pm.group(2)
        o["ptb_red"] = sq.count(RED); o["ptb_grn"] = sq.count(GRN)
        o["ptb_n"] = len(sq)
    em = re.search(r"Entry\s+(\d+)¢\s*\(([\d.]+)x\)", raw)
    if em:
        o["entry_cents"] = int(em.group(1)); o["mult"] = float(em.group(2))
    cm = re.search(r"Confidence\s*([●○]+)\s*(\w+)", raw)
    if cm:
        o["conf_dots"] = cm.group(1).count("●"); o["conf_label"] = cm.group(2)
    rm = re.search(r"Record\s+(\d+)W\s+(\d+)L\s*\((\d+)%\)", raw)
    if rm:
        o["rec_w"] = int(rm.group(1)); o["rec_l"] = int(rm.group(2)); o["rec_wr"] = int(rm.group(3))
    return o

def parse_winloss(raw):
    o = {}
    mm = re.search(r"\$([\d,]+)\s*→\s*\$([\d,]+)\s*\(([+-]?\d+)\)", raw)
    if mm:
        o["mv_from"] = _money_s(mm.group(1)); o["mv_to"] = _money_s(mm.group(2)); o["mv_delta"] = int(mm.group(3))
    em = re.search(r"Entry\s+(\d+)¢", raw)
    if em: o["entry_cents"] = int(em.group(1))
    rm = re.search(r"Record\s+(\d+)W\s+(\d+)L\s*\((\d+)%\)", raw)
    if rm:
        o["rec_w"] = int(rm.group(1)); o["rec_l"] = int(rm.group(2)); o["rec_wr"] = int(rm.group(3))
    return o

def _money(m):
    return float(m.group(1).replace(",", "")) if m else np.nan
def _money_s(s):
    return float(s.replace(",", ""))

rows = []
for _, r in df.iterrows():
    raw = str(r["raw"])
    t = r["type"]
    rec = {"msg_id": r["msg_id"], "post_ts": r["post_ts"], "type": t,
           "direction": r["direction"]}
    rec["slot_start_utc"] = parse_slot_et(raw, r["post_ts"])
    if t == "SIGNAL":
        rec.update(parse_signal(raw))
    elif t in ("WIN", "LOSS"):
        rec.update(parse_winloss(raw))
    rows.append(rec)
P = pd.DataFrame(rows)
P.to_parquet(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cyclops_clean_2026_05_30.parquet")

sig = P[P["type"]=="SIGNAL"].copy()
wl  = P[P["type"].isin(["WIN","LOSS"])].copy()
print("\n--- PARSE QC ---")
print("SIGNAL n:", len(sig), " entry_cents parsed:", sig["entry_cents"].notna().sum(),
      " mult parsed:", sig["mult"].notna().sum(), " strike parsed:", sig["strike"].notna().sum())
print("WIN/LOSS n:", len(wl), " mv_delta parsed:", wl["mv_delta"].notna().sum(),
      " entry parsed:", wl["entry_cents"].notna().sum())
print("slot_start_utc parsed SIGNAL:", sig["slot_start_utc"].notna().sum())

# ===== TASK 2: WR VALIDATION vs chainlink =====
res = load_resolutions(assets=["BTC"], timeframes=["5m"]).copy()
res["slot_s"] = res["slot_start_us"] // 1_000_000
res_map = res.set_index("slot_s")[["outcome","strike_price","settlement_price","slug"]].to_dict("index")

def chainlink_outcome(slot_s):
    d = res_map.get(int(slot_s)) if pd.notna(slot_s) else None
    return d

# advertised WR = max rec_wr seen / last record
last_rec = P.dropna(subset=["rec_wr"]).sort_values("post_ts").iloc[-1]
adv_w, adv_l, adv_wr = int(last_rec["rec_w"]), int(last_rec["rec_l"]), int(last_rec["rec_wr"])
# message-tally WR
nwin = (P["type"]=="WIN").sum(); nloss = (P["type"]=="LOSS").sum()
tally_wr = nwin/(nwin+nloss)*100

print("\n--- TASK2: WR REALITY ---")
print(f"ADVERTISED (last Record msg): {adv_w}W {adv_l}L = {adv_wr}%  (computed {adv_w/(adv_w+adv_l)*100:.1f}%)")
print(f"MESSAGE-TALLY WIN/LOSS:       {nwin}W {nloss}L = {tally_wr:.1f}%")

# our chainlink truth on SIGNAL calls
sig["cl"] = sig["slot_start_utc"].map(lambda s: chainlink_outcome(s))
sig["cl_outcome"] = sig["cl"].map(lambda d: d["outcome"] if d else None)
sig["cl_strike"]  = sig["cl"].map(lambda d: d["strike_price"] if d else None)
sig["cl_settle"]  = sig["cl"].map(lambda d: d["settlement_price"] if d else None)
matched = sig[sig["cl_outcome"].notna()].copy()
# bot dir UP wins if outcome Up
matched["bot_dir"] = matched["direction"].str.title()  # Up / Down
matched["cl_win"] = (matched["bot_dir"] == matched["cl_outcome"])
cl_wr = matched["cl_win"].mean()*100
print(f"OUR CHAINLINK TRUTH on SIGNALS: {matched['cl_win'].sum()}W "
      f"{(~matched['cl_win']).sum()}L = {cl_wr:.1f}%  (n={len(matched)} of {len(sig)} signals matched to chainlink)")
print("signals NOT matched to chainlink:", sig["cl_outcome"].isna().sum())

# Does bot's claimed WIN/LOSS match chainlink? join WIN/LOSS msgs to chainlink by slot
wl["cl"] = wl["slot_start_utc"].map(lambda s: chainlink_outcome(s))
wl["cl_outcome"] = wl["cl"].map(lambda d: d["outcome"] if d else None)
wl["bot_dir"] = wl["direction"].str.title()
wl["bot_claims_win"] = (wl["type"]=="WIN")
wlm = wl[wl["cl_outcome"].notna()].copy()
wlm["cl_win"] = (wlm["bot_dir"]==wlm["cl_outcome"])
agree = (wlm["bot_claims_win"]==wlm["cl_win"]).mean()*100
print(f"\nWIN/LOSS label vs chainlink agreement: {agree:.1f}% (n={len(wlm)})")
print("  bot WIN but chainlink LOSS:", ((wlm['bot_claims_win'])&(~wlm['cl_win'])).sum())
print("  bot LOSS but chainlink WIN:", ((~wlm['bot_claims_win'])&(wlm['cl_win'])).sum())

# Cherry-pick check: of all SIGNALs, how many got a WIN/LOSS followup?
sig_slots = set(sig["slot_start_utc"].dropna().astype(int))
wl_slots  = set(wl["slot_start_utc"].dropna().astype(int))
posted_followup = len(sig_slots & wl_slots)
print(f"\nSIGNAL slots with WIN/LOSS followup posted: {posted_followup}/{len(sig_slots)}"
      f"  (no followup = {len(sig_slots)-posted_followup})")

# ===== TASK 3: TRIGGER DECODE =====
print("\n--- TASK3: TRIGGER DECODE ---")
# load binance 1m klines for feature join
end_us, px = load_klines_asof("BTC", "binance-spot-ws", "1MIN")
km = load_klines("BTC", "binance-spot-ws", "1MIN")
kts = km["ts_s"].values.astype("int64"); kclose = km["price_close"].values.astype("float64")
def close_at(ts_s):  # close of 1m bar ending at-or-before ts_s
    return asof_strict(end_us, px, int(ts_s)*1_000_000)
def ret_n(slot_s, n):  # n-minute return ending at slot open
    a = close_at(slot_s - 60*n); b = close_at(slot_s)
    if np.isnan(a) or np.isnan(b) or a==0: return np.nan
    return (b-a)/a

feat = matched.dropna(subset=["slot_start_utc"]).copy()
feat["slot_s"] = feat["slot_start_utc"].astype(int)
# BTC-strike sign at signal time
feat["btc_minus_strike"] = feat["btc_price"] - feat["strike"]
feat["ret_1m"] = feat["slot_s"].map(lambda s: ret_n(s,1))
feat["ret_2m"] = feat["slot_s"].map(lambda s: ret_n(s,2))
feat["ret_3m"] = feat["slot_s"].map(lambda s: ret_n(s,3))
feat["ret_5m"] = feat["slot_s"].map(lambda s: ret_n(s,5))
feat["bot_up"] = (feat["bot_dir"]=="Up").astype(int)
# ptb signed: green positive, red negative
feat["ptb_signed"] = feat["ptb_grn"].fillna(0) - feat["ptb_red"].fillna(0)

print("\nbot direction vs sign(BTC - strike):")
feat["bms_sign"] = np.sign(feat["btc_minus_strike"])
ct = pd.crosstab(feat["bot_dir"], feat["bms_sign"])
print(ct)
# simple rule: bot UP iff btc>strike?
rule_pos = ((feat["bot_dir"]=="Up")==(feat["btc_minus_strike"]>0))
print("rule [UP iff BTC>strike] reproduces dir:", rule_pos.mean()*100, "% (n=",len(feat),")")
# rule: bot follows ptb_signed
rule_ptb = ((feat["bot_dir"]=="Up")==(feat["ptb_signed"]>0))
print("rule [UP iff PTB green>red] reproduces dir:", rule_ptb.mean()*100,"%")
# rule: ptb_signed sign else btc-strike when ptb 0
def combo(row):
    if row["ptb_signed"] > 0: return "Up"
    if row["ptb_signed"] < 0: return "Down"
    return "Up" if row["btc_minus_strike"] > 0 else "Down"
feat["combo_pred"] = feat.apply(combo, axis=1)
print("rule [PTB sign, tiebreak BTC-strike] reproduces dir:",
      (feat["combo_pred"]==feat["bot_dir"]).mean()*100,"%")
# momentum continuation: UP iff recent ret_1m>0
rule_mom1 = ((feat["bot_dir"]=="Up")==(feat["ret_1m"]>0))
print("rule [UP iff ret_1m>0] reproduces dir:", rule_mom1.dropna().mean()*100 if rule_mom1.notna().any() else "NA")

# PTB decode: does ptb_signed == count of consecutive same-dir 1m bars before slot?
def streak_1m(slot_s):
    # count consecutive 1m bars (ending at slot open going back) with same sign close-to-close
    closes = []
    for k in range(0, 7):
        closes.append(close_at(slot_s - 60*k))
    closes = closes[::-1]  # oldest..newest, newest = at slot open
    diffs = np.diff(closes)
    if len(diffs)==0 or np.isnan(diffs[-1]): return 0
    last = np.sign(diffs[-1]); cnt = 0
    for d in diffs[::-1]:
        if np.isnan(d): break
        if np.sign(d)==last and last!=0: cnt+=1
        else: break
    return int(last*cnt)
feat["streak1m"] = feat["slot_s"].map(streak_1m)
print("\nPTB vs 1m-bar consecutive streak:")
print("  corr(ptb_signed, streak1m):", feat[["ptb_signed","streak1m"]].corr().iloc[0,1])
print("  ptb_signed == streak1m exact:", (feat["ptb_signed"]==feat["streak1m"]).mean()*100,"%")
print("  |ptb_signed| vs |streak1m| match:", (feat["ptb_signed"].abs()==feat["streak1m"].abs()).mean()*100,"%")
print("  sign(ptb_signed)==sign(streak1m):", (np.sign(feat["ptb_signed"])==np.sign(feat["streak1m"])).mean()*100,"%")

# confidence/mult mapping
print("\nmult vs entry_cents (should be ~ 1/entry):")
print("  corr(mult, 1/entry):", np.corrcoef(feat["mult"].dropna(), (100/feat["entry_cents"]).dropna())[0,1] if feat["entry_cents"].notna().sum()>2 else "NA")
print("\nconf_label vs |btc-strike|:")
print(feat.groupby("conf_label")["btc_minus_strike"].apply(lambda s: s.abs().mean()))
print("\nconf_label vs |ptb_signed|:")
print(feat.groupby("conf_label")["ptb_signed"].apply(lambda s: s.abs().mean()))
print("\nconf_label vs |ret_2m|:")
print(feat.groupby("conf_label")["ret_2m"].apply(lambda s: s.abs().mean()))

# WATCH vs FIRE gate: compare watch slots' btc vs strike / market neutral
wat = P[P["type"]=="WATCHING"].copy()
print("\nWATCHING n:", len(wat), " (market shown Neutral). FIRE rate among posted slots:",
      f"{len(sig)}/{len(sig)+len(wat)} = {len(sig)/(len(sig)+len(wat))*100:.1f}%")

# ===== TASK 4: EDGE AFTER FEES =====
print("\n--- TASK4: EDGE ---")
# Polymarket production fee = 2% on profit only (per CLAUDE.md). Also show 0.07 curve.
def ev_per_trade(entry_c, wr, fee_model="legacy"):
    p = entry_c/100.0  # entry price (cost per share to win $1)
    # win: gross profit = (1-p); loss: -p
    if fee_model=="legacy":
        win_net = (1-p)*0.98  # 2% on profit
        loss_net = -p
    elif fee_model=="curve007":
        fee = 0.07*p*(1-p)  # per-share both legs
        win_net = (1-p) - fee
        loss_net = -p - fee
    return wr*win_net + (1-wr)*loss_net
med_entry = sig["entry_cents"].median()
wr_real = tally_wr/100
wr_cl   = cl_wr/100
for label, wr in [("tally63", wr_real), ("chainlink_truth", wr_cl), ("adv84", adv_wr/100)]:
    ev_l = ev_per_trade(med_entry, wr, "legacy")
    ev_c = ev_per_trade(med_entry, wr, "curve007")
    print(f"  WR={wr*100:.1f}% entry={med_entry:.0f}c  EV/$1 legacy={ev_l:+.4f}  curve007={ev_c:+.4f}")
# also EV using ACTUAL per-signal entry & chainlink outcome
m2 = matched.dropna(subset=["entry_cents"]).copy()
m2["p"] = m2["entry_cents"]/100.0
m2["pnl_legacy"] = np.where(m2["cl_win"], (1-m2["p"])*0.98, -m2["p"])
m2["pnl_curve"]  = np.where(m2["cl_win"], (1-m2["p"]) - 0.07*m2["p"]*(1-m2["p"]),
                                          -m2["p"] - 0.07*m2["p"]*(1-m2["p"]))
print(f"\n  ACTUAL per-signal EV (chainlink outcome, real entry prices, n={len(m2)}):")
print(f"    legacy 2%-profit: {m2['pnl_legacy'].mean():+.4f}/$1  total={m2['pnl_legacy'].sum():+.3f}")
print(f"    0.07 curve:       {m2['pnl_curve'].mean():+.4f}/$1   total={m2['pnl_curve'].sum():+.3f}")
print(f"    per $25 stake legacy: {m2['pnl_legacy'].mean()*25:+.3f}")

# save feature table for report
feat.to_parquet(r"C:\Users\alexandre bandarra\Desktop\global\strategy_lab\wallet_hunt\cyclops_features_2026_05_30.parquet")
print("\n", OUT, "OUTPUT END")
