"""V4-C LLM event classifier — production scaffold.

Replaces V4-C's lexicon-based sentiment (positive/negative keyword count) with
a real LLM call (Claude / Kimi K2 / GLM 4.6). Returns per-market UP/DOWN/SKIP
with confidence.

USAGE — set ANTHROPIC_API_KEY (or rewrite the call_llm function for Kimi/GLM):
  python -m strategy_lab.v4_signals.v4c_llm_classifier --asset btc --timeframe 5m
  python -m strategy_lab.v4_signals.v4c_llm_classifier --sample 200

The harness:
  1. Loads polymarket markets + Reddit + F&G features (built by v4c_feature_join.py)
  2. For each market window, packs the last 4h of relevant Reddit titles into a prompt
  3. Calls the LLM, parses {direction: UP/DOWN/SKIP, confidence: 0-100, rationale: str}
  4. Caches responses to data/v4/llm_cache/{model}/{market_id}.json
  5. Writes scored CSV with LLM verdict joined to outcome_up

Defensive design:
  - Cache hits skip API calls (idempotent re-runs)
  - Bad JSON => SKIP, log
  - Rate limit: 0.5s between calls for Anthropic free tier safety
  - Token budget: Claude Haiku 4.5 = $1/$5 per 1M; ~500 tokens in + 100 out per call
    => 6,143 markets x ~$0.001 = ~$6 to backtest full window on Haiku 4.5
    => Kimi K2 0905 (Fireworks) = ~$0.001 per call cached ~$0.10 if all cache miss
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SENT = ROOT / "data" / "v4" / "sentiment"
PM_DIR = ROOT / "strategy_lab" / "data" / "polymarket"
CACHE = ROOT / "data" / "v4" / "llm_cache"
CACHE.mkdir(parents=True, exist_ok=True)

# Default model — change via env var V4C_MODEL=...
MODEL = os.environ.get("V4C_MODEL", "claude-haiku-4-5")
PROVIDER = os.environ.get("V4C_PROVIDER", "anthropic")  # anthropic | fireworks (Kimi) | openrouter (GLM)


PROMPT_TEMPLATE = """You are a crypto trading event classifier. Given recent news/social posts
about {asset_upper}, predict whether the {asset_upper} price will be HIGHER or LOWER
{horizon_minutes} minutes from now (the resolution time of a Polymarket UP/DOWN binary market).

Current setup:
- Asset: {asset_upper}
- Current price (Binance perp): ${price:.2f}
- Window starts: {window_start_iso}
- Resolution in {horizon_minutes} min
- Fear & Greed today: {fg_value} ({fg_class})
- Recent 5m return: {ret_5m_pct:+.3f}%
- Recent 15m return: {ret_15m_pct:+.3f}%

Recent Reddit posts ({n_posts} from r/{subs} in last 4h):
{post_lines}

Classify the directional bias. Output ONLY valid JSON:
{{"direction": "UP" | "DOWN" | "SKIP", "confidence": 0-100, "rationale": "<20 words"}}

Rules:
- "SKIP" if signal is too weak/conflicting to call
- "confidence" = your subjective probability of being correct (50 = coin flip)
- Be conservative — defaulting to SKIP is fine"""


def call_llm_anthropic(prompt: str, model: str) -> dict:
    """Anthropic SDK call. Requires `pip install anthropic` and ANTHROPIC_API_KEY."""
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("anthropic SDK not installed. Run: pip install anthropic")
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=model,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text.strip()
    return parse_llm_response(text)


def call_llm_fireworks(prompt: str, model: str) -> dict:
    """Fireworks AI for Kimi K2. Requires FIREWORKS_API_KEY env var."""
    import urllib.request, urllib.error
    api_key = os.environ.get("FIREWORKS_API_KEY")
    if not api_key:
        raise RuntimeError("FIREWORKS_API_KEY not set")
    url = "https://api.fireworks.ai/inference/v1/chat/completions"
    body = json.dumps({
        "model": model,  # e.g. "accounts/fireworks/models/kimi-k2-instruct-0905"
        "max_tokens": 200,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read())
    text = d["choices"][0]["message"]["content"].strip()
    return parse_llm_response(text)


def parse_llm_response(text: str) -> dict:
    """Pull JSON object from LLM output. Robust to surrounding prose."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return {"direction": "SKIP", "confidence": 0, "rationale": "no_json", "_raw": text[:200]}
    try:
        obj = json.loads(m.group(0))
        # validate
        if obj.get("direction") not in ("UP", "DOWN", "SKIP"):
            obj["direction"] = "SKIP"
        obj["confidence"] = int(obj.get("confidence", 0))
        return obj
    except Exception as e:
        return {"direction": "SKIP", "confidence": 0, "rationale": f"parse_err: {e}", "_raw": text[:200]}


def cache_path(asset: str, market_idx: int, model: str) -> Path:
    safe_model = re.sub(r"[^a-zA-Z0-9_-]", "_", model)
    return CACHE / safe_model / f"{asset}_{market_idx:06d}.json"


def call_llm(prompt: str) -> dict:
    if PROVIDER == "anthropic":
        return call_llm_anthropic(prompt, MODEL)
    elif PROVIDER == "fireworks":
        return call_llm_fireworks(prompt, MODEL)
    else:
        raise NotImplementedError(f"Provider {PROVIDER} not wired yet")


def build_prompt(row, posts_df: pd.DataFrame) -> str:
    asset = row["asset"]
    horizon_minutes = 5 if row["timeframe"] == "5m" else 15
    win_start_unix = row["window_start_unix"]
    posts_in_window = posts_df[
        (posts_df["created_utc"] >= win_start_unix - 4 * 3600)
        & (posts_df["created_utc"] <= win_start_unix)
    ].tail(15)  # cap at 15 most recent to fit prompt
    post_lines = "\n".join(
        f"- [{p['subreddit']}] (score {p['score']}) {p['title'][:120]}"
        for _, p in posts_in_window.iterrows()
    ) if len(posts_in_window) else "(no posts)"

    fg_class_map = {1: "Extreme Fear", 2: "Fear", 3: "Neutral", 4: "Greed", 5: "Extreme Greed"}
    fg_v = row.get("fg_value", 50)
    if fg_v < 25: fg_class = "Extreme Fear"
    elif fg_v < 45: fg_class = "Fear"
    elif fg_v < 55: fg_class = "Neutral"
    elif fg_v < 75: fg_class = "Greed"
    else: fg_class = "Extreme Greed"

    return PROMPT_TEMPLATE.format(
        asset_upper=asset.upper(),
        horizon_minutes=horizon_minutes,
        price=row.get("strike_price", 0) or 0,
        window_start_iso=pd.to_datetime(win_start_unix, unit="s", utc=True).isoformat(),
        fg_value=int(fg_v) if pd.notna(fg_v) else 50,
        fg_class=fg_class,
        ret_5m_pct=(row.get("ret_5m", 0) or 0) * 100,
        ret_15m_pct=(row.get("ret_15m", 0) or 0) * 100,
        n_posts=len(posts_in_window),
        subs="+".join(set(posts_in_window["subreddit"])) if len(posts_in_window) else "none",
        post_lines=post_lines,
    )


def classify_markets(asset: str, timeframe: str, sample: int | None = None,
                     dry_run: bool = False, sleep_sec: float = 0.5) -> pd.DataFrame:
    pm = pd.read_csv(PM_DIR / f"{asset}_features_v3.csv")
    pm = pm.dropna(subset=["outcome_up", "ret_5m", "window_start_unix"]).copy()
    pm = pm[pm["timeframe"] == timeframe].reset_index(drop=True)
    pm["asset"] = asset

    # Load reddit posts and filter to asset
    reddit = pd.read_parquet(SENT / "reddit_posts.parquet")
    if asset == "btc":
        keep_subs = ["Bitcoin", "CryptoCurrency"]
        kwd_pat = r"btc|bitcoin"
    elif asset == "eth":
        keep_subs = ["ethfinance", "CryptoCurrency"]
        kwd_pat = r"\beth\b|ethereum|ether\b"
    elif asset == "sol":
        keep_subs = ["solana", "CryptoCurrency"]
        kwd_pat = r"\bsol\b|solana"
    reddit = reddit[reddit["subreddit"].isin(keep_subs)].copy()
    reddit["text"] = (reddit["title"].fillna("") + " " + reddit["selftext"].fillna("")).str.lower()
    reddit = reddit[reddit["text"].str.contains(kwd_pat, regex=True, na=False)
                    | reddit["subreddit"].isin([s for s in keep_subs if s != "CryptoCurrency"])]
    reddit = reddit.sort_values("created_utc").reset_index(drop=True)

    # Load F&G
    fg = pd.read_parquet(SENT / "fear_greed.parquet")
    fg["fg_date"] = pd.to_datetime(fg["date"]).dt.tz_localize("UTC")
    pm["window_start_dt"] = pd.to_datetime(pm["window_start_unix"], unit="s", utc=True)
    pm["window_date"] = pm["window_start_dt"].dt.normalize()
    pm = pm.merge(
        fg[["fg_date", "fg_value"]].rename(columns={"fg_date": "window_date"}),
        on="window_date", how="left"
    )

    if sample is not None and sample < len(pm):
        pm = pm.sample(sample, random_state=42).reset_index(drop=True)

    print(f"Classifying {len(pm)} {asset} {timeframe} markets via {PROVIDER}/{MODEL}")
    results = []
    for i, row in pm.iterrows():
        cp = cache_path(asset, int(i), MODEL)
        if cp.exists():
            verdict = json.loads(cp.read_text())
        elif dry_run:
            print(f"  [{i+1}/{len(pm)}] DRY-RUN — skipping LLM call")
            verdict = {"direction": "SKIP", "confidence": 0, "rationale": "dry_run"}
        else:
            prompt = build_prompt(row, reddit)
            try:
                verdict = call_llm(prompt)
            except Exception as e:
                print(f"  [{i+1}/{len(pm)}] ERROR: {e}")
                verdict = {"direction": "SKIP", "confidence": 0, "rationale": f"err:{e}"}
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_text(json.dumps(verdict))
            time.sleep(sleep_sec)
            if (i + 1) % 25 == 0:
                print(f"  [{i+1}/{len(pm)}] cached")

        results.append({
            "asset": asset, "market_idx": i,
            "window_start_unix": row["window_start_unix"],
            "outcome_up": row["outcome_up"],
            "ret_5m": row["ret_5m"],
            "llm_direction": verdict.get("direction"),
            "llm_confidence": verdict.get("confidence", 0),
            "llm_rationale": verdict.get("rationale", ""),
        })

    return pd.DataFrame(results)


def evaluate(df: pd.DataFrame, conf_threshold: int = 60):
    print(f"\n=== LLM verdict eval (n={len(df)}, conf>={conf_threshold}) ===")
    fired = df[(df["llm_direction"] != "SKIP") & (df["llm_confidence"] >= conf_threshold)]
    print(f"  fired:  {len(fired)} ({len(fired)/len(df)*100:.1f}%)")
    print(f"  skipped: {(df['llm_direction']=='SKIP').sum()}")
    if len(fired) == 0:
        print("  no fires")
        return
    fired = fired.copy()
    pred_up = fired["llm_direction"] == "UP"
    actual_up = fired["outcome_up"] == 1
    fired["hit"] = (pred_up & actual_up) | (~pred_up & ~actual_up)
    print(f"  hit_rate: {fired['hit'].mean()*100:.2f}%  (baseline 50%)")
    for d in ("UP", "DOWN"):
        sub = fired[fired["llm_direction"] == d]
        if len(sub):
            print(f"  {d}: n={len(sub)} hit={sub['hit'].mean()*100:.2f}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default="btc", choices=["btc", "eth", "sol"])
    ap.add_argument("--timeframe", default="5m", choices=["5m", "15m"])
    ap.add_argument("--sample", type=int, default=None, help="random subset size for cheap run")
    ap.add_argument("--dry-run", action="store_true", help="don't call LLM, just build prompts")
    ap.add_argument("--conf-threshold", type=int, default=60)
    ap.add_argument("--sleep", type=float, default=0.5)
    args = ap.parse_args()

    df = classify_markets(args.asset, args.timeframe, sample=args.sample,
                          dry_run=args.dry_run, sleep_sec=args.sleep)
    out = ROOT / "data" / "v4" / f"v4c_llm_{args.asset}_{args.timeframe}.csv"
    df.to_csv(out, index=False)
    print(f"\nSaved {len(df)} verdicts -> {out.relative_to(ROOT)}")
    evaluate(df, conf_threshold=args.conf_threshold)


if __name__ == "__main__":
    main()
