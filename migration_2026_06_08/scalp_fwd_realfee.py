"""Re-baseline shadow scalp PnL with the real taker sell-leg fee (0.07*q*(1-q)*shares).
Shadow logs sell_leg_fee=0.0 (optimistic). Recompute mean + bootstrap CI for the
deployable d3 sleeves only."""
import json, glob, random
from collections import defaultdict

TARGET = {
    "shadow_scalp_exit_btc_5m_d3_v1", "shadow_scalp_exit_btc_15m_d3_v1",
    "shadow_scalp_exit_eth_5m_d3_v1", "shadow_scalp_exit_btc_5m_d3_control_v1",
    "shadow_scalp_exit_btc_5m_d3_notp_v1", "shadow_scalp_exit_btc_5m_d3_tod2_v1",
}
rows = defaultdict(list)  # sid -> list of (pnl_raw, pnl_realfee)
for f in sorted(glob.glob("/var/log/tradingvenue/sniper_v5/2026-*.jsonl")):
    with open(f) as fh:
        for line in fh:
            if "sleeve_scalp_exit" not in line:
                continue
            try:
                d = json.loads(line)
            except Exception:
                continue
            if d.get("event_type") != "sleeve_scalp_exit":
                continue
            sid = d.get("sleeve_id", "")
            if sid not in TARGET:
                continue
            p = d.get("pnl_usd")
            if p is None:
                continue
            p = float(p)
            q = d.get("hedge_sell_vwap")
            sh = d.get("fill_shares")
            fee = 0.0
            if q is not None and sh is not None:
                q = float(q); sh = float(sh)
                fee = 0.07 * q * (1.0 - q) * sh   # taker sell-leg fee
            rows[sid].append((p, p - fee))


def boot_ci(xs, n=4000):
    random.seed(7)
    k = len(xs)
    if k < 2:
        return (float("nan"), float("nan"))
    m = []
    for _ in range(n):
        m.append(sum(xs[random.randrange(k)] for _ in range(k)) / k)
    m.sort()
    return (m[int(0.025 * n)], m[int(0.975 * n)])


print("%-42s %4s | %8s %16s | %8s %16s" %
      ("sleeve", "n", "raw$", "rawCI", "realfee$", "realfeeCI"))
for sid in sorted(rows):
    v = rows[sid]
    raw = [a for a, b in v]
    adj = [b for a, b in v]
    n = len(v)
    rlo, rhi = boot_ci(raw)
    alo, ahi = boot_ci(adj)
    print("%-42s %4d | %8.3f [%6.3f,%6.3f] | %8.3f [%6.3f,%6.3f]" %
          (sid, n, sum(raw) / n, rlo, rhi, sum(adj) / n, alo, ahi))
