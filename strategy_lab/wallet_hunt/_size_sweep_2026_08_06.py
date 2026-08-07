"""Size sweep — does the sim's gap to b945 close when SIZE is held equal?

The corrected decomposition (docs/B945-CORRECTED-DECOMPOSITION-2026-08-06.md)
says he wins on shares, not price:

                     b945     sim
    paired shares   753.1    74.6     10.1x
    edge (1-pvs)    0.031   0.187      0.17x   <- WE are 6x better
    paired PnL     +22.71  +10.23
    residual PnL   -18.78  -12.67
    net             +4.07   -2.03

`paired_pnl = shares x edge`. If size is the whole story, then running the SAME
engine on the SAME slugs at b945-scale budget should walk net from -2.03 toward
+4.07. If it does not, the gap is something else and the sim has a real defect.

Deliberately a separate driver, importing the engine rather than editing it, for
two reasons: `_mm_queue_engine.py` writes unconditionally to the 2026-06-12
report path (it clobbered that file on 2026-08-06, restored from git), and its
`compute_slug_pnl` is the shipped decomposition. We use the REBUILT one, which
reconciles against chain-true at 99.4% where the shipped ledger manages 0.2%.

usage: py -3 _size_sweep_2026_08_06.py [n_slugs]
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import _mm_queue_engine as E  # noqa: E402

OUT = Path(__file__).parent.parent / "reports" / "SIZE_SWEEP_2026_08_06.md"

# (budget_usd_per_side, clip_usd_per_order). Base is the engine's default.
GRID = [
    (100.0, 5.0),    # base — what produced -$2.03
    (200.0, 10.0),
    (400.0, 20.0),
    (400.0, 5.0),    # same budget, small clips: isolates clip from budget
    (800.0, 40.0),
]


def slug_pnl(r_up, r_dn, won_up):
    """REBUILT decomposition — the one that reconciles with redeem - cost.

    pairs        = min(sh_up, sh_dn)
    paired_pnl   = pairs * (1 - (vwap_up + vwap_dn))
    residual_pnl = wins ? resid*(1-vwap) : -resid*vwap
    """
    su, sd = r_up["filled_sh"], r_dn["filled_sh"]
    if su <= 0 and sd <= 0:
        return None
    vu = r_up["vwap"] if su > 0 else 0.0
    vd = r_dn["vwap"] if sd > 0 else 0.0
    pairs = min(su, sd)
    pvs = vu + vd
    paired_pnl = pairs * (1.0 - pvs) if pairs > 0 else 0.0
    resid = abs(su - sd)
    up_heavy = su > sd
    rv = vu if up_heavy else vd
    resid_wins = won_up if up_heavy else (not won_up)
    residual_pnl = resid * (1.0 - rv) if resid_wins else -resid * rv
    rebate = (su + sd) * E.REBATE_SH
    return {
        "pairs": pairs, "pvs": pvs, "resid": resid,
        "paired_pnl": paired_pnl, "residual_pnl": residual_pnl,
        "rebate": rebate, "net": paired_pnl + residual_pnl + rebate,
        "sh": su + sd,
    }


def main():
    n_slugs = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    res = E.load_resolutions()
    res = res[res.slug.str.startswith("btc-updown-15m-")].drop_duplicates("slug")
    # Only slugs that actually HAVE a trade tape. The book archive starts earlier
    # than the trade archive, so the first ~400 slugs by timestamp have depth and
    # no prints — simulating them yields zero fills and an empty sweep (which is
    # exactly what the first run of this script produced).
    import pyarrow.parquet as pq
    have_trades = set(
        pq.read_table(E.TR_PATH, columns=["slug"]).to_pandas().slug.unique()
    )
    res = res[res.slug.isin(have_trades)]
    res = res.sort_values("slug").head(n_slugs)
    # slug -> (slot_start_s, won_up)
    meta = {r.slug: (int(r.slot_start_s), str(r.outcome) == "Up") for r in res.itertuples()}
    slugs = list(meta)
    print(f"loading books/trades for {len(slugs)} slugs ...", flush=True)
    tob, depth = E.load_books(set(slugs))
    trades = E.load_trades(set(slugs))

    rows = []
    for budget, clip in GRID:
        acc = []
        for slug in slugs:
            slot_s, won_up = meta[slug]
            ru = E.sim_one_token(slug, "Up", slot_s, tob, depth, trades, -3600.0,
                                 budget_usd=budget, clip_usd_per_order=clip)
            rd = E.sim_one_token(slug, "Down", slot_s, tob, depth, trades, -3600.0,
                                 budget_usd=budget, clip_usd_per_order=clip)
            p = slug_pnl(ru, rd, won_up)
            if p:
                acc.append(p)
        if not acc:
            continue
        g = lambda k: float(np.mean([a[k] for a in acc]))  # noqa: E731
        rows.append({
            "budget": budget, "clip": clip, "n": len(acc),
            "pairs": g("pairs"), "pvs": g("pvs"), "resid": g("resid"),
            "paired_pnl": g("paired_pnl"), "residual_pnl": g("residual_pnl"),
            "net": g("net"),
        })
        r = rows[-1]
        print(f"  budget=${budget:<6.0f} clip=${clip:<5.1f} n={r['n']:<4d} "
              f"pairs={r['pairs']:7.1f} pvs={r['pvs']:.4f} "
              f"paired=${r['paired_pnl']:7.2f} resid=${r['residual_pnl']:8.2f} "
              f"net=${r['net']:7.2f}", flush=True)

    lines = [
        "# Size sweep — does the gap close when size is held equal?",
        "",
        f"**{n_slugs} slugs, placement −3600s, FIFO lower bound, REBUILT decomposition.**",
        "",
        "b945 on the same slugs: pairs **753.1**, pvs 0.969, paired **+$22.71**, "
        "residual **−$18.78**, net **+$4.07** (chain-true).",
        "",
        "| budget/side | clip | n | pairs | pvs | paired $ | residual $ | net $ |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| ${r['budget']:.0f} | ${r['clip']:.0f} | {r['n']} | {r['pairs']:.1f} | "
            f"{r['pvs']:.4f} | {r['paired_pnl']:+.2f} | {r['residual_pnl']:+.2f} | "
            f"**{r['net']:+.2f}** |"
        )
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwritten: {OUT}")


if __name__ == "__main__":
    main()
