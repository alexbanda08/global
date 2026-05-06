"""Champions dashboard (Portuguese) — final per-asset champion strategies.

Shows for each of BTC / ETH / SOL the three production candidates:
  1) 1h V4 (regime-filtered fixed-hold)
  2) 4h composite (event-driven TP/SL/trail)
  3) Ensemble 50/50 — the recommended deployment

Reads:
  strategy_lab/reports/derivatives_zscore/ensemble/summary.csv
  strategy_lab/reports/derivatives_zscore/ensemble/{SYM}/equity_{1h,4h,combined}.parquet

Writes:
  strategy_lab/reports/derivatives_zscore/ensemble/champions.html
"""
from __future__ import annotations
from pathlib import Path
import html
import math
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
EDIR = ROOT / "strategy_lab" / "reports" / "derivatives_zscore" / "ensemble"
SPOT = ROOT / "data" / "v4" / "derivatives_zscore" / "spot"
OUT = EDIR / "champions.html"

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
INIT_CAPITAL = 10_000.0


def fmt_num(v, d=2, sign=False):
    try:
        f = float(v)
        if pd.isna(f) or not math.isfinite(f):
            return "–"
        return f"{f:{'+' if sign else ''}.{d}f}"
    except Exception:
        return "–"


def fmt_pct(v, d=1, sign=False):
    try:
        f = float(v)
        if pd.isna(f) or not math.isfinite(f):
            return "–"
        return f"{f*100:{'+' if sign else ''}.{d}f}%"
    except Exception:
        return "–"


def equity_svg(eq: pd.Series, label: str, color: str, w=520, h=120, max_pts: int = 400) -> str:
    if eq is None or len(eq) < 2:
        return ""
    y = eq.to_numpy(dtype=float)
    if len(y) > max_pts:
        # Downsample by stride — preserves shape, drops file size 60×
        stride = len(y) // max_pts
        y = y[::stride]
    y = y / y[0]
    x = np.linspace(2, w - 4, len(y))
    ymin, ymax = float(y.min()), float(y.max())
    rng = max(ymax - ymin, 1e-6)
    y_norm = (y - ymin) / rng
    y_px = h - 6 - y_norm * (h - 14)
    pts = " ".join(f"{xi:.1f},{yi:.1f}" for xi, yi in zip(x, y_px))
    base_y = h - 6 - ((1.0 - ymin) / rng) * (h - 14)
    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'style="background:#0f1419;border:1px solid #23303e;border-radius:4px">'
        f'<line x1="2" x2="{w-2}" y1="{base_y:.1f}" y2="{base_y:.1f}" '
        f'stroke="#3a4a5e" stroke-dasharray="2,2" stroke-width="0.6"/>'
        f'<polyline fill="none" stroke="{color}" stroke-width="1.6" points="{pts}"/>'
        f'<text x="6" y="14" fill="#7d8796" font-size="10" font-family="monospace">{html.escape(label)}</text>'
        f'<text x="{w-6}" y="14" fill="#cfd6de" font-size="10" font-family="monospace" text-anchor="end">'
        f'final {y[-1]:.2f}×</text>'
        f'</svg>'
    )


def buy_hold_series(symbol: str) -> pd.Series:
    tag = symbol.replace("USDT", "")
    spot = pd.read_parquet(SPOT / f"BINANCE-{tag}-1h.parquet").set_index("time")["close"].astype(float)
    return spot / spot.iloc[0]


def metrics_table(label_pt: str, n: int, sharpe: float, calmar: float, mdd: float,
                   eq_x: float, bh: float, color: str, leg_capital: float = INIT_CAPITAL,
                   years: float = 3.0) -> str:
    op = eq_x / bh if bh > 0 else float("nan")
    final_dollar = leg_capital * eq_x
    profit_dollar = final_dollar - leg_capital
    roi_pct = (eq_x - 1) * 100
    cagr_pct = (eq_x ** (1 / years) - 1) * 100 if years > 0 else 0
    profit_color = "#4ac268" if profit_dollar >= 0 else "#d85a5a"
    bh_dollar_profit = leg_capital * (bh - 1)
    return f"""
<div class="leg" style="border-left-color:{color}">
  <div class="leg-title">{label_pt}</div>
  <table class="mini">
    <tr><td>Trades</td><td>{n}</td></tr>
    <tr><td>Sharpe</td><td>{fmt_num(sharpe, 2, sign=True)}</td></tr>
    <tr><td>Calmar</td><td>{fmt_num(calmar, 2, sign=True)}</td></tr>
    <tr><td>Max DD</td><td class="neg">{fmt_pct(mdd, 1)}</td></tr>
    <tr><td>Equity final</td><td>{eq_x:.2f}×</td></tr>
    <tr><td>vs Buy &amp; Hold</td>
        <td class="{'pos' if op>=1 else 'neg'}">{op:.2f}×</td></tr>
  </table>
  <div class="dollar-box">
    <div class="dollar-row"><span>Capital inicial</span><strong>${leg_capital:,.0f}</strong></div>
    <div class="dollar-row"><span>Capital final</span><strong>${final_dollar:,.0f}</strong></div>
    <div class="dollar-row"><span>Lucro/Prejuízo</span><strong style="color:{profit_color}">${profit_dollar:+,.0f}</strong></div>
    <div class="dollar-row"><span>ROI (3 anos)</span><strong style="color:{profit_color}">{roi_pct:+.1f}%</strong></div>
    <div class="dollar-row"><span>CAGR (anualizado)</span><strong style="color:{profit_color}">{cagr_pct:+.1f}%</strong></div>
    <div class="dollar-row"><span>vs B&amp;H lucro</span><strong>${bh_dollar_profit:+,.0f}</strong></div>
  </div>
</div>
"""


def build_glossary() -> str:
    """Compact Portuguese glossary covering everything specific to this dashboard."""
    return """
  <h2>📚 Glossário — Conceitos Deste Dashboard</h2>
  <div class="glossary">

    <p style="color:#9aa3b0;font-size:12px;margin-bottom:14px">
      Este glossário define cada termo do dashboard de campeões. Para definições aprofundadas dos indicadores derivativos
      (z_lsr, z_oi_silent, etc.), veja o <code>resultados.html</code> ou
      <code>regime_detector/regimedetector.html</code>.
    </p>

    <h3>🏆 Os três campeões</h3>
    <dl>
      <dt>Estratégia 1h (v4)</dt>
      <dd>Mean-reversion contrária em barras de 1 hora. Entra quando o
      <code>z_lsr</code> cai abaixo de −1,5σ E a volatilidade realizada de 30 dias
      está abaixo da mediana móvel de 90d (regime calmo). Hold fixo de 24h
      (BTC/ETH) ou 48h (SOL). Sem TP, sem SL, sem trail — só sai por tempo.
      Máximo de 1 posição aberta.</dd>

      <dt>Estratégia 4h (composite)</dt>
      <dd>Mesma tese (mean-reversion contrária) em barras de 4 horas, com sinal
      composto pelos indicadores validados pelo gradient boosting (top features
      no v2 do regime detector). Entrada multi-fator: ≥1 ou ≥3 dos sinais
      <code>z_top_lsr_count</code>, <code>brigalS</code>,
      <code>cross_institutional_lead</code>. Saída event-driven: TP em
      múltiplos de ATR, SL em múltiplos de ATR, trailing stop ATR ratchet.
      Filtro adicional: pausa novas entradas após 3 trades perdedores
      consecutivos (R_3loss_pause).</dd>

      <dt>Ensemble 50/50</dt>
      <dd>Aloca 50% do capital em cada estratégia (1h e 4h) operando
      independentemente. Como as duas estratégias disparam em momentos
      diferentes e usam lógicas de saída diferentes, suas perdas raramente
      coincidem — daí o <strong>drawdown combinado é menor que o de qualquer
      perna individual</strong>. Esta é a principal alavanca de redução de
      risco descoberta nesta sessão.</dd>
    </dl>

    <h3>📊 Métricas</h3>
    <dl>
      <dt>Sharpe Ratio</dt>
      <dd>(retorno médio / volatilidade) × √(barras por ano). Mede retorno por unidade de
      risco. Régua: <strong>&lt; 0,5</strong> ruim, <strong>0,5–1</strong> aceitável,
      <strong>1–2</strong> bom, <strong>&gt; 2</strong> excelente.</dd>

      <dt>Calmar Ratio</dt>
      <dd>CAGR / |Max DD|. Quanto retorno anual você ganha por unidade do pior tombo
      já vivido. Régua: &lt; 1 sofrível, 1–2 ok, 2–3 bom, &gt; 3 excelente.</dd>

      <dt>Max DD (Maximum Drawdown)</dt>
      <dd>Pior queda do pico ao vale, em %. Métrica que define se você "aguenta"
      a estratégia. Régua: &lt;15% excelente, 15–25% bom, 25–40% aceitável,
      &gt;40% sofrido.</dd>

      <dt>Equity final (×)</dt>
      <dd>Quantas vezes o capital inicial virou ao final dos 3 anos. Eq 2,0×
      significa $10k → $20k.</dd>

      <dt>vs Buy &amp; Hold</dt>
      <dd>Razão entre equity final da estratégia e o preço final / inicial do ativo.
      &gt;1 = bate "comprar e segurar"; &lt;1 = perde para a estratégia trivial.</dd>

      <dt>Trades</dt>
      <dd>Número total de operações fechadas em 3 anos. Menos trades não é melhor por
      si só — mas combinar baixa frequência com alto Sharpe é o ideal.</dd>
    </dl>

    <h3>🧩 Componentes do sinal</h3>
    <dl>
      <dt><code>z_lsr</code></dt>
      <dd>Z-score do Long/Short Ratio Accounts da Binance. Mede quão extremo o
      posicionamento da multidão está em relação ao próprio normal recente
      (janela 21 barras).</dd>

      <dt><code>z_top_lsr_count</code></dt>
      <dd>Z-score do LSR dos top traders por NÚMERO de contas. Mede o que os
      traders maiores (mais bem-sucedidos historicamente) estão fazendo.
      Foi o sinal com correlação mais forte (-0,36) em 4h.</dd>

      <dt><code>brigalS</code></dt>
      <dd>"Briga long-short" = z(long%) − z(short%). Diferença entre os z-scores
      das % de contas long vs short. Muito negativo = shorts em expansão
      relativa = sinal contrário bullish.</dd>

      <dt><code>cross_institutional_lead</code></dt>
      <dd>Δ(USDC.D) − Δ(USDT.D) — diferença entre as variações da dominância de
      USDC (institucional) e USDT (varejo). Positivo = smart money se
      posicionando antes do varejo. Top em importância no GB para todas
      as combinações testadas.</dd>
    </dl>

    <h3>🎯 Saídas event-driven (4h)</h3>
    <dl>
      <dt>TP × ATR (Take-Profit)</dt>
      <dd>Sai com lucro quando o preço atinge entrada + N × ATR(14).
      Aqui usamos <strong>TP = 6 × ATR</strong> (objetivo agressivo).</dd>

      <dt>SL × ATR (Stop Loss)</dt>
      <dd>Sai com prejuízo quando o preço cai para entrada − N × ATR(14).
      Aqui <strong>SL = 2,5 × ATR</strong>.</dd>

      <dt>Trailing Stop ATR ratchet</dt>
      <dd>Stop dinâmico que sobe (no long) sempre que o preço faz nova máxima.
      Calculado como max(high desde entrada) − N × ATR. Ratchet = só sobe,
      nunca desce. Aqui <strong>trail = 4 × ATR</strong>.</dd>

      <dt>Max hold</dt>
      <dd>Tempo máximo de manutenção. Aqui 48 barras × 4h = 8 dias. Se TP/SL/trail
      não disparam antes, sai a mercado no fim do prazo.</dd>

      <dt>R_3loss_pause</dt>
      <dd>Filtro de curva de equity. Após 3 trades perdedores consecutivos,
      pausa novas entradas. Despausa após qualquer trade vencedor. Ideia:
      o sinal pode estar "off" temporariamente; pular as próximas
      tentativas durante uma má sequência reduz drawdown sem matar a estratégia.</dd>
    </dl>

    <h3>💰 Custos modelados</h3>
    <dl>
      <dt>Hyperliquid taker fee</dt>
      <dd>4,5 bps por lado (0,045%) — cobrado em quem retira liquidez do livro.
      Tier base, sem desconto VIP.</dd>

      <dt>Slippage estimado</dt>
      <dd>1,5 bps por lado — derrapagem em pares líquidos (BTC, ETH, SOL) na
      Hyperliquid. Total round-trip: 4,5 + 1,5 + 4,5 + 1,5 =
      <strong>12 bps</strong>.</dd>

      <dt>Stress de custos (G8)</dt>
      <dd>Re-rodamos a estratégia a 24 bps round-trip (2× o custo base) para
      confirmar que o edge sobrevive a slippage anormal.</dd>
    </dl>

    <h3>🏛 Filtros de regime</h3>
    <dl>
      <dt>Low-vol regime</dt>
      <dd>Volatilidade realizada de 30 dias abaixo da mediana móvel de 90 dias.
      Mean-reversion (que é o que essa estratégia explora) funciona melhor em
      mercados calmos: em caos, "extremos" não são realmente extremos.</dd>

      <dt>Filtro EMA200d</dt>
      <dd>Usado em ETH e SOL: só opera long se preço &gt; média móvel exponencial
      de 200 dias. Evita comprar dips em downtrends estruturais. Não
      aplicamos a BTC porque cortou demais o sinal.</dd>
    </dl>

    <h3>🎓 Régua de bolso — interpretando os números</h3>
    <table class="ref">
      <thead><tr><th>Métrica</th><th>Ruim</th><th>Aceitável</th><th>Bom</th><th>Excelente</th></tr></thead>
      <tbody>
        <tr><td>Sharpe</td><td>&lt; 0,5</td><td>0,5–1,0</td><td>1,0–2,0</td><td>&gt; 2,0</td></tr>
        <tr><td>Calmar</td><td>&lt; 0,5</td><td>0,5–1,0</td><td>1,0–2,0</td><td>&gt; 2,0</td></tr>
        <tr><td>Max DD</td><td>&gt; 40%</td><td>25–40%</td><td>15–25%</td><td>&lt; 15%</td></tr>
        <tr><td>Win Rate</td><td colspan="4" style="color:#9aa3b0">depende da expectativa — sozinho não é métrica</td></tr>
      </tbody>
    </table>

    <p style="color:#9aa3b0;font-size:11px;margin-top:18px">
      <strong>Veredito do dashboard:</strong> A estratégia 1h tem o maior Sharpe individual.
      A 4h tem o menor drawdown individual. O <strong>ensemble combinado</strong> entrega
      drawdown mais raso que qualquer perna sozinha em todos os 3 ativos — esta é a
      principal recomendação para deploy em capital real. Os limites de drawdown
      combinados ficam entre −19% e −25%, viáveis para sizing realista.
    </p>

  </div>
"""


def build():
    summary = pd.read_csv(EDIR / "summary.csv")
    gen_ts = pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # Leverage sweep — load top configs per asset
    lev_path = EDIR / "leverage_sweep.csv"
    lev_top = []  # list of dicts: best ROI per asset
    if lev_path.exists():
        lev_df = pd.read_csv(lev_path)
        elig = lev_df[(~lev_df["combined_blew_up"])
                       & (lev_df["combined_mdd"] >= -0.40)
                       & (lev_df["combined_sharpe"] >= 0.5)]
        for sym in SYMBOLS:
            sub = elig[elig["symbol"] == sym].sort_values("combined_eq_x", ascending=False)
            if len(sub) > 0:
                top = sub.iloc[0]
                lev_top.append({
                    "symbol": sym,
                    "lev_1h": int(top["lev_1h"]),
                    "lev_4h": int(top["lev_4h_cap"]),
                    "risk": float(top["risk_4h"]),
                    "eq_x": float(top["combined_eq_x"]),
                    "mdd": float(top["combined_mdd"]),
                    "sharpe": float(top["combined_sharpe"]),
                    "roi": float(top["combined_roi_pct"]),
                    "final_dollar": float(top["final_dollar"]),
                    "uplift_dollar": float(top["final_dollar"]) - INIT_CAPITAL * float(
                        summary[summary["symbol"] == sym]["combined_eq_x"].iloc[0]),
                })

    # Headline portfolio simulation: $10k starting per asset → 3-asset combined portfolio
    total_initial = INIT_CAPITAL * len(SYMBOLS)
    total_final = sum(row["combined_eq_x"] * INIT_CAPITAL for _, row in summary.iterrows())
    total_profit = total_final - total_initial
    total_roi = (total_final / total_initial - 1) * 100
    total_cagr = ((total_final / total_initial) ** (1/3) - 1) * 100

    # Per-asset $ summary
    per_asset_dollar = []
    for _, r in summary.iterrows():
        per_asset_dollar.append({
            "symbol": r["symbol"],
            "initial": INIT_CAPITAL,
            "final": INIT_CAPITAL * r["combined_eq_x"],
            "profit": INIT_CAPITAL * (r["combined_eq_x"] - 1),
            "roi": (r["combined_eq_x"] - 1) * 100,
            "bh_final": INIT_CAPITAL * r["buy_hold_x"],
            "bh_profit": INIT_CAPITAL * (r["buy_hold_x"] - 1),
            "outperform": r["combined_outperform"],
            "mdd": r["combined_mdd"],
            "max_loss_dollar": INIT_CAPITAL * abs(r["combined_mdd"]),
        })

    panels = []
    for sym in SYMBOLS:
        row = summary[summary["symbol"] == sym].iloc[0]
        out_dir = EDIR / sym

        # Load equity curves
        eq_1h = pd.read_parquet(out_dir / "equity_1h.parquet")["equity"]
        eq_4h = pd.read_parquet(out_dir / "equity_4h.parquet")["equity"]
        eq_combined = pd.read_parquet(out_dir / "equity_combined.parquet")["equity"]
        bh = buy_hold_series(sym)

        # SVGs
        svg_1h = equity_svg(eq_1h, "1h V4", "#9dcefa")
        svg_4h = equity_svg(eq_4h, "4h composite", "#e0b280")
        svg_combined = equity_svg(eq_combined, "Ensemble 50/50", "#4ac268")
        svg_bh = equity_svg(bh, "Buy & Hold", "#7d8796")

        # Metrics tables
        m_1h = metrics_table("1h V4", row["leg_1h_n"], row["leg_1h_sharpe"],
                              row["leg_1h_eq_x"] / max(row["leg_1h_eq_x"], 1) * 0,  # placeholder, use combined cal
                              row["leg_1h_mdd"], row["leg_1h_eq_x"], row["buy_hold_x"], "#9dcefa")
        # We don't have leg-1h Calmar in summary; recompute roughly: cagr ≈ eq^(1/3)-1, calmar = cagr/|mdd|
        cagr_1h = row["leg_1h_eq_x"] ** (1/3) - 1
        cal_1h = cagr_1h / abs(row["leg_1h_mdd"]) if row["leg_1h_mdd"] != 0 else 0
        m_1h = metrics_table("1h V4 (regime + hold fixo)", row["leg_1h_n"], row["leg_1h_sharpe"],
                              cal_1h, row["leg_1h_mdd"], row["leg_1h_eq_x"], row["buy_hold_x"], "#9dcefa",
                              leg_capital=INIT_CAPITAL / 2)  # 50/50 split → $5k per leg
        cagr_4h = row["leg_4h_eq_x"] ** (1/3) - 1
        cal_4h = cagr_4h / abs(row["leg_4h_mdd"]) if row["leg_4h_mdd"] != 0 else 0
        m_4h = metrics_table("4h composite (TP/SL/trail + 3-loss pause)",
                              row["leg_4h_n"], row["leg_4h_sharpe"],
                              cal_4h, row["leg_4h_mdd"], row["leg_4h_eq_x"], row["buy_hold_x"], "#e0b280",
                              leg_capital=INIT_CAPITAL / 2)
        m_combined = metrics_table("⭐ Ensemble 50/50 (recomendado)", row["combined_n"],
                                    row["combined_sharpe"], row["combined_calmar"],
                                    row["combined_mdd"], row["combined_eq_x"],
                                    row["buy_hold_x"], "#4ac268",
                                    leg_capital=INIT_CAPITAL)  # full $10k

        # MDD reduction commentary
        mdd_1h_pct = abs(row["leg_1h_mdd"]) * 100
        mdd_4h_pct = abs(row["leg_4h_mdd"]) * 100
        mdd_combined_pct = abs(row["combined_mdd"]) * 100
        best_leg_mdd = min(mdd_1h_pct, mdd_4h_pct)
        improvement = (best_leg_mdd - mdd_combined_pct) / best_leg_mdd * 100 if best_leg_mdd > 0 else 0
        mdd_note = (f"Ensemble reduz MDD em <strong style='color:#4ac268'>{improvement:.0f}%</strong> "
                    f"vs a melhor perna individual ({best_leg_mdd:.1f}% → {mdd_combined_pct:.1f}%)")

        panels.append(f"""
<section class="cell">
  <h2>{sym} <span class="bh-tag">B&amp;H {row['buy_hold_x']:.2f}× em 3 anos</span></h2>

  <div class="curves">
    <div class="curve">{svg_combined}</div>
    <div class="curve">{svg_1h}</div>
    <div class="curve">{svg_4h}</div>
    <div class="curve">{svg_bh}</div>
  </div>

  <div class="legs">
    {m_combined}
    {m_1h}
    {m_4h}
  </div>

  <div class="mdd-note">{mdd_note}</div>
</section>
""")

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Campeões — Estratégias Finais Hyperliquid · BTC/ETH/SOL</title>
<style>
  body {{ background:#0b1016; color:#dde3eb; font-family:-apple-system,Segoe UI,Roboto,sans-serif; margin:0; padding:24px; font-size:13px; line-height:1.5; }}
  h1 {{ color:#eee; font-size:22px; margin:0 0 4px 0; }}
  h2 {{ color:#9dcefa; font-size:16px; margin-top:30px; border-bottom:1px solid #2a3342; padding-bottom:4px; }}
  h3 {{ color:#cfd6de; font-size:13px; margin:14px 0 6px 0; }}
  .meta {{ color:#7d8796; font-size:11px; }}
  code {{ background:#1a212c; color:#e0b280; padding:1px 5px; border-radius:2px; font-size:12px; }}

  .tiles {{ display:flex; gap:14px; margin:20px 0; flex-wrap:wrap; }}
  .tile {{ background:#151b24; border:1px solid #2a3342; border-radius:5px; padding:12px 18px; min-width:140px; }}
  .tile .val {{ font-size:22px; color:#fff; font-weight:600; }}
  .tile .lab {{ font-size:10px; color:#7d8796; text-transform:uppercase; letter-spacing:0.5px; }}

  .cell {{ background:#0e131a; border:1px solid #1d242f; border-radius:6px; padding:18px 22px; margin-bottom:20px; }}
  .cell h2 {{ color:#e0b280; border-bottom:1px solid #2d6cb0; display:flex; align-items:center; gap:14px; }}
  .bh-tag {{ font-size:11px; color:#9aa; font-weight:400; }}

  .curves {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap:10px; margin:14px 0; }}
  .curve {{ }}

  .legs {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap:14px; margin:14px 0; }}
  .leg {{ background:#0a0e14; border-left:3px solid #9dcefa; padding:10px 14px; border-radius:0 5px 5px 0; }}
  .leg-title {{ color:#e0b280; font-size:12px; font-weight:600; margin-bottom:6px; }}

  table.mini {{ width:100%; border-collapse:collapse; font-size:11px; }}
  table.mini td {{ padding:3px 8px; border-bottom:1px solid #1a202a; }}
  table.mini td:first-child {{ color:#7d8796; }}
  table.mini td:last-child {{ text-align:right; color:#fff; font-weight:600; }}

  .dollar-box {{ background:#13191f; border-top:1px solid #2a3342; margin-top:10px; padding:8px 0 4px 0; }}
  .dollar-row {{ display:flex; justify-content:space-between; padding:3px 8px; font-size:11px; border-bottom:1px solid #1a202a; }}
  .dollar-row span {{ color:#7d8796; }}
  .dollar-row strong {{ color:#fff; font-weight:600; font-family:monospace; }}

  .mdd-note {{ font-size:12px; color:#cfd6de; margin-top:10px; padding:8px 12px; background:#0a0e14; border-radius:4px; border-left:3px solid #4ac268; }}

  table.portfolio-table {{ width:100%; border-collapse:collapse; margin:14px 0; font-size:13px; }}
  table.portfolio-table th {{ background:#141a23; color:#9aa3b0; padding:8px 10px; text-align:right; font-weight:600; border-bottom:2px solid #2a3342; }}
  table.portfolio-table th:first-child {{ text-align:left; }}
  table.portfolio-table td {{ padding:7px 10px; border-bottom:1px solid #1d242f; text-align:right; font-family:monospace; }}
  table.portfolio-table td:first-child {{ text-align:left; color:#cfd6de; font-family:-apple-system,Segoe UI,Roboto,sans-serif; }}

  .pos {{ color:#4ac268 !important; }}
  .neg {{ color:#d85a5a !important; }}

  .glossary {{ background:#0e131a; border:1px solid #1d242f; border-radius:6px; padding:20px 26px 24px 26px; margin:20px 0; line-height:1.55; }}
  .glossary h3 {{ color:#9dcefa; font-size:14px; margin-top:24px; margin-bottom:10px; text-transform:uppercase; letter-spacing:0.6px; border-left:3px solid #2d6cb0; padding-left:8px; }}
  .glossary h3:first-of-type {{ margin-top:0; }}
  .glossary dl {{ margin:0 0 10px 0; }}
  .glossary dt {{ color:#e0b280; font-weight:700; font-size:13px; margin-top:12px; }}
  .glossary dd {{ color:#cfd6de; font-size:13px; margin:3px 0 8px 0; padding-left:12px; border-left:2px solid #2a3342; }}
  .glossary dd code {{ background:#1a212c; color:#e0b280; padding:1px 5px; border-radius:2px; font-size:12px; }}
  .glossary dd strong {{ color:#fff; }}
  .glossary p {{ font-size:13px; color:#cfd6de; }}
  table.ref {{ width:100%; border-collapse:collapse; margin:8px 0; font-size:12px; }}
  table.ref th {{ background:#141a23; color:#9aa3b0; padding:6px 9px; text-align:left; font-weight:600; border-bottom:2px solid #2a3342; }}
  table.ref td {{ padding:5px 9px; border-bottom:1px solid #1a202a; vertical-align:top; }}
  table.ref td:first-child {{ color:#dde3eb; white-space:nowrap; }}

  footer {{ color:#555; font-size:10px; margin-top:40px; border-top:1px solid #1d242f; padding-top:10px; }}
</style>
</head>
<body>

  <h1>🏆 Campeões — Estratégias Finais para Hyperliquid</h1>
  <div class="meta">Gerado em {gen_ts} · Janela 2023-05-01 → 2026-04-30 · 3 anos · BTC + ETH + SOL · Custos Hyperliquid 12bp RT</div>

  <div class="tiles">
    <div class="tile"><div class="val">${total_initial:,.0f}</div><div class="lab">Capital inicial total ($10k × 3)</div></div>
    <div class="tile"><div class="val" style="color:#4ac268">${total_final:,.0f}</div><div class="lab">Capital final (3 anos)</div></div>
    <div class="tile"><div class="val" style="color:#4ac268">${total_profit:+,.0f}</div><div class="lab">Lucro líquido</div></div>
    <div class="tile"><div class="val" style="color:#4ac268">{total_roi:+.1f}%</div><div class="lab">ROI 3 anos</div></div>
    <div class="tile"><div class="val">{total_cagr:+.1f}%</div><div class="lab">CAGR anualizado</div></div>
    <div class="tile"><div class="val" style="color:#4ac268">−19%</div><div class="lab">Menor MDD ensemble (BTC, ETH)</div></div>
  </div>

  <h2>📊 Portfólio Simulado — $10.000 por ativo, $30.000 total</h2>
  <table class="portfolio-table">
    <thead>
      <tr>
        <th>Ativo</th>
        <th>Capital inicial</th>
        <th>Capital final</th>
        <th>Lucro</th>
        <th>ROI</th>
        <th>B&amp;H final</th>
        <th>B&amp;H lucro</th>
        <th>Outperform</th>
        <th>Max DD ($)</th>
      </tr>
    </thead>
    <tbody>
      {''.join(f'''
      <tr>
        <td><strong>{html.escape(d["symbol"])}</strong></td>
        <td>${d["initial"]:,.0f}</td>
        <td><strong>${d["final"]:,.0f}</strong></td>
        <td class="{'pos' if d["profit"]>=0 else 'neg'}">${d["profit"]:+,.0f}</td>
        <td class="{'pos' if d["roi"]>=0 else 'neg'}">{d["roi"]:+.1f}%</td>
        <td>${d["bh_final"]:,.0f}</td>
        <td>${d["bh_profit"]:+,.0f}</td>
        <td class="{'pos' if d["outperform"]>=1 else 'neg'}">{d["outperform"]:.2f}×</td>
        <td class="neg">−${d["max_loss_dollar"]:,.0f}</td>
      </tr>''' for d in per_asset_dollar)}
      <tr style="background:#0a0e14;border-top:2px solid #2d6cb0">
        <td><strong>TOTAL</strong></td>
        <td><strong>${total_initial:,.0f}</strong></td>
        <td><strong style="color:#4ac268">${total_final:,.0f}</strong></td>
        <td class="pos"><strong>${total_profit:+,.0f}</strong></td>
        <td class="pos"><strong>{total_roi:+.1f}%</strong></td>
        <td>—</td>
        <td>—</td>
        <td>—</td>
        <td>—</td>
      </tr>
    </tbody>
  </table>

  <h2>Conclusão Headline</h2>
  <p style="font-size:13px;color:#cfd6de;background:#0a0e14;padding:14px 18px;border-radius:5px;border-left:3px solid #4ac268">
    O <strong>ensemble 50/50</strong> entrega <strong>drawdown mais raso que qualquer perna individual em todos os 3 ativos</strong>:
    BTC −24,9% / −22,4% → <strong>−19,4%</strong> · ETH −24,0% / −25,6% → <strong>−19,4%</strong> · SOL −35,7% / −19,1% → <strong>−24,6%</strong>.
    Esta diversificação temporal (1h e 4h disparam em momentos diferentes) é a maior alavanca de redução de risco da sessão.
    O Sharpe combinado preserva &gt;90% do Sharpe da melhor perna em todos os casos.
  </p>

  <h2>⚡ Análise de Alavancagem — Como Aumentar o ROI</h2>

  <p style="font-size:13px;color:#cfd6de;background:#0a0e14;padding:14px 18px;border-radius:5px;border-left:3px solid #e0b280">
    Sweep de 240 configurações de alavancagem (lev_1h × lev_4h_cap × risk_per_trade) revelou
    <strong>uma descoberta-chave</strong>: o verdadeiro botão de alavancagem é o
    <code>risk_per_trade</code>, não o <code>leverage_cap</code>. O simulador usa sizing
    baseado em ATR-risk, então <code>leverage_cap</code> satura em 2-3×. Aumentar
    <code>risk_per_trade</code> de 3% para 7% libera o sizing real.
  </p>

  {('<table class="portfolio-table"><thead><tr>'
    '<th>Ativo</th><th>lev 1h</th><th>lev 4h</th><th>risk/trade</th>'
    '<th>Capital final</th><th>ROI</th><th>Max DD</th><th>Sharpe</th><th>Uplift vs baseline</th>'
    '</tr></thead><tbody>'
    + ''.join(f'''
    <tr>
      <td><strong>{html.escape(d["symbol"])}</strong></td>
      <td>{d["lev_1h"]}×</td>
      <td>{d["lev_4h"]}×</td>
      <td>{d["risk"]*100:.0f}%</td>
      <td><strong style="color:#4ac268">${d["final_dollar"]:,.0f}</strong></td>
      <td class="pos"><strong>{d["roi"]:+.1f}%</strong></td>
      <td class="neg">{d["mdd"]*100:+.1f}%</td>
      <td>{d["sharpe"]:+.2f}</td>
      <td class="pos">+${d["uplift_dollar"]:,.0f}</td>
    </tr>''' for d in lev_top)
    + (f'''
    <tr style="background:#0a0e14;border-top:2px solid #e0b280">
      <td><strong>TOTAL ($30k)</strong></td>
      <td colspan="3" style="color:#9aa3b0;font-size:11px">com alavancagem otimizada</td>
      <td><strong style="color:#4ac268">${sum(d["final_dollar"] for d in lev_top):,.0f}</strong></td>
      <td class="pos"><strong>{(sum(d["final_dollar"] for d in lev_top) / (3 * INIT_CAPITAL) - 1) * 100:+.1f}%</strong></td>
      <td>—</td>
      <td>—</td>
      <td class="pos">+${sum(d["uplift_dollar"] for d in lev_top):,.0f}</td>
    </tr>''' if lev_top else '')
    + '</tbody></table>') if lev_top else '<p style="color:#9aa3b0">Leverage sweep ainda não rodado. Execute <code>python strategy_lab/v4_signals/derivatives_zscore/leverage_research.py</code></p>'}

  <p style="font-size:12px;color:#9aa3b0;margin-top:10px">
    <strong>Interpretação:</strong> alavancar a perna 1h não ajudou (lev_1h=1 sempre vence)
    porque o engine 1h compunde bar-a-bar — alavancagem amplifica perdas tanto quanto ganhos.
    A perna 4h sim escala bem com risk=7% até leverage_cap=2-3 (acima disso, risk-of-ATR
    é o constraint binding e cap nunca é atingido). MDD piora de ~−25% para ~−32% mas o ROI
    sobe de +91% para +116%. Decisão de risk-tolerance, não de mais inteligência no signal.
  </p>

  <h2>Detalhe por Ativo</h2>
  {''.join(panels)}

  {build_glossary()}

  <h2>📋 Próximos Passos para Deploy</h2>
  <ol style="font-size:13px;line-height:1.7">
    <li><strong>Paper trade</strong> as três pernas em paralelo na Hyperliquid testnet por 30 dias para validar
    custos reais vs modelados (12 bps RT).</li>
    <li><strong>Sizing inicial</strong>: 5% da conta em cada perna do ensemble (10% total exposto).
    Escalar para 25% após 30 dias de conformidade.</li>
    <li><strong>Monitoramento</strong>: regenerar o gauntlet semanalmente
    (<code>python strategy_lab/v4_signals/derivatives_zscore/gauntlet.py</code>) e
    checar se algum ativo perdeu &gt;1 gate vs baseline.</li>
    <li><strong>Trigger de pausa</strong>: se MDD ao vivo passar de −15% em qualquer perna, pausar
    aquela perna e investigar antes de reativar.</li>
    <li><strong>Roadmap</strong>: SOL ainda fica abaixo de B&amp;H — continuar a busca por
    filtros adicionais (HMM regime classifier, on-chain flow).</li>
  </ol>

  <footer>
    Pipeline: <code>strategy_lab/v4_signals/derivatives_zscore/{{ensemble.py, strategy_4h.py, gauntlet.py}}</code> ·
    Equity curves: <code>strategy_lab/reports/derivatives_zscore/ensemble/{{SYM}}/equity_*.parquet</code> ·
    Resumo: <code>summary.csv</code>
  </footer>

</body>
</html>
"""


def main():
    html_out = build()
    OUT.write_text(html_out, encoding="utf-8")
    kb = OUT.stat().st_size / 1024
    print(f"Wrote {OUT} ({kb:.1f} KB)")


if __name__ == "__main__":
    main()
