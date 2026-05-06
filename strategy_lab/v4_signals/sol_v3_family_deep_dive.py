"""sol_v3_family_deep_dive.py — analyze V3 family (V3, V3.1, V3.2, V3.3, V4) per asset.

Now that SOL V3 fix + V3.3 multi-horizon A/B sleeve are deployed, this script:
1. Computes per-asset × per-variant fire/hit/PnL stats
2. Tests the V3.3 vs V3.2 multi-horizon A/B (decision rule from SOL_V3_FIX_SPEC)
3. Maps subset relationships (V4 ⊆ V3.2 ⊆ V3 etc) — sanity check on actual data
4. Per-direction (UP/DOWN) breakdown for each variant
5. Per-hour-of-day breakdown for SOL specifically (to check if hour blocklist still helps)
"""
from __future__ import annotations
import csv, math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

DATA = Path(__file__).parent.parent.parent / "data" / "v4" / "shadow_trades_2026_05_05" / "v3_family_full.csv"
RNG = np.random.default_rng(42)


def load() -> list[dict]:
    rows = []
    with open(DATA) as f:
        for r in csv.DictReader(f):
            try:
                at = datetime.fromisoformat(r["at"].replace(" ", "T"))
                r["at_unix"] = int(at.timestamp())
                r["at_utc"] = at.astimezone(timezone.utc)
                r["pnl_paper"] = float(r.get("pnl_usd") or 0)
                r["pnl_live"] = r["pnl_paper"] / 25.0  # rescale to $1 live
                r["won_b"] = r.get("won") in ("t", "true", "True", "1")
                r["sym"] = (r.get("symbol") or "").upper()
                r["sig"] = (r.get("signal") or "").upper()
                r["entry_f"] = float(r.get("entry_price") or 0) or float("nan")
            except (ValueError, TypeError, KeyError):
                continue
            rows.append(r)
    return rows


def variant_from_sleeve(sleeve_id: str) -> str:
    for v in ("v3_3", "v3_1", "v3_2", "v4", "v3"):
        if sleeve_id.endswith(f"_{v}"):
            return v
    return "?"


def stats(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0}
    pnls = np.asarray([t["pnl_live"] for t in trades])
    wins = sum(1 for t in trades if t["won_b"])
    n = len(trades)
    hr = wins / n
    # bootstrap 95% CI on hit rate
    won_arr = np.asarray([1 if t["won_b"] else 0 for t in trades])
    boot_hr = RNG.choice(won_arr, size=(2000, n), replace=True).mean(axis=1)
    return {
        "n": n,
        "hit_rate": hr,
        "ci_lo": float(np.quantile(boot_hr, 0.025)),
        "ci_hi": float(np.quantile(boot_hr, 0.975)),
        "total_pnl_live": float(pnls.sum()),
        "avg_pnl_live": float(pnls.mean()),
        "max_dd_live": float(np.minimum.accumulate(np.concatenate([[0], np.cumsum(pnls)]))[-1]) if len(pnls) else 0.0,
        "first_at": min(t["at_unix"] for t in trades),
        "last_at": max(t["at_unix"] for t in trades),
        "n_up": sum(1 for t in trades if t["sig"] == "UP"),
        "n_down": sum(1 for t in trades if t["sig"] == "DOWN"),
        "wins_up": sum(1 for t in trades if t["sig"] == "UP" and t["won_b"]),
        "wins_down": sum(1 for t in trades if t["sig"] == "DOWN" and t["won_b"]),
    }


def main() -> int:
    rows = load()
    print(f"V3-family events loaded: {len(rows)}")

    # 1. Per-asset × per-variant matrix
    print("\n" + "="*100)
    print("PER-ASSET × PER-VARIANT MATRIX (live-rescaled $1 stake)")
    print("="*100)
    print(f"{'asset':5s}  {'variant':8s}  {'n':>4s}  {'hit%':>5s}  {'CI_hit':>13s}  {'pnl$':>7s}  {'avg/t':>6s}  {'UP':>4s}  {'DN':>4s}  {'UP_hit':>7s}  {'DN_hit':>7s}")
    by_av = defaultdict(list)
    for r in rows:
        by_av[(r["sym"], variant_from_sleeve(r["sleeve_id"]))].append(r)

    for asset in ("BTC", "ETH", "SOL"):
        for variant in ("v3", "v3_1", "v3_2", "v3_3", "v4"):
            trades = by_av.get((asset, variant), [])
            if not trades:
                print(f"{asset:5s}  {variant:8s}  {'0':>4s}  {'-':>5s}  {'-':>13s}  {'-':>7s}  {'-':>6s}")
                continue
            s = stats(trades)
            up_hit = (s["wins_up"] / s["n_up"] * 100) if s["n_up"] else 0
            dn_hit = (s["wins_down"] / s["n_down"] * 100) if s["n_down"] else 0
            ci = f"[{s['ci_lo']*100:.0f},{s['ci_hi']*100:.0f}]"
            print(f"{asset:5s}  {variant:8s}  {s['n']:>4d}  {s['hit_rate']*100:>4.1f}%  {ci:>13s}  "
                  f"{s['total_pnl_live']:>+6.2f}  {s['avg_pnl_live']:>+5.3f}  "
                  f"{s['n_up']:>4d}  {s['n_down']:>4d}  "
                  f"{up_hit:>5.1f}%  {dn_hit:>5.1f}%")
        print()

    # 2. V3.3 vs V3.2 A/B test — multi-horizon decision
    print("="*100)
    print("V3.3 vs V3.2 A/B TEST — Multi-horizon decision (per SOL_V3_FIX_SPEC § Decision protocol)")
    print("="*100)
    print(f"{'asset':5s}  {'variant':8s}  {'n':>4s}  {'hit%':>5s}  {'CI_hit':>13s}  {'pnl$':>7s}  {'note'}")
    for asset in ("BTC", "ETH", "SOL"):
        for variant in ("v3_2", "v3_3"):
            trades = by_av.get((asset, variant), [])
            if not trades:
                print(f"{asset:5s}  {variant:8s}  {'0':>4s}  -")
                continue
            s = stats(trades)
            ci = f"[{s['ci_lo']*100:.0f},{s['ci_hi']*100:.0f}]"
            tag = "MH active for SOL" if (asset == "SOL" and variant == "v3_3") else "no MH" if variant == "v3_2" else "(BTC/ETH MH N/A)"
            print(f"{asset:5s}  {variant:8s}  {s['n']:>4d}  {s['hit_rate']*100:>4.1f}%  {ci:>13s}  "
                  f"{s['total_pnl_live']:>+6.2f}  {tag}")
        # Direct comparison only meaningful for SOL where MH actually differs
        if asset == "SOL":
            v32 = by_av.get(("SOL", "v3_2"), [])
            v33 = by_av.get(("SOL", "v3_3"), [])
            if v32 and v33:
                s32 = stats(v32); s33 = stats(v33)
                delta_hit = (s33["hit_rate"] - s32["hit_rate"]) * 100
                print(f"  → SOL V3.3 hit% − V3.2 hit% = {delta_hit:+.1f}pp  "
                      f"(decision rule: ≥3pp → adopt MH, ≤-3pp → reject MH, else neutral)")
                if abs(delta_hit) < 3:
                    print(f"     → NEUTRAL — keep status quo (need n≥30 per spec, currently n={s32['n']} vs n={s33['n']})")
                elif delta_hit >= 3:
                    print(f"     → ADOPT MH — but n={s33['n']} too small (need n≥30)")
                else:
                    print(f"     → REJECT MH — but n={s33['n']} too small (need n≥30)")
        print()

    # 3. Subset hierarchy sanity check (V4 should be subset of V3.2 and V3.1)
    print("="*100)
    print("SUBSET HIERARCHY SANITY CHECK (V4 ⊆ V3.2 ⊆ V3, V4 ⊆ V3.1 ⊆ V3)")
    print("="*100)
    print("Per SOL_V3_FIX_SPEC: V4 only fires when ALL of V3.1 quantile + V3.2 gates pass.")
    print("So V4's fired markets should be a proper subset of V3.2's and V3.1's.")
    print()
    for asset in ("BTC", "ETH", "SOL"):
        # Build (timestamp, signal) keys per variant
        keys = {}
        for v in ("v3", "v3_1", "v3_2", "v3_3", "v4"):
            keys[v] = set(
                (t["at_unix"] // 300, t["sig"])  # round to 5min
                for t in by_av.get((asset, v), [])
            )
        if not keys["v4"]:
            continue
        # check V4 ⊆ V3.2
        ovr_v32 = len(keys["v4"] & keys["v3_2"]) / max(len(keys["v4"]), 1)
        ovr_v31 = len(keys["v4"] & keys["v3_1"]) / max(len(keys["v4"]), 1)
        ovr_v3 = len(keys["v4"] & keys["v3"]) / max(len(keys["v4"]), 1)
        print(f"{asset}:  V4 fires:  V4∩V3.2 = {ovr_v32*100:.0f}%  V4∩V3.1 = {ovr_v31*100:.0f}%  V4∩V3 = {ovr_v3*100:.0f}%")
        # SOL V3.3 should overlap with V3.2 (same V3.2 logic) but reduce to MH-passing subset
        if asset == "SOL" and keys["v3_3"]:
            ovr_v33_v32 = len(keys["v3_3"] & keys["v3_2"]) / max(len(keys["v3_3"]), 1)
            print(f"     V3.3 ∩ V3.2 = {ovr_v33_v32*100:.0f}%  (V3.3 should be a subset of V3.2 if MH only restricts further)")

    # 4. Per-hour breakdown for V3 BTC (the strongest sleeve)
    print("\n" + "="*100)
    print("PER-HOUR HEAT MAP — BTC V3 (n=41) (UTC)")
    print("="*100)
    btc_v3 = by_av.get(("BTC", "v3"), [])
    by_hour = defaultdict(list)
    for t in btc_v3:
        by_hour[t["at_utc"].hour].append(t)
    print(f"{'hour':>4s}  {'n':>3s}  {'hit%':>5s}  {'pnl$':>7s}  {'in_v3.2_blocklist?':18s}")
    for h in range(24):
        ts = by_hour.get(h, [])
        if not ts:
            continue
        s = stats(ts)
        block = h in {1, 16, 22}
        print(f"  {h:>2d}  {s['n']:>3d}  {s['hit_rate']*100:>4.1f}%  {s['total_pnl_live']:>+6.2f}  "
              f"{'BLOCKED' if block else ''}")

    # 5. Direction asymmetry check on full V3 family (DOWN >> UP claim verification)
    print("\n" + "="*100)
    print("DIRECTION ASYMMETRY (DOWN ≫ UP claim) — per asset, all V3-family aggregated")
    print("="*100)
    print(f"{'asset':5s}  {'UP_n':>5s}  {'UP_hit%':>8s}  {'UP_pnl':>7s}  {'DN_n':>5s}  {'DN_hit%':>8s}  {'DN_pnl':>7s}  {'asymm':>10s}")
    for asset in ("BTC", "ETH", "SOL"):
        all_trades = []
        for v in ("v3", "v3_1", "v3_2", "v3_3", "v4"):
            all_trades.extend(by_av.get((asset, v), []))
        ups = [t for t in all_trades if t["sig"] == "UP"]
        dns = [t for t in all_trades if t["sig"] == "DOWN"]
        up_hit = sum(1 for t in ups if t["won_b"]) / len(ups) * 100 if ups else 0
        dn_hit = sum(1 for t in dns if t["won_b"]) / len(dns) * 100 if dns else 0
        up_pnl = sum(t["pnl_live"] for t in ups)
        dn_pnl = sum(t["pnl_live"] for t in dns)
        delta = dn_hit - up_hit
        tag = ("DOWN » UP" if delta > 10 else
               "DOWN > UP" if delta > 3 else
               "UP > DOWN" if delta < -3 else
               "symmetric")
        print(f"{asset:5s}  {len(ups):>5d}  {up_hit:>7.1f}%  {up_pnl:>+6.2f}  "
              f"{len(dns):>5d}  {dn_hit:>7.1f}%  {dn_pnl:>+6.2f}  {tag:>10s}  ({delta:+.1f}pp)")

    # 6. V3 family combined per-asset: which variant is BEST per asset
    print("\n" + "="*100)
    print("WINNER PER ASSET — V3 family ranked by total live-rescaled PnL")
    print("="*100)
    for asset in ("BTC", "ETH", "SOL"):
        results = []
        for v in ("v3", "v3_1", "v3_2", "v3_3", "v4"):
            trades = by_av.get((asset, v), [])
            if not trades:
                continue
            s = stats(trades)
            results.append((v, s))
        results.sort(key=lambda x: -x[1]["total_pnl_live"])
        print(f"\n{asset}:")
        for rank, (v, s) in enumerate(results, 1):
            ci = f"[{s['ci_lo']*100:.0f},{s['ci_hi']*100:.0f}]"
            tag = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else " "
            print(f"  {tag} #{rank}.  {v:6s}  n={s['n']:>3d}  hit={s['hit_rate']*100:>4.1f}% {ci}  "
                  f"pnl=${s['total_pnl_live']:>+6.2f}  per-trade=${s['avg_pnl_live']:>+5.3f}")


if __name__ == "__main__":
    main()
