"""Dashboard em Português para o BTC Trend-Start Regime Detector.

Lê:     strategy_lab/reports/derivatives_zscore/regime_detector/*.csv
        strategy_lab/reports/derivatives_zscore/regime_detector/06_pine_detector.txt

Escreve: strategy_lab/reports/derivatives_zscore/regime_detector/regimedetector.html
"""
from __future__ import annotations
from pathlib import Path
import html
import math
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
RDIR = ROOT / "strategy_lab" / "reports" / "derivatives_zscore" / "regime_detector"
OUT = RDIR / "regimedetector.html"


def build_glossary() -> str:
    """All glossary content for the Portuguese regime-detector dashboard.
    Pure HTML — no Python substitutions, no curly-brace escaping needed."""
    return """
  <h2>📚 Glossário — Todos os Conceitos do Dashboard Explicados</h2>
  <div class="glossary">

    <p style="color:#9aa3b0;font-size:12px;margin-bottom:18px">
      Esta seção explica em linguagem simples cada termo, métrica e visualização que aparece neste dashboard. Foi escrita para alguém que está vendo esses conceitos pela primeira vez. Os termos estão agrupados por tema.
    </p>

    <h3>🧱 Conceitos básicos do estudo</h3>
    <dl>
      <dt>Event study</dt>
      <dd>Tipo de análise estatística que pega um EVENTO específico (aqui: "início de tendência") e mede o estado de várias variáveis nos momentos ao redor desse evento. Em vez de olhar barra por barra como em backtest, focamos só nos N momentos onde o evento aconteceu.</dd>

      <dt>Início de tendência (trend-start)</dt>
      <dd>Definido matematicamente: o preço se moveu pelo menos <strong>X%</strong> dentro de <strong>Y horas</strong>, <strong>sem nunca</strong> ter encostado em uma contra-excursão de ±Z% durante esse período. A condição de "sem nunca encostar" é o que separa um movimento limpo de um chop. Aqui usamos X=3%, Y=24h, Z=±1%.</dd>

      <dt>Contra-excursão</dt>
      <dd>Movimento na direção oposta. Se você está medindo um bull (alta), a contra-excursão é qualquer queda que o preço faça antes de atingir a meta. Limitar Z=±1% significa: o preço não pode cair mais que 1% no caminho até subir 3%.</dd>

      <dt>Forward return (retorno futuro)</dt>
      <dd>Variação do preço a partir do momento atual, olhando para frente. <code>ret_24h = close[T+24] / close[T] - 1</code>. É o que estamos tentando prever.</dd>

      <dt>Indicador líder vs defasado (leading vs lagging)</dt>
      <dd><strong>Líder</strong>: dispara ANTES do evento — útil para prever. <strong>Defasado</strong>: dispara NO ou DEPOIS do evento — útil para confirmar mas não para entrar antes do mercado. A análise de sequenciamento revela qual é qual.</dd>

      <dt>Sequenciamento</dt>
      <dd>Para cada evento, registramos o estado dos indicadores em vários momentos antes (offsets -24h, -12h, -8h, -4h, -2h, -1h, 0). A média desses estados ao longo de muitos eventos revela o "filme" que se repete antes de cada tendência.</dd>
    </dl>

    <h3>📊 Métricas estatísticas</h3>
    <dl>
      <dt>Pearson correlation (correlação de Pearson)</dt>
      <dd>Mede a relação linear entre duas variáveis. Vai de −1 a +1. <strong>+1</strong> = quando uma sobe, a outra sempre sobe na mesma proporção. <strong>0</strong> = sem relação linear. <strong>−1</strong> = sempre opostas. Em cripto a 1h, correlações entre indicador e retorno futuro raramente passam de 0,1 — é normal e ainda assim útil quando consistente.</dd>

      <dt>Z-score</dt>
      <dd><em>Z = (valor atual − média móvel 21 barras) / desvio-padrão 21 barras</em>. Mede "quão extremo o valor atual está em relação ao próprio passado recente". Z = +2 = dois desvios-padrão acima do normal recente (cauda alta). Z = −1,5 (nosso gatilho) = abaixo de cerca de 93% das observações dos últimos dias.</dd>

      <dt>σ (sigma) / desvio-padrão</dt>
      <dd>Medida de dispersão. Quanto maior σ, mais espalhados os valores. Em uma distribuição normal: 68% dos dados ficam entre −1σ e +1σ; 95% entre −2σ e +2σ; 99,7% entre −3σ e +3σ. Por isso "z &gt; +2σ" é considerado raro.</dd>

      <dt>Hit rate (taxa de acerto)</dt>
      <dd>Fração de eventos que terminaram positivos. Em um teste contrário ("aposto que vai subir quando indicador X disparar"), hit rate é a % de vezes que o preço de fato subiu nas próximas N barras.</dd>

      <dt>Mean / Median (média / mediana)</dt>
      <dd><strong>Média</strong>: soma dividida pela quantidade. Sensível a extremos. <strong>Mediana</strong>: valor do meio da lista ordenada. Mais robusta a outliers. Usamos a mediana em métricas como hold de trades para não ser distorcido por uma trade que durou muito.</dd>
    </dl>

    <h3>🔧 Os indicadores específicos do nosso pipeline</h3>
    <dl>
      <dt><code>z_lsr</code></dt>
      <dd>Z-score do Long/Short Ratio Accounts da Binance. Mede quão extremo o posicionamento da multidão está em relação ao seu próprio normal recente. Z &lt; −1,5 = contas pequenas estão abnormalmente shorts (sinal contrário de comprar). Z &gt; +1,5 = abnormalmente longs (sinal contrário de vender).</dd>

      <dt><code>z_fund</code></dt>
      <dd>Z-score do funding rate dos perpetuals. Funding positivo = longs pagam shorts (mercado eufórico comprado). Funding extremamente positivo (z &gt; +2) = topo provável. Negativo extremo = fundo provável (shorts pagando demais para manter posição).</dd>

      <dt><code>z_oi</code></dt>
      <dd>Z-score do Open Interest. Total de contratos abertos no mercado de perpetuals. OI subindo = novo dinheiro entrando posicionado. OI caindo = posições sendo fechadas.</dd>

      <dt><code>z_oi_silent</code></dt>
      <dd>OI Silencioso. Detecta quando o OI cresce significativamente (z_oi_fast &gt; 1) mas o preço não acompanha proporcionalmente. Indica novas posições sendo abertas SEM mover o preço — assinatura clássica de smart money acumulando silenciosamente.</dd>

      <dt><code>oilsr</code></dt>
      <dd>Spread de convicção: <em>oilsr = z_oi − z_lsr</em>. Mede o diferencial entre OI (tamanho real das posições) e LSR (sentimento contagem-de-contas). Positivo = mercado abrindo posições com convicção. Negativo grande = sentimento sem cobertura de posições.</dd>

      <dt><code>brigalS</code> (briga long-short)</dt>
      <dd>Diferença entre os z-scores das contas longs e das contas shorts: <em>brigalS = z(long%) − z(short%)</em>. Positivo = longs em expansão relativa. Negativo grande = shorts em expansão relativa (sinal contrário bullish).</dd>

      <dt><code>z_cb_premium</code></dt>
      <dd>Z-score do Coinbase Premium. Premium = (preço BTC na Coinbase − preço BTC na Binance) / preço Binance × 100. Coinbase premium positivo é proxy de fluxo institucional americano comprando (Coinbase é a venue dominante de TradFi nos EUA). Negativo = saída institucional.</dd>

      <dt><code>z_dom_stables</code></dt>
      <dd>Z-score da dominância de stablecoins. Capital total em stablecoins (USDT + USDC + DAI etc.) dividido pelo mercado cripto total. Subindo = capital saindo de cripto e indo para o "estacionamento" em dólar tokenizado = risk-off. Descendo = capital saindo das stables e voltando para BTC/altcoins = risk-on.</dd>

      <dt><code>cross_institutional_lead</code></dt>
      <dd>Lead institucional = Δ(USDC.D) − Δ(USDT.D). Mede se o capital institucional (USDC predomina entre instituições) está crescendo mais rápido que o capital de varejo (USDT). Positivo = smart money se posicionando antes do varejo. Foi o indicador mais forte do bear: vai de +0,19 para +0,54 antes do crash (distribuição institucional).</dd>

      <dt><code>cross_leverage_heat</code></dt>
      <dd>Calor de alavancagem = Δ(USDe + FDUSD) − Δ(USDC). Mede se a alavancagem sintética (USDe e FDUSD são usadas em yields DeFi) cresce mais que o capital institucional. Positivo grande = alavancagem subindo demais = alerta de topo.</dd>

      <dt><code>cross_risk_off</code></dt>
      <dd>Rotação defensiva. Mede se as stables totais crescem mais que seus componentes ativos. Positivo = capital fugindo para o estacionamento defensivo.</dd>

      <dt><code>cross_real_money</code></dt>
      <dd>Fluxo de dinheiro real. Compara entrada institucional + varejo vs sintético. Positivo = dinheiro REAL entrando. Negativo = alta sustentada por derivativos (frágil).</dd>

      <dt><code>z_top_lsr_count</code> e <code>z_top_lsr_sum</code></dt>
      <dd>LSR dos top traders. <strong>count</strong>: ratio por NÚMERO de contas dos top traders (1 baleia = 1 conta). <strong>sum</strong>: ratio por TAMANHO DE POSIÇÃO. Diferentes do LSR geral — capturam o que os traders maiores estão fazendo, que historicamente é mais preditivo.</dd>

      <dt><code>z_taker_ratio</code></dt>
      <dd>Z-score da razão de volume taker buy / taker sell. Quem tira liquidez (taker) é quem está disposto a pagar mais para entrar agora. Z alto = compradores agressivos dominando. Z baixo = vendedores agressivos dominando. Proxy para "quem tem pressa".</dd>

      <dt><code>rsi_14</code> (Relative Strength Index)</dt>
      <dd>Indicador clássico de momentum (0–100). RSI &lt; 30 = sobrevendido (potencial alta). RSI &gt; 70 = sobrecomprado (potencial queda). Aqui foi incluído mais como controle do que como sinal — mostrou quase nenhuma diferença antes de eventos (média ~50 em todos os offsets).</dd>

      <dt><code>atr_pct</code></dt>
      <dd>Average True Range normalizado pelo preço. Mede volatilidade média horária. ATR alto = barras grandes (mais movimento). ATR baixo = mercado calmo (mais previsível para mean reversion).</dd>
    </dl>

    <h3>🌍 Filtros de regime macro</h3>
    <dl>
      <dt>Regime macro</dt>
      <dd>Estado geral do mercado num horizonte longo. Aqui usamos 3 categorias: <code>trending_up</code> (BTC acima da EMA 200d), <code>below_ema50</code> (entre EMA 200d e EMA 50d, zona de transição), <code>trending_down</code> (BTC abaixo da EMA 200d). Indicadores curtos costumam funcionar de modo OPOSTO em regimes diferentes — daí a importância do filtro.</dd>

      <dt>EMA 200d (Exponential Moving Average de 200 dias)</dt>
      <dd>Média móvel exponencial de 200 dias. Pondera mais os dias recentes. É o filtro de tendência mais clássico do mercado: preço acima = bull market estrutural, abaixo = bear market estrutural. Nos backtests vimos que adicionar este filtro corta drawdowns pela metade no BTC.</dd>

      <dt>Sign flip (inversão de sinal)</dt>
      <dd>Quando o mesmo indicador tem correlação POSITIVA com o retorno futuro em um regime e NEGATIVA em outro. Exemplo: <code>z_lsr</code> tem corr +0,08 em <code>below_ema50</code> mas −0,02 em <code>trending_up</code> — o mesmo gatilho funciona em direções opostas! Isso significa: se você usar o indicador sem prefixar com filtro de regime, em metade dos casos vai operar contra a estrutura.</dd>

      <dt>Low-vol regime</dt>
      <dd>Vol realizada 30d abaixo da mediana móvel 90d. Mean reversion (que é o que esta estratégia explora) funciona melhor em mercados calmos: em caos, "extremos" não são realmente extremos. Em calma, posicionamento extremo se destaca.</dd>
    </dl>

    <h3>🛠 Termos da implementação</h3>
    <dl>
      <dt>Pine Script</dt>
      <dd>Linguagem de scripting do TradingView para criar indicadores e estratégias. O detector gerado nesta análise é Pine v6, pronto para copiar/colar no TradingView e visualizar os triggers ao vivo no gráfico do BTC.</dd>

      <dt>Threshold (gatilho)</dt>
      <dd>Valor de corte. Aqui os thresholds do detector são gerados automaticamente: pegamos a média do indicador no momento do evento (offset 0), dividimos por 2 e usamos como o limite. Isso captura quando o indicador está "metade do caminho" rumo ao estado típico de evento.</dd>

      <dt>Heatmap</dt>
      <dd>Tabela em que a cor de cada célula codifica o valor. Verde = positivo, vermelho = negativo, intensidade = magnitude. Permite ver padrões de relevância em uma matriz grande de uma só olhada.</dd>

      <dt>Resample (reamostragem)</dt>
      <dd>Mudança de granularidade temporal. Aqui usamos dados de 5min agregados para 1h pegando o último valor de cada hora. Alinha tudo num grid horário consistente.</dd>
    </dl>

    <h3>🎓 Régua de bolso — interpretando os números</h3>
    <p>
      Para cada métrica deste dashboard, aqui está uma régua aproximada do que é "bom":
    </p>
    <dl>
      <dt>Correlação |Pearson|</dt>
      <dd>Em cripto a 1h: <strong>&lt; 0,03</strong> = ruído, <strong>0,03 a 0,07</strong> = sinal fraco mas usável em ensemble, <strong>0,07 a 0,15</strong> = sinal forte para essa escala, <strong>&gt; 0,15</strong> = excepcional.</dd>

      <dt>n eventos (sample size)</dt>
      <dd><strong>&lt; 100</strong> = estatísticas instáveis, <strong>100 a 500</strong> = aceitável, <strong>&gt; 500</strong> = robusto. Aqui temos 1.235 bull events e 1.059 bear events — bom tamanho amostral.</dd>

      <dt>Sequência média (offset analysis)</dt>
      <dd>Indicador é "líder" se a média MUDA visivelmente entre offsets distantes (ex: −24h) e próximos (0). Indicador é "ruído" se a média for praticamente igual em todos os offsets.</dd>
    </dl>

    <p style="color:#9aa3b0;font-size:11px;margin-top:18px">
      <strong>Veredito final:</strong> o detector gerado é uma TELA MULTI-FATOR — usa-se para destacar momentos de alta probabilidade no gráfico, não como gatilho automático isolado. As correlações são pequenas mas a sequência é consistente, o filtro de regime macro é obrigatório, e os indicadores que medem fluxo de stablecoins (<code>z_dom_stables</code>, <code>cross_institutional_lead</code>) são os mais valiosos por serem estáveis entre regimes.
    </p>

  </div>
"""


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


def color_by_corr(c, max_abs=0.10):
    """Background color for a correlation cell."""
    try:
        v = float(c)
        if pd.isna(v) or not math.isfinite(v):
            return "#1a1f26"
    except Exception:
        return "#1a1f26"
    a = min(1.0, abs(v) / max_abs)
    if v >= 0:
        return f"rgba(31,157,85,{a:.2f})"
    return f"rgba(194,58,58,{a:.2f})"


def color_by_mean(v, max_abs=0.5):
    """Background for sequencing/zone-mean cell."""
    try:
        f = float(v)
        if pd.isna(f) or not math.isfinite(f):
            return "#1a1f26"
    except Exception:
        return "#1a1f26"
    a = min(1.0, abs(f) / max_abs)
    if f >= 0:
        return f"rgba(31,157,85,{a:.2f})"
    return f"rgba(194,58,58,{a:.2f})"


def render_label_sweep(df: pd.DataFrame) -> str:
    rows = []
    for _, r in df.iterrows():
        bull_pct = float(r["bull_rate_pct"])
        bear_pct = float(r["bear_rate_pct"])
        is_chosen = (r["X"] == 0.03 and r["Y"] == 24 and r["Z"] == 0.010)
        cls = ' class="chosen"' if is_chosen else ""
        rows.append(
            f'<tr{cls}><td>{r["X"]*100:.0f}%</td><td>{int(r["Y"])}h</td>'
            f'<td>±{r["Z"]*100:.1f}%</td>'
            f'<td>{int(r["n_bull"])}</td><td>{int(r["n_bear"])}</td>'
            f'<td>{bull_pct:.2f}%</td><td>{bear_pct:.2f}%</td></tr>'
        )
    return (
        '<table class="data"><thead><tr>'
        '<th>X (movimento)</th><th>Y (janela)</th><th>Z (contra-excursão máx)</th>'
        '<th>Eventos bull</th><th>Eventos bear</th>'
        '<th>Taxa bull</th><th>Taxa bear</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>'
        '<div class="note">Definição escolhida (destacada): X=3%, Y=24h, Z=±1,0%.</div>'
    )


def render_correlations(df: pd.DataFrame) -> str:
    """Pivot indicator × horizon, color cells by sign+magnitude."""
    pivot = df.pivot_table(index="indicator", columns="horizon_h", values="pearson_corr")
    pivot["abs_max"] = pivot.abs().max(axis=1)
    pivot = pivot.sort_values("abs_max", ascending=False).drop(columns=["abs_max"])
    horizons = sorted(c for c in pivot.columns if isinstance(c, (int, float)))

    head = "<tr><th>Indicador</th>" + "".join(f"<th>{h}h</th>" for h in horizons) + "</tr>"
    body = []
    for ind, row in pivot.iterrows():
        cells = []
        for h in horizons:
            v = row[h]
            bg = color_by_corr(v, max_abs=0.10)
            cells.append(f'<td style="background:{bg}" title="{ind} @ {h}h">{fmt_num(v, 3, sign=True)}</td>')
        body.append(f"<tr><td><code>{html.escape(ind)}</code></td>{''.join(cells)}</tr>")
    return f'<table class="heatmap"><thead>{head}</thead><tbody>{"".join(body)}</tbody></table>'


def render_zone_means(df: pd.DataFrame) -> str:
    pivot = df.pivot_table(index="indicator", columns="zone", values="mean_fwd_ret_pct")
    cols = ["<-2σ", "-2 to -1", "-1 to +1", "+1 to +2", ">+2σ"]
    cols = [c for c in cols if c in pivot.columns]
    pivot = pivot[cols]

    head = "<tr><th>Indicador</th>" + "".join(f"<th>{c}</th>" for c in cols) + "</tr>"
    body = []
    for ind, row in pivot.iterrows():
        cells = []
        for c in cols:
            v = row[c]
            bg = color_by_mean(v, max_abs=0.30)
            cells.append(
                f'<td style="background:{bg}" title="zona {c}">{fmt_num(v, 2, sign=True)}%</td>'
            )
        body.append(f"<tr><td><code>{html.escape(ind)}</code></td>{''.join(cells)}</tr>")
    return f'<table class="heatmap"><thead>{head}</thead><tbody>{"".join(body)}</tbody></table>'


def render_sequencing(df: pd.DataFrame, label: str) -> str:
    sub = df[df["label"] == label]
    pivot = sub.pivot_table(index="indicator", columns="offset_h", values="mean")
    # filter inf / nan rows
    finite_mask = pivot.replace([np.inf, -np.inf], np.nan).notna().all(axis=1)
    pivot = pivot[finite_mask]
    pivot["abs_at_zero"] = pivot.get(0, pd.Series(0, index=pivot.index)).abs()
    pivot = pivot.sort_values("abs_at_zero", ascending=False).drop(columns=["abs_at_zero"])
    offsets = sorted(pivot.columns)

    head = "<tr><th>Indicador</th>" + "".join(f"<th>{o:+d}h</th>" for o in offsets) + "</tr>"
    body = []
    for ind, row in pivot.iterrows():
        cells = []
        for o in offsets:
            v = row[o]
            # use a different scale for rsi_14 (centered around 50)
            if ind == "rsi_14":
                bg = color_by_mean(float(v) - 50, max_abs=10)
                cells.append(f'<td style="background:{bg}">{fmt_num(v, 1)}</td>')
            else:
                bg = color_by_mean(v, max_abs=0.5)
                cells.append(f'<td style="background:{bg}">{fmt_num(v, 3, sign=True)}</td>')
        body.append(f"<tr><td><code>{html.escape(ind)}</code></td>{''.join(cells)}</tr>")

    return f'<table class="heatmap"><thead>{head}</thead><tbody>{"".join(body)}</tbody></table>'


def render_macro_split(df: pd.DataFrame) -> str:
    """Show indicator × regime, flagging sign flips in red border."""
    # pivot: rows=indicator, cols=(regime, horizon)
    horizons = sorted(df["horizon_h"].unique())
    regimes = sorted(df["regime"].unique())
    pivot = df.pivot_table(index="indicator", columns=["regime", "horizon_h"],
                            values="pearson_corr")
    indicators = pivot.index

    # Header: regime spans, then horizons
    head1 = "<tr><th rowspan='2'>Indicador</th>"
    for reg in regimes:
        head1 += f"<th colspan='{len(horizons)}'>{html.escape(reg)}</th>"
    head1 += "<th rowspan='2'>Inverte sinal?</th></tr>"
    head2 = "<tr>" + "".join(f"<th>{h}h</th>" for _ in regimes for h in horizons) + "</tr>"

    body = []
    for ind in indicators:
        cells = []
        signs = []
        for reg in regimes:
            for h in horizons:
                v = pivot.loc[ind].get((reg, h), np.nan)
                bg = color_by_corr(v, max_abs=0.30)
                cells.append(f'<td style="background:{bg}">{fmt_num(v, 3, sign=True)}</td>')
                if pd.notna(v) and math.isfinite(float(v)) and abs(float(v)) > 0.02:
                    signs.append(1 if float(v) > 0 else -1)
        flip = (len(set(signs)) > 1) if signs else False
        flag = '<span class="flip">⚠ inverte</span>' if flip else '<span class="stable">estável</span>'
        body.append(f"<tr><td><code>{html.escape(ind)}</code></td>{''.join(cells)}<td>{flag}</td></tr>")

    return f'<table class="heatmap"><thead>{head1}{head2}</thead><tbody>{"".join(body)}</tbody></table>'


def build():
    sweep = pd.read_csv(RDIR / "01_label_sweep.csv")
    corrs = pd.read_csv(RDIR / "02_correlations.csv")
    zones = pd.read_csv(RDIR / "03_zone_means.csv")
    seq = pd.read_csv(RDIR / "04_sequencing.csv")
    macro = pd.read_csv(RDIR / "05_macro_regime_split.csv")
    pine_path = RDIR / "06_pine_detector.txt"
    pine_code = pine_path.read_text(encoding="utf-8") if pine_path.exists() else ""

    # Tiles
    n_bull = int(sweep[(sweep["X"] == 0.03) & (sweep["Y"] == 24) & (sweep["Z"] == 0.010)]["n_bull"].iloc[0])
    n_bear = int(sweep[(sweep["X"] == 0.03) & (sweep["Y"] == 24) & (sweep["Z"] == 0.010)]["n_bear"].iloc[0])
    top_corr = corrs.assign(abs_corr=corrs["pearson_corr"].abs()).nlargest(1, "abs_corr").iloc[0]

    # Top 5 leading indicators per side (for narrative)
    def top_lead(side: str, top: int = 5):
        sub = seq[(seq["label"] == side) & (seq["offset_h"] == 0)].copy()
        sub = sub[np.isfinite(sub["mean"])]
        sub["abs_mean"] = sub["mean"].abs()
        return sub.sort_values("abs_mean", ascending=False).head(top)

    bull_lead = top_lead("bull")
    bear_lead = top_lead("bear")

    # Macro flip count
    macro_pivot = macro.pivot_table(index="indicator", columns=["regime", "horizon_h"],
                                     values="pearson_corr")
    n_flips = 0
    for ind in macro_pivot.index:
        signs = []
        for col in macro_pivot.columns:
            v = macro_pivot.loc[ind, col]
            if pd.notna(v) and math.isfinite(float(v)) and abs(float(v)) > 0.02:
                signs.append(1 if float(v) > 0 else -1)
        if signs and len(set(signs)) > 1:
            n_flips += 1

    gen_ts = pd.Timestamp.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    GLOSSARY_PLACEHOLDER = build_glossary()

    # Bull/bear narrative tiles
    bull_lead_html = "".join(
        f'<li><code>{html.escape(r["indicator"])}</code> '
        f'mean={fmt_num(r["mean"], 3, sign=True)}</li>'
        for _, r in bull_lead.iterrows()
    )
    bear_lead_html = "".join(
        f'<li><code>{html.escape(r["indicator"])}</code> '
        f'mean={fmt_num(r["mean"], 3, sign=True)}</li>'
        for _, r in bear_lead.iterrows()
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Detector de Regime — Início de Tendência BTC · Event Study 3 Anos</title>
<style>
  body {{ background:#0b1016; color:#dde3eb; font-family:-apple-system,Segoe UI,Roboto,sans-serif; margin:0; padding:24px; font-size:13px; line-height:1.5; }}
  h1 {{ color:#eee; font-size:22px; margin:0 0 4px 0; }}
  h2 {{ color:#9dcefa; font-size:15px; margin-top:30px; border-bottom:1px solid #2a3342; padding-bottom:4px; text-transform:uppercase; letter-spacing:0.6px; }}
  h3 {{ color:#cfd6de; font-size:13px; margin:16px 0 6px 0; }}
  .meta {{ color:#7d8796; font-size:11px; }}
  code {{ background:#1a212c; color:#e0b280; padding:1px 5px; border-radius:2px; font-size:12px; }}

  .tiles {{ display:flex; gap:14px; margin:20px 0; flex-wrap:wrap; }}
  .tile {{ background:#151b24; border:1px solid #2a3342; border-radius:5px; padding:12px 18px; min-width:140px; }}
  .tile .val {{ font-size:22px; color:#fff; font-weight:600; }}
  .tile .lab {{ font-size:10px; color:#7d8796; text-transform:uppercase; letter-spacing:0.5px; }}

  .columns {{ display:grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap:18px; }}
  .panel {{ background:#0e131a; border:1px solid #1d242f; border-radius:6px; padding:14px 18px; }}
  .panel h3 {{ margin-top:0; }}

  table {{ border-collapse:collapse; width:100%; font-size:11px; margin-top:6px; }}
  table.data th, table.data td {{ padding:5px 8px; border-bottom:1px solid #1d242f; text-align:right; }}
  table.data th {{ background:#141a23; color:#9aa3b0; font-weight:600; }}
  table.data td:first-child, table.data th:first-child {{ text-align:left; }}
  table.data tr.chosen td {{ background:rgba(31,157,85,0.20); color:#fff; font-weight:600; }}

  table.heatmap {{ font-size:10px; }}
  table.heatmap th {{ background:#141a23; color:#9aa3b0; padding:4px 6px; font-weight:600; text-align:center; }}
  table.heatmap td {{ padding:3px 6px; text-align:right; color:#dde3eb; border-bottom:1px solid #1a202a; }}
  table.heatmap td:first-child {{ text-align:left; }}

  .note {{ color:#7d8796; font-size:10px; margin-top:6px; font-style:italic; }}

  pre.pine {{ background:#0a0e14; border:1px solid #1d242f; border-radius:5px; padding:12px; font-size:11px; color:#cfd6de; overflow-x:auto; max-height:600px; }}

  .lead-list {{ list-style:none; padding:0; margin:6px 0; font-size:12px; }}
  .lead-list li {{ padding:3px 0; border-bottom:1px solid #1d242f; }}
  .lead-list code {{ color:#9dcefa; }}

  .flip {{ color:#d85a5a; font-weight:600; font-size:10px; }}
  .stable {{ color:#7d8796; font-size:10px; }}
  .pos {{ color:#4ac268; }}
  .neg {{ color:#d85a5a; }}

  .playbook {{ background:#0a0e14; border-left:3px solid #2d6cb0; padding:12px 16px; margin:14px 0; font-size:12px; }}
  .playbook strong {{ color:#9dcefa; }}

  footer {{ color:#555; font-size:10px; margin-top:40px; border-top:1px solid #1d242f; padding-top:10px; }}

  .glossary {{ background:#0e131a; border:1px solid #1d242f; border-radius:6px; padding:20px 26px 24px 26px; margin:20px 0; line-height:1.55; }}
  .glossary h3 {{ color:#9dcefa; font-size:14px; margin-top:24px; margin-bottom:10px; text-transform:uppercase; letter-spacing:0.6px; border-left:3px solid #2d6cb0; padding-left:8px; }}
  .glossary h3:first-of-type {{ margin-top:0; }}
  .glossary dl {{ margin:0 0 10px 0; }}
  .glossary dt {{ color:#e0b280; font-weight:700; font-size:13px; margin-top:12px; }}
  .glossary dd {{ color:#cfd6de; font-size:13px; margin:3px 0 8px 0; padding-left:12px; border-left:2px solid #2a3342; }}
  .glossary dd code {{ background:#1a212c; color:#e0b280; padding:1px 5px; border-radius:2px; font-size:12px; }}
  .glossary dd em {{ color:#9aa3b0; font-style:italic; }}
  .glossary dd strong {{ color:#fff; }}
  .glossary p {{ font-size:13px; color:#cfd6de; }}
</style>
</head>
<body>

  <h1>Detector de Regime — Início de Tendência BTC · Event Study 3 Anos</h1>
  <div class="meta">Gerado em {gen_ts} · Janela 2023-05-01 → 2026-04-29 · 5.160 barras horárias · BTCUSDT</div>

  <div class="tiles">
    <div class="tile"><div class="val">{n_bull:,}</div><div class="lab">Eventos bull</div></div>
    <div class="tile"><div class="val">{n_bear:,}</div><div class="lab">Eventos bear</div></div>
    <div class="tile"><div class="val">3% / 24h / ±1%</div><div class="lab">Definição escolhida</div></div>
    <div class="tile"><div class="val">{fmt_num(top_corr['pearson_corr'], 3, sign=True)}</div><div class="lab">Maior corr ({html.escape(top_corr['indicator'])} @ {int(top_corr['horizon_h'])}h)</div></div>
    <div class="tile"><div class="val" style="color:#d85a5a">{n_flips}</div><div class="lab">Indicadores que invertem sinal entre regimes</div></div>
  </div>

  <h2>O Playbook — Sequência Média do Evento</h2>
  <div class="playbook">
    <strong>Início bull (média 24h antes do movimento):</strong>
    <code>cross_institutional_lead</code> sobe (smart money entrando em stables) →
    <code>oilsr</code> sobe (convicção de OI se forma) →
    <code>z_oi_silent</code> faz pico ~4h antes (acumulação silenciosa) →
    <code>brigalS</code> e <code>z_lsr</code> despencam nas últimas 12h (varejo capitulando) →
    PREÇO SOBE.
  </div>
  <div class="playbook" style="border-left-color:#c23a3a">
    <strong>Início bear (média 24h antes do movimento):</strong>
    <code>cross_institutional_lead</code> dispara (+0,19 → +0,54 — distribuição institucional) →
    <code>oilsr</code> reverte →
    <code>z_lsr</code> e <code>brigalS</code> sobem (varejo entrando comprado) →
    <code>z_top_lsr_count</code> sobe (top traders abrindo shorts) →
    PREÇO CAI.
  </div>

  <div class="columns">
    <div class="panel">
      <h3>🐂 Top 5 Indicadores Líderes do Lado Bull (estado médio @ evento)</h3>
      <ul class="lead-list">{bull_lead_html}</ul>
    </div>
    <div class="panel">
      <h3>🐻 Top 5 Indicadores Líderes do Lado Bear (estado médio @ evento)</h3>
      <ul class="lead-list">{bear_lead_html}</ul>
    </div>
  </div>

  <h2>1 · Sweep da Definição de Label — Escolhendo X / Y / Z</h2>
  <p style="color:#9aa3b0;font-size:12px">
    Início de tendência = preço se move ≥X% em até Y horas <em>sem nunca encostar</em> em uma contra-excursão de ±Z%. Z menor → movimentos mais limpos mas menos eventos. Escolhemos a célula que maximiza a contagem de eventos mantendo mercados choppy excluídos.
  </p>
  {render_label_sweep(sweep)}

  <h2>2 · Heatmap de Correlação — Indicador × Horizonte Futuro</h2>
  <p style="color:#9aa3b0;font-size:12px">
    Correlação de Pearson de cada indicador com o retorno futuro contínuo (sem thresholding). Verde = preditivo positivo (indicador maior → retorno futuro maior), vermelho = negativo. Correlações em cripto a 1h são naturalmente pequenas; <code>z_dom_stables</code> é o melhor preditor linear individual.
  </p>
  {render_correlations(corrs)}

  <h2>3 · Médias por Zona — Retorno Futuro Condicional por Faixa de ±σ (24h)</h2>
  <p style="color:#9aa3b0;font-size:12px">
    Para cada indicador, particionamos em 5 zonas pela distância σ e medimos o retorno médio 24h à frente. Isso revela sweet spots NÃO-lineares que a correlação pura não captura.
  </p>
  {render_zone_means(zones)}

  <h2>4 · Sequenciamento — Quem Dispara Quando (o "playbook")</h2>
  <p style="color:#9aa3b0;font-size:12px">
    Para cada início de tendência confirmado (bull/bear), tiramos um snapshot do estado médio de cada indicador nos offsets {{−24h, −12h, −8h, −4h, −2h, −1h, 0}}. Indicadores ordenados por |média no offset 0|. Observe como os indicadores líderes (linhas de cima) se movem ANTES do evento vs indicadores defasados que confirmam NO evento.
  </p>

  <h3>🐂 Início de tendência bull (n={n_bull:,})</h3>
  {render_sequencing(seq, "bull")}

  <h3>🐻 Início de tendência bear (n={n_bear:,})</h3>
  {render_sequencing(seq, "bear")}

  <h2>5 · Estabilidade no Regime Macro — Onde os Indicadores Invertem</h2>
  <p style="color:#9aa3b0;font-size:12px">
    Mesma métrica de correlação, particionada por regime macro: <code>trending_up</code> (BTC &gt; EMA 200d), <code>below_ema50</code> (entre EMA 200d e EMA 50d), <code>trending_down</code> (BTC &lt; EMA 200d). Se um indicador muda de sinal entre regimes, ele não pode ser usado isoladamente — exige o filtro de regime como prefixo obrigatório.
  </p>
  {render_macro_split(macro)}
  <div class="note"><strong style="color:#d85a5a">{n_flips} indicadores</strong> invertem sinal entre regimes — filtro macro é obrigatório.</div>

  <h2>6 · Detector Pine Script Gerado</h2>
  <p style="color:#9aa3b0;font-size:12px">
    Gerado automaticamente a partir dos thresholds de sequenciamento (cada gatilho dispara quando um indicador cruza metade da sua média observada no offset 0). Requer filtro macro (<code>trending_up</code> + <code>low_vol_regime</code> para bull; <code>not trending_up</code> para bear) E ≥3 de 5 indicadores líderes alinhados.
  </p>
  <pre class="pine">{html.escape(pine_code)}</pre>

  <h2>7 · Limitações Honestas</h2>
  <ul style="font-size:12px">
    <li>As correlações absolutas são <strong>pequenas</strong> (máx +0,07 para <code>z_dom_stables</code> @ 48h). Típico para dados ruidosos de cripto a 1h — útil como filtro multi-fator, não como gatilho único.</li>
    <li><code>cross_real_money</code> e <code>cross_leverage_heat</code> contêm valores <code>±inf</code> por divisão por zero a montante nos Δ de stablecoin. Excluídos do output Pine. Solução: clipar denominadores em <code>compute_zscores.py</code> e re-rodar.</li>
    <li>A definição de label (3% / 24h / ±1%) foi escolhida pelo equilíbrio entre quantidade de eventos e limpeza do sinal. Outras células do sweep enfatizariam outros trade-offs (mais eventos = mais ruído; eventos mais limpos = menos para aprender).</li>
    <li>Esta é uma análise <strong>linear / contemporânea</strong>. Modelos não-lineares (gradient boosting, classificador HMM de regime) provavelmente trariam estrutura mais forte — fica para v2.</li>
    <li>Apenas BTC. O mesmo pipeline pode rodar nos painéis ETH/SOL trocando o símbolo em <code>load_btc()</code>.</li>
  </ul>

  {GLOSSARY_PLACEHOLDER}

  <footer>
    Fonte: <code>strategy_lab/v4_signals/derivatives_zscore/regime_detector_research.py</code> ·
    CSVs em <code>strategy_lab/reports/derivatives_zscore/regime_detector/</code> ·
    Pine Script: <code>06_pine_detector.txt</code>
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
