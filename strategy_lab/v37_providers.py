"""
V37 — Provider abstraction for the Claude-as-Trader backtest.

Three call layers, one common contract.

  ClaudeCLIProvider     — drives the `claude` CLI as a subprocess.
                           Uses your `claude login` auth → counts against
                           your Max / Pro / Team subscription quota,
                           NOT against the Anthropic API token bill.
                           Best for $0-marginal-cost validation runs.

  AnthropicAPIProvider  — official `anthropic` SDK with prompt caching.
                           Pay-per-token, but supports Batch API
                           (50% off + async). Best for full-grid backtests.

  OpenRouterProvider    — OpenAI-compatible endpoint at openrouter.ai.
                           Lets you swap to GLM-4.5, Kimi K2, DeepSeek-V3,
                           Sonnet, anything. Best for cost-down at scale.

All three return a validated `Decision` (Pydantic model) given a
(system_prompt, user_snapshot) pair.

Design doc:    strategy_lab/reports/V37_CLAUDE_TRADER_DESIGN.md
System prompt: strategy_lab/prompts/claude_trader_system.md
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error
from typing import Protocol

from strategy_lab.v37_claude_trader import Decision, load_system_prompt


# ─── Robust JSON extraction (text-out providers) ────────────────────
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_first_json_object(text: str) -> str:
    """
    Pull the first JSON object out of a text response.
    Handles: fenced code blocks, raw {...}, leading prose.
    Raises ValueError if no balanced object can be found.
    """
    if not text or not text.strip():
        raise ValueError("empty response")
    fence = _JSON_FENCE_RE.search(text)
    if fence:
        return fence.group(1)
    start = text.find("{")
    if start < 0:
        raise ValueError(f"no '{{' in response: {text[:200]!r}")
    depth = 0
    in_str = False
    esc = False
    for i, ch in enumerate(text[start:], start):
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start: i + 1]
    raise ValueError("unbalanced braces in response")


def parse_decision_or_flat(text: str, where: str = "") -> Decision:
    """
    Best-effort parse. On any failure, return a safe Flat decision so
    the backtest can continue and the failure is logged downstream.
    """
    try:
        raw = _extract_first_json_object(text)
        return Decision.model_validate_json(raw)
    except Exception as e:
        print(f"[V37 parse-error{(' ' + where) if where else ''}] "
              f"{type(e).__name__}: {e!s} — fallback to Flat", file=sys.stderr)
        return Decision(
            regime="transition", strategy="Flat", direction="none",
            size_mult=0.0, confidence=0.0,
            rationale=f"parse-error fallback: {type(e).__name__}",
        )


# ─── Provider contract ──────────────────────────────────────────────
class TraderClient(Protocol):
    """Every provider returns a validated Decision for (system, user)."""
    name: str
    def decide(self, snapshot: str, system_prompt: str) -> Decision: ...


# ─── 1. Claude CLI subprocess (Max / Pro subscription) ──────────────
class ClaudeCLIProvider:
    """
    Drives `claude --print` as a subprocess. Uses whatever account your
    `claude` CLI is logged into — which means a Max 20× / Pro / Team
    subscription if you've authed that way. No API key needed.

    Trade-offs vs API:
      * $0 marginal cost (subscription you already pay)
      * ~3-5s subprocess overhead per call
      * No Batch API, no async parallelism
      * No native structured outputs — we parse JSON from text
      * Subject to CLI rate limits (Max 20× ≈ 900 msg / 5h)
      * pace_seconds gates the call rate to stay under that ceiling
    """
    name = "claude-cli"

    def __init__(self,
                  model: str = "sonnet",
                  binary: str = "claude",
                  pace_seconds: float = 4.0,
                  timeout_seconds: int = 180,
                  max_retries: int = 4):
        self.model = model
        # Resolve to a full path. On Windows `claude` is a .cmd file —
        # CreateProcess (subprocess.run without shell=True) won't find .cmd
        # via PATH. shutil.which() returns the full .cmd path which DOES work.
        resolved = shutil.which(binary)
        if resolved is None:
            raise RuntimeError(
                f"Could not locate `{binary}` on PATH. "
                f"Install Claude Code (`npm i -g @anthropic-ai/claude-code`) "
                f"and ensure `claude --version` works in your terminal."
            )
        self.binary = resolved
        self.pace_seconds = pace_seconds
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    def _invoke(self, snapshot: str, system_prompt: str) -> str:
        # `claude --print` reads the user prompt from stdin (avoids arg-length
        # limits on Windows) and emits the assistant text on stdout.
        cmd = [
            self.binary, "--print",
            "--model", self.model,
            "--append-system-prompt", system_prompt,
        ]
        proc = subprocess.run(
            cmd, input=snapshot, capture_output=True, text=True,
            timeout=self.timeout_seconds, encoding="utf-8",
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"claude CLI exited {proc.returncode}: "
                f"stderr={proc.stderr[:500]!r}"
            )
        return proc.stdout

    def decide(self, snapshot: str, system_prompt: str) -> Decision:
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                text = self._invoke(snapshot, system_prompt)
                # Pace AFTER the call so a quick reply doesn't immediately
                # fire the next; before sleep gives the CLI a beat to settle.
                time.sleep(self.pace_seconds)
                return parse_decision_or_flat(text, where=self.name)
            except subprocess.TimeoutExpired as e:
                last_err = e
                wait = min(60.0, 5.0 * (2 ** attempt))
                print(f"[{self.name}] timeout (attempt {attempt+1}/"
                      f"{self.max_retries}); sleeping {wait}s", file=sys.stderr)
                time.sleep(wait)
            except RuntimeError as e:
                last_err = e
                msg = str(e).lower()
                # Heuristic rate-limit detection — claude CLI prints various
                # messages; treat any non-zero exit + "rate"/"limit" as 429-ish.
                if "rate" in msg or "limit" in msg or "quota" in msg:
                    wait = min(300.0, 30.0 * (2 ** attempt))
                    print(f"[{self.name}] rate-limited; sleeping {wait}s",
                          file=sys.stderr)
                    time.sleep(wait)
                else:
                    raise
        # Exhausted retries — return Flat so backtest continues
        print(f"[{self.name}] giving up after {self.max_retries} attempts: "
              f"{last_err!r}", file=sys.stderr)
        return Decision(
            regime="transition", strategy="Flat", direction="none",
            size_mult=0.0, confidence=0.0,
            rationale=f"retries-exhausted: {type(last_err).__name__}",
        )


# ─── 2. Anthropic API (token-billed, supports Batch API + caching) ──
class AnthropicAPIProvider:
    """
    Pay-per-token Anthropic API via the official SDK.
    Uses prompt caching on the system block (90% cheaper after first call).
    Supports Batch API for historical backtests via .batch_decide().
    """
    name = "anthropic-api"

    def __init__(self, model: str = "claude-sonnet-4-6"):
        try:
            import anthropic                                  # noqa: F401
        except ImportError as e:
            raise RuntimeError(
                "AnthropicAPIProvider requires the `anthropic` package. "
                "Install with: pip install 'anthropic>=0.88.0'"
            ) from e
        import anthropic as _a
        self._a = _a
        self.client = _a.Anthropic()                          # ANTHROPIC_API_KEY env
        self.model = model

    def _system_block(self, system_prompt: str) -> list[dict]:
        return [{
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }]

    def decide(self, snapshot: str, system_prompt: str) -> Decision:
        resp = self.client.messages.parse(
            model=self.model,
            max_tokens=4000,
            thinking={"type": "adaptive"},
            system=self._system_block(system_prompt),
            messages=[{"role": "user", "content": snapshot}],
            output_format=Decision,
        )
        return resp.parsed_output

    # Batch API — 50% off, async. Used by the historical runner when
    # provider="anthropic-api" is selected.
    def batch_decide(self,
                      snapshots_by_id: dict[str, str],
                      system_prompt: str,
                      poll_seconds: int = 30) -> dict[str, Decision]:
        from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
        from anthropic.types.messages.batch_create_params import Request

        sys_block = self._system_block(system_prompt)
        schema = Decision.model_json_schema()
        requests = [
            Request(
                custom_id=cid,
                params=MessageCreateParamsNonStreaming(
                    model=self.model, max_tokens=4000,
                    thinking={"type": "adaptive"},
                    system=sys_block,
                    messages=[{"role": "user", "content": snap}],
                    output_config={"format": {"type": "json_schema", "schema": schema}},
                ),
            )
            for cid, snap in snapshots_by_id.items()
        ]
        batch = self.client.messages.batches.create(requests=requests)
        print(f"[{self.name}] batch {batch.id} — {len(requests)} requests")
        while True:
            batch = self.client.messages.batches.retrieve(batch.id)
            if batch.processing_status == "ended":
                break
            rc = batch.request_counts
            print(f"[{self.name}] {batch.processing_status}  "
                  f"ok={rc.succeeded} err={rc.errored} proc={rc.processing}")
            time.sleep(poll_seconds)

        out: dict[str, Decision] = {}
        for r in self.client.messages.batches.results(batch.id):
            if r.result.type == "succeeded":
                txt = next(b.text for b in r.result.message.content if b.type == "text")
                out[r.custom_id] = parse_decision_or_flat(txt, where=r.custom_id)
            else:
                out[r.custom_id] = Decision(
                    regime="transition", strategy="Flat", direction="none",
                    size_mult=0.0, confidence=0.0,
                    rationale=f"batch-error: {r.result.type}",
                )
        return out


# ─── 3. OpenRouter (OpenAI-compatible — GLM, Kimi, DeepSeek, etc.) ──
class OpenRouterProvider:
    """
    OpenAI-compatible chat completions endpoint that proxies many models:
      - z-ai/glm-4.5         (very cheap, strong reasoning)
      - moonshotai/kimi-k2   (256k context)
      - deepseek/deepseek-chat-v3
      - anthropic/claude-sonnet-4.6  (Sonnet through OpenRouter)

    Set OPENROUTER_API_KEY in env. urllib only — no extra dep.
    Returns text → we parse JSON via parse_decision_or_flat().
    """
    name = "openrouter"
    URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self,
                  model: str = "z-ai/glm-4.5",
                  api_key: str | None = None,
                  http_referer: str = "https://localhost/v37-trader",
                  app_name: str = "v37-claude-trader",
                  pace_seconds: float = 0.5,
                  timeout_seconds: int = 90,
                  max_retries: int = 5):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not self.api_key:
            raise RuntimeError("Set OPENROUTER_API_KEY env var.")
        self.model = model
        self.http_referer = http_referer
        self.app_name = app_name
        self.pace_seconds = pace_seconds
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    def _invoke(self, snapshot: str, system_prompt: str) -> str:
        body = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": snapshot},
            ],
            "max_tokens": 4000,
            "response_format": {"type": "json_object"},   # honored by most OR models
        }).encode("utf-8")
        req = urllib.request.Request(
            self.URL, data=body, method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": self.http_referer,
                "X-Title": self.app_name,
            },
        )
        with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return payload["choices"][0]["message"]["content"]

    def decide(self, snapshot: str, system_prompt: str) -> Decision:
        last_err: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                text = self._invoke(snapshot, system_prompt)
                if self.pace_seconds > 0:
                    time.sleep(self.pace_seconds)
                return parse_decision_or_flat(text, where=f"{self.name}:{self.model}")
            except urllib.error.HTTPError as e:
                last_err = e
                if e.code in (429, 500, 502, 503, 504):
                    wait = min(60.0, 2.0 * (2 ** attempt))
                    print(f"[{self.name}] HTTP {e.code}; sleeping {wait}s",
                          file=sys.stderr)
                    time.sleep(wait)
                else:
                    raise
            except (urllib.error.URLError, TimeoutError) as e:
                last_err = e
                wait = min(30.0, 2.0 * (2 ** attempt))
                print(f"[{self.name}] network error {e!r}; sleeping {wait}s",
                      file=sys.stderr)
                time.sleep(wait)
        return Decision(
            regime="transition", strategy="Flat", direction="none",
            size_mult=0.0, confidence=0.0,
            rationale=f"openrouter-retries-exhausted: {type(last_err).__name__}",
        )


# ─── Factory ────────────────────────────────────────────────────────
PROVIDERS = {
    "claude-cli": ClaudeCLIProvider,
    "anthropic-api": AnthropicAPIProvider,
    "openrouter": OpenRouterProvider,
}


def make_provider(name: str, **kwargs) -> TraderClient:
    if name not in PROVIDERS:
        raise ValueError(f"unknown provider {name!r}; choose from {list(PROVIDERS)}")
    return PROVIDERS[name](**kwargs)


__all__ = [
    "TraderClient", "ClaudeCLIProvider", "AnthropicAPIProvider",
    "OpenRouterProvider", "make_provider", "PROVIDERS",
    "parse_decision_or_flat",
]
