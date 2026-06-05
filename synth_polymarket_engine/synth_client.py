"""Synth API client (synthdata.co). Needs env SYNTH_API_KEY.

Key endpoint for us: /insights/polymarket/up-down/{tf} -> synth_probability_up vs
polymarket_probability_up (the value-bet signal). start_time= for historical snapshots.

Docs: https://docs.synthdata.co/rest-api
"""
from __future__ import annotations
import os, time, requests

BASE = "https://api.synthdata.co"
KEY = os.environ.get("SYNTH_API_KEY", "")
UA = {"User-Agent": "global-strategy-lab/1.0"}

class SynthError(Exception): ...

def _auth():
    if not KEY:
        raise SynthError("set SYNTH_API_KEY env (get one at https://dashboard.synthdata.co/)")
    return {**UA, "Authorization": f"Apikey {KEY}"}

def _get(path: str, params: dict | None = None, auth: bool = True, tries: int = 4):
    h = _auth() if auth else UA
    for i in range(tries):
        try:
            r = requests.get(f"{BASE}{path}", params=params or {}, headers=h, timeout=20)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (401, 403):
                raise SynthError(f"auth/credits error {r.status_code}: {r.text[:200]}")
            if r.status_code == 429:
                time.sleep(1.5 + i)  # rate-limited, back off
                continue
            return {"_status": r.status_code, "_text": r.text[:300]}
        except SynthError:
            raise
        except Exception:
            time.sleep(0.6 + i)
    return None

# ---- Polymarket comparison (THE signal) ----
PM_TF = {"5min", "15min", "hourly", "daily"}
def polymarket_up_down(asset: str = "BTC", tf: str = "15min", start_time: str | None = None) -> dict:
    """synth_probability_up vs polymarket_probability_up for an up-down contract.
    tf in {5min,15min,hourly,daily}. start_time ISO8601 for historical snapshot."""
    assert tf in PM_TF, tf
    p = {"asset": asset}
    if start_time: p["start_time"] = start_time
    return _get(f"/insights/polymarket/up-down/{tf}", p)

def polymarket_range_daily(asset="BTC", start_time=None):
    p={"asset":asset};  p.update({"start_time":start_time} if start_time else {})
    return _get("/insights/polymarket/range/daily", p)
def polymarket_above_daily(asset="BTC", start_time=None):
    p={"asset":asset};  p.update({"start_time":start_time} if start_time else {})
    return _get("/insights/polymarket/above/daily", p)
def polymarket_hit_daily(asset="BTC", start_time=None):
    p={"asset":asset};  p.update({"start_time":start_time} if start_time else {})
    return _get("/insights/polymarket/hit/daily", p)

# ---- raw forecast (to build our own P(up) if we ever want to) ----
def prediction_percentiles(asset="BTC", horizon="1h", start_time=None):
    p={"asset":asset,"horizon":horizon}; p.update({"start_time":start_time} if start_time else {})
    return _get("/insights/prediction-percentiles", p)

# ---- public (no key) ----
def leaderboard_v2(prompt_name="high"):  # 'high'=1h prompt, 'low'=24h
    return _get("/v2/leaderboard/latest", {"prompt_name": prompt_name}, auth=False)

def edge(snapshot: dict) -> float | None:
    """value-bet edge = synth P(up) - polymarket P(up). Positive -> bet UP."""
    try:
        return float(snapshot["synth_probability_up"]) - float(snapshot["polymarket_probability_up"])
    except Exception:
        return None

if __name__ == "__main__":
    # smoke test (needs key). prints current BTC 15min synth-vs-poly + edge.
    snap = polymarket_up_down("BTC", "15min")
    print("snapshot:", snap)
    if isinstance(snap, dict) and "synth_probability_up" in snap:
        print(f"synth_p_up={snap['synth_probability_up']}  poly_p_up={snap['polymarket_probability_up']}  edge={edge(snap):+.3f}")
