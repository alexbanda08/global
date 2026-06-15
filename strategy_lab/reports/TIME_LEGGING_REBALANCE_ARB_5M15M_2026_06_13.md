# Análise Quant — Arbitragem temporal de rebalanceamento (comprar as 2 pontas < $1) em mercados up/down 5m/15m

**Data:** 2026-06-13
**Base teórica:** `2508.03474v1.md` (Saguillo et al., "Unravelling the Probabilistic Forest") — *Market Rebalancing Arbitrage* / single-condition arb.
**Ancoragem empírica do projeto:** decode da carteira `0xce25e214` (TAKER PAIR-ARB), `0xb945945d` (maker two-sided), `project_synthetic_book_marginal`.
**Veredito honesto:** estruturalmente difícil como descrito; o alpha NÃO está em achar `sum_ask < 1` simultâneo (raro aqui), está no **legging assíncrono ao longo do tempo da janela** + captura de rebate como maker. Tudo abaixo é hipótese pré-registrável, não edge confirmado.

---

## 1. O que o artigo prova — e por que NÃO transfere direto

O artigo (Def. 3, §6.1, §7.2) encontra que **todas** as oportunidades single-condition observadas são **LONG** (`ask_YES + ask_NO < 1`), com **sum mediano ≈ $0.60** — ineficiência enorme. Isso é tentador: parece que "comprar as 2 pontas barato" é abundante.

**Mas o universo do artigo é o oposto dos nossos mercados:**

| Dimensão | Artigo (eleições/esportes) | Nossos up/down 5m/15m |
|---|---|---|
| Liquidez | Baixa, esporádica | Market-made contínuo, denso |
| Resolução | Dias/meses | 5–15 min |
| Filtro deles | exclui token > $0.95, exige `\|1−sum\|>0.02` | janela inteira é "incerteza" por design |
| `sum_ask` típico | < 1 (sub-precificado) | **> 1 (overround do MM)** |

**Evidência do projeto que mata a versão ingênua (GROUND-TRUTH):** decode `ce25` mediu nos slugs BTC/ETH/SOL/XRP 5m+15m:
- `sum_ask` **mediano = 1.041 (+4.1% overround)**
- **apenas 35% dos slugs** têm `sum_ask < 1.0` em algum momento
- como **taker**, fee `0.07·p·(1−p)` winner-only (~1.7%) **come o edge** → `ce25` é vencedor histórico (+$300k) mas o **DEPLOY foi NO** (taker fees ~1.7% vs ~4% edge disponível só em 35% dos slugs).

→ **A arb pura "2 asks somam < $1 agora, compro os dois como taker" existe em ≤35% dos slugs e é negativa após fee.** Não é o caminho.

---

## 2. Onde *poderia* existir alpha — mapa de hipóteses

O pedido ("comprar **ao longo do tempo** as 2 pontas por < $1") é, na verdade, a chave: relaxar a exigência de **simultaneidade**. Isso converte uma arb atômica (que não existe) em **duas execuções de timing** dentro da janela. Quatro fontes candidatas:

**H-A. Janela transitória de abertura (0–60s).** Book fino logo após o slug abrir; um lado lagga o oráculo → `sum_ask` cai abaixo de 1 por segundos. `ce25` dispara 78% no 1º minuto — consistente com explorar essa janela. *Risco: profundidade rasa, sumiço rápido.*

**H-B. Repricing assimétrico intrawindow.** Oráculo move (Chainlink/Pyth Lazer lidera 1.3–1.8s); o lado que vira favorito reprecifica antes do underdog → `ask_up + ask_dn` momentaneamente < 1 (cross-token). *Já temos Lazer δ A/B em shadow — mesma família de sinal.*

**H-C. Legging assíncrono (o núcleo da estratégia).** NÃO exigir `sum < 1` num único instante. Comprar a perna **A** quando A está barata (ex. ask_up = 0.46 num dip), e a perna **B** quando B está barata (ask_dn = 0.50 mais tarde), tal que **custo acumulado das duas pernas < $1** ao fim da janela. Como up/down é uma *single condition* (YES/NO complementares), **possuir 1 Up + 1 Dn garante payoff de exatamente $1 na resolução** → lucro = `1 − custo_total`.

**H-D. Maker two-sided abaixo do mid (estilo b945).** Em vez de pagar o ask, **postar bids GTC** dos dois lados a preços cuja soma-alvo seja ~0.96. Vira maker: fee $0, **rebate como receita**, captura o overround em vez de pagá-lo. *Caveat forte:* o queue-sim do `b945` deu **72–76% de fill mas TODAS as políticas ≤ 0** (join-bid −0.05 SIG-NEG, ladders −0.24..−0.41). A única variante não-refutada = **quoting oracle-gated** (postar só quando |rtds_ret5| elevado).

---

## 3. Por que o caminho TAKER morre (quantificação)

Para fechar 1 Up + 1 Dn pagando o ask:
```
custo = ask_up + ask_dn  (overround mediano 1.041)
fee_winner ≈ 0.07 · p_win · (1 − p_win)   # só na perna vencedora, winner-only
payoff = 1.00 (garantido)
PnL = 1 − custo − fee ≈ 1 − 1.041 − 0.017 ≈ −0.058  por par (mediano)
```
Negativo no caso mediano. Só os ~35% de slugs com `sum_ask<1` dão chance, e mesmo lá o min costuma ser raso/curto. **Taker simultâneo = descartado.**

---

## 4. Estrutura proposta — **"Time-Legging Rebalance" (TLR)**

Maker-first, legging dinâmico, com gate pré-registrado de margem. Objetivo: terminar cada slug com 1 Up + 1 Dn por **custo_total < 0.97** (margem > fee+slippage).

### 4.1 Estado por slug (atualizado a cada update do BookMirror, ~10Hz)
- `ask_up(t), ask_dn(t), bid_up(t), bid_dn(t)` (L25 nativo, **`subsample_1hz=False`**).
- `filled_up_px, filled_dn_px` (preço das pernas já preenchidas), `filled_up_qty, filled_dn_qty`.
- `remaining_budget_sum = 0.97 − (filled legs já pagas, por share emparelhada)`.

### 4.2 Política de cotação (maker, H-D + H-C)
Para o lado ainda não preenchido, postar **bid GTC** a:
```
target_bid_X = remaining_budget_sum − best_bid_other_side_or_filled
```
ou seja, só pago pela perna que falta o que mantém `custo_par < 0.97`. Dois sub-modos:
- **Passivo (default):** bids dos dois lados simultâneos abaixo do mid; sum-alvo 0.96. Captura rebate + overround.
- **Oracle-gated (única variante b945 não-refutada):** só ativa/aperta as cotações quando `|rtds_ret5|` (ou Lazer δ) está elevado — momento em que o repricing assimétrico (H-B) cria a perna barata.

### 4.3 Gestão da perna solta (o risco central — non-atomic)
Se a perna A preenche e B não dentro de `T_hedge` (ex. 20s):
- **Opção 1 (fechar):** cancelar B, vender A no book (taker) → realizar pequena perda/lucro de timing. Evita exposição direcional.
- **Opção 2 (completar como taker):** se `ask_B` ainda deixa `custo_par < 0.97`, pagar o ask de B e travar o par. Caso contrário, Opção 1.
- **Nunca** segurar perna solta até a resolução sem gate — isso é aposta direcional (e a perna que ficou barata costuma ser a que vai PERDER → adverse selection).

### 4.4 Exit
- Par completo (`custo_par < 0.97`) → **segurar até resolução** (payoff $1 garantido). Sem time-sell, sem TP.
- Par incompleto em `T_window − buffer` → forçar Opção 1/2 acima.

### 4.5 Sizing
- $1–$5 por par no shadow/live-probe (mesma escala dos probes ce25/b945).
- one-shot por slug.

---

## 5. Riscos (ranqueados)

1. **Non-atomic legging risk** — perna solta vira direcional. Mitigado por §4.3, mas o hedge custa edge.
2. **Adverse selection na perna barata** — o lado que afunda barato é frequentemente o lado perdedor; comprá-lo "barato" é comprar o lixo. *Este é o assassino silencioso; mensurar markout pós-fill por perna.*
3. **Queue/fill como maker** — `b945` queue-sim: 72–76% fill mas PnL ≤0 em todas as políticas faithful. O rebate sozinho não salva.
4. **Overround estrutural** — `sum_ask` mediano 1.041; a margem só aparece em janelas transitórias rasas.
5. **Fees** — winner-only `0.07·p·(1−p)`; nunca aplicar taker fee a fill maker (memory `b945`).
6. **Profundidade** — min-sum transiente pode ter < $5 de profundidade → capacidade limitada.

---

## 6. Plano de validação (pré-registro — fazer ANTES de qualquer capital)

Tudo via `data/v4/canonical/load.py`, L25 **nativo 10Hz**, `engine_v2.LiveMimicConfig` (fee 0.07 winner-only) + `book_walk_fill`, regras de `scalp_fill_lib_2026_06_10.py` (size==0=artefato→carry-forward).

**V1 — Existe a janela? (distribuição do min-sum ao longo do tempo)**
- Para cada slug 5m/15m (BTC/ETH/SOL/XRP), computar `sum_ask(t) = ask_up(t)+ask_dn(t)` em toda a janela.
- Métricas por slug: `min_sum`, fração do tempo com `sum<0.97`, profundidade $ disponível nesse momento.
- Pergunta: quantos % dos slugs têm `min_sum < 0.97` com ≥$5 de profundidade, e por quantos segundos?

**V2 — Legging realista (H-C)**
- Simular a política §4.2–4.4: GTC bids, fila proporcional (lower=FIFO, upper=proporcional, como `_maker_queue_bt.py`), hedge da perna solta.
- PnL líquido por par, com rebate como receita e fee winner-only.

**V3 — Robustez**
- `$/par` líquido, **DSR** (n_trials honesto), **ex-top2** outlier robustness (obrigatório — vide cloud_vwap), markout por perna (testar adverse selection H-B/risco#2).
- Variante oracle-gated vs passiva vs taker-baseline (controle).

**Gate de promoção:** `$/par > 0` líquido **E** DSR pass **E** ex-top2 ainda positivo **E** capacidade ≥ $5/par em ≥30% dos slugs. Só então → shadow ≥4 semanas → live $1.

---

## 7. Conclusão (quant)

- A leitura ingênua do artigo ("2 pontas somam < $1, abundante") **não vale** nos 5m/15m: overround mediano +4.1%, só 35% dos slugs cruzam 1.0, e como taker o fee inverte o sinal (já provado por `ce25` → DEPLOY:NO).
- O **único ângulo com chance de alpha** é o que o operador descreveu: **legging assíncrono ao longo do tempo** (H-C) executado como **maker** (H-D), idealmente **oracle-gated** (H-B / Lazer δ) — a única variante maker que o `b945` ainda não refutou.
- O risco dominante é **non-atomic legging + adverse selection na perna barata**, não a matemática da arb.
- **Próximo passo concreto:** rodar V1 (distribuição min-sum + profundidade). É barato, data-ready, e decide em uma sessão se a janela existe com capacidade — se V1 falhar, toda a tese morre antes de escrever o simulador de legging.
```
```
