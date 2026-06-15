# ETH 5m sleeves — comparação período completo, metodologia corrigida (2026-06-09)

**Correção de processo** (erros da 1ª passada, agora sanados):
1. Contabilidade verificada: shadow `pnl_usd` = curva **fee07 winner-only**, idêntica ao
   backtest (**260/260 fires reconciliados exatos**). Sem artefato contábil.
2. Sem fatias de 5 dias (ruído ±$0.3-0.5/tr no $/tr): backtest = período in-sample COMPLETO
   (Apr24→May26, universo com colunas de gate de produção); shadow = janela OOS COMPLETA
   (May29→Jun9, engine de produção).
3. Bootstrap CI95 nos dois lados + **DSR (ml4t, n_trials=25** = sleeves do sweep).
4. A "refutação por adjacência" anterior usou uma cauda quente (May21-26: v8 +1.265 vs +0.925
   full) — viés de regime meu, retirada.

Script: `strategy_lab/directional/eth5m_full_period_proper_2026_06_09.py` (+ ext