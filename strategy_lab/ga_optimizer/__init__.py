"""GA optimizer package for momo / mispricing sleeves on Polymarket binary options.

Modules:
  genome      Gene definitions + mutation operators per gene kind
  operators   Selection / crossover / breeding pipeline
  fitness     PnL-heavy composite + backtest harness wrapper (lookahead-corrected)
  ga_loop     Main evolution loop with checkpointing
  runner      CLI entry: orchestrate single or multi-niche optimization
  seeds       Known-good initial individuals (from manual fade-scan winners)

Critical: every fitness eval uses LATENCY_US=100_000 shift on kline asof to
prevent the microsec lookahead documented in LOOKAHEAD_CORRECTION.md.
"""
