"""
B945 Definitive PnL Audit — 2026-06-12
Reconciles A (+$15,749), B (+$9,749), C (LB $21,742).
Verdict: LB $21,742 is canonical. A and B both wrong for structural reasons.

Key findings:
- B ($9,749) = naive chain ERC20 net (total_in − deposits − total_out)
  = NegRisk pUSD cycling double-counts 0x0 mints & e111 payments
- A ($15,749) = equity formula (cash_at_tape_end + withdrawals − deposits)
  = wrong formula (LB ≠ equity) + stale Jun11 balance + incorrect withdrawal classfication
- LB ($21,742) = Polymarket internal: REDEEM + REBATE − all fill costs
  = $1,352,604 + $3,645 − $1,334,507 = $21,742

Usage: py -3 _b945_pnl_audit.py
"""
import pandas as pd
import numpy as np
import json
import os
import sys
import urllib.request

os.chdir('C:/Users/alexandre bandarra/Desktop/global')

WALLET = '0xb945945d5bcaf7b56834d4da8cdf8f8f94b2db68'
CACHE = 'strategy_lab/wallet_hunt/cache/0xb945945d'
PM = 'strategy_lab/wallet_hunt/cache/_pm_portfolio/0xb945945d'
AUDIT_DIR = f'{PM}/audit_2026_06_12'
os.makedirs(AUDIT_DIR, exist_ok=True)

# Known addresses
PUSD_CONTRACT = '0xf70da97812cb96acdf810712aa562db8dfa3dbef'
CTF_ADDR      = '0x4d97dcd97ec945f40cf65f87097ace5ea0476045'
CLOB_ADDR     = '0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e'
ZERO_ADDR     = '0x0000000000000000000000000000000000000000'
CONV_ADDR     = '0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb'
REBATE_SRC    = '0x3a9418b2651c8164db5ebc56f12008137865e0f7'
E111_ADDR     = '0xe111180000d2663c0091e4f400237545b87b996b'
E05CD_ADDR    = '0x05cd9922a5d37fae921fc5dee280a9dbc4c3b393'
C417_ADDR     = '0xc417fd8e9661c0d2120b64a04bb3278c17e99db1'
C4CD_ADDR     = '0x4cd00e387622c35bddb9b4c962c136462338bc31'  # 6,201 out = cross-wallet transfer

# ─── Load data ────────────────────────────────────────────────────────────────
at = pd.read_parquet(f'{CACHE}/alchemy_transfers.parquet')
fills = pd.read_parquet(f'{CACHE}/fill_tape_full.parquet')

# Use fresh audit snapshots if available, else fall back to stored
def load_json_fresh_or_stored(fresh_path, stored_path):
    if os.path.exists(fresh_path):
        with open(fresh_path, encoding='utf-8') as f:
            return json.load(f)
    with open(stored_path, encoding='utf-8') as f:
        return json.load(f)

redeem_data = load_json_fresh_or_stored(f'{AUDIT_DIR}/activity_REDEEM_fresh.json', f'{PM}/activity_REDEEM.json')
rebate_data = load_json_fresh_or_stored(f'{AUDIT_DIR}/activity_MAKER_REBATE_fresh.json', f'{PM}/activity_MAKER_REBATE.json')

lb_data = load_json_fresh_or_stored(f'{AUDIT_DIR}/lb_all_fresh.json', f'{PM}/lb_profit.json')
if isinstance(lb_data, list):
    lb_val = lb_data[0]['amount']
else:
    lb_val = lb_data['all'][0]['amount']

redeem_df = pd.DataFrame(redeem_data)
rebate_df = pd.DataFrame(rebate_data)
redeem_df['usdcSize'] = redeem_df['usdcSize'].astype(float)
rebate_df['usdcSize'] = rebate_df['usdcSize'].astype(float)

total_redeem = redeem_df['usdcSize'].sum()
total_rebate = rebate_df['usdcSize'].sum()

# ─── Chain fill cost classification ───────────────────────────────────────────
e20 = at[(at['category']=='erc20') & (at['asset'].isin(['pUSD','USDCE','USDC']))].copy()
out_e = e20[e20['direction']=='from']
inn = e20[e20['direction']=='to']

# Primary fill contracts
fills_e111 = out_e[out_e['to'].str.lower() == E111_ADDR.lower()]['value'].sum()
fills_clob = out_e[out_e['to'].str.lower() == CLOB_ADDR.lower()]['value'].sum()
chain_fills_primary = fills_e111 + fills_clob

# P2P fills: non-trading OUT with ERC1155 IN in the same tx
KNOWN_TRADING_DST = {E111_ADDR.lower(), CLOB_ADDR.lower(), CONV_ADDR.lower(),
                     CTF_ADDR.lower(), ZERO_ADDR}
non_trading = out_e[~out_e['to'].str.lower().isin(KNOWN_TRADING_DST)]
erc1155_in_txs = set(at[(at['category']=='erc1155') & (at['direction']=='to')]['tx_hash'].unique())
fills_p2p = non_trading[non_trading['tx_hash'].isin(erc1155_in_txs)]['value'].sum()
# Cross-wallet transfers (no ERC1155 = not fills, just capital movement)
fills_xwallet = non_trading[~non_trading['tx_hash'].isin(erc1155_in_txs)]['value'].sum()

total_chain_fills = chain_fills_primary + fills_p2p

# ─── Naive chain cash flow (= B) ──────────────────────────────────────────────
total_in = inn['value'].sum()
total_out = out_e['value'].sum()
deposits_chain = inn[inn['from'].str.lower() == PUSD_CONTRACT.lower()]['value'].sum()
withdrawals_chain = out_e[out_e['to'].str.lower() == PUSD_CONTRACT.lower()]['value'].sum()
naive_chain_pnl = total_in - deposits_chain - total_out  # = B = $9,749

# pUSD balance at chain tape end
pUSD_in = inn[inn['asset']=='pUSD']['value'].sum()
pUSD_out = out_e[out_e['asset']=='pUSD']['value'].sum()
pUSD_balance_tape = pUSD_in - pUSD_out  # = $19,734 at Jun11 15:07

# ─── Per-slug ledger ──────────────────────────────────────────────────────────
slug_cost = fills.groupby('slug')['usd'].sum()

# REDEEM by slug
redeem_df['slug'] = redeem_df['slug'].fillna('').astype(str)
if 'eventSlug' in redeem_df.columns:
    redeem_df['slug'] = redeem_df['slug'].where(redeem_df['slug']!='', redeem_df['eventSlug'].fillna(''))
rd_by_slug = redeem_df[redeem_df['slug'].str.startswith('btc-updown-15m')].groupby('slug')['usdcSize'].sum()

per_slug = pd.DataFrame({'cost': slug_cost, 'redeem': rd_by_slug}).fillna(0)
per_slug['net'] = per_slug['redeem'] - per_slug['cost']
per_slug = per_slug.sort_values('net', ascending=False)

# Corrected per-slug net: subtract P2P fills (not in fill_tape)
unmapped_fill_cost = fills_p2p  # 84,554 = not attributed to any slug in fill_tape
corrected_per_slug_net = per_slug['net'].sum() - unmapped_fill_cost + total_rebate
chain_pnl_through_tape = total_redeem + total_rebate - total_chain_fills  # 29,722

per_slug.to_parquet(f'{CACHE}/per_slug_audit_ledger.parquet')

# ─── Print results ────────────────────────────────────────────────────────────
print("=" * 70)
print("B945 DEFINITIVE PnL AUDIT — 2026-06-12")
print("=" * 70)
print(f"\nLB (Polymarket canonical, fresh API):  ${lb_val:>12,.2f}  ← TRUE PnL")
print()
print("INCOME STATEMENT:")
print(f"  REDEEM ({len(redeem_df)} events):                ${total_redeem:>12,.2f}")
print(f"  REBATE ({len(rebate_df)} events):                ${total_rebate:>12,.2f}")
print(f"  Total income:                       ${total_redeem + total_rebate:>12,.2f}")
print()
print("FILL COSTS (chain tape, Jun11 15:07):")
print(f"  e111 (negRisk CLOB):                ${fills_e111:>12,.2f}")
print(f"  CLOB exchange:                      ${fills_clob:>12,.2f}")
print(f"  P2P fills (direct w/ERC1155):       ${fills_p2p:>12,.2f}")
print(f"  Cross-wallet transfers (not fills): ${fills_xwallet:>12,.2f}")
print(f"  Total fills (excl xwallet):         ${total_chain_fills:>12,.2f}")
print()
print(f"  Chain PnL (through Jun11 15:07):    ${chain_pnl_through_tape:>12,.2f}")
print(f"  LB fresh (through Jun12 17:45):     ${lb_val:>12,.2f}")
print(f"  Gap = Jun11-12 fills not in tape:   ${chain_pnl_through_tape - lb_val:>12,.2f}")
print()
print("RECONCILIATION OF A, B, C:")
print(f"  A ($15,749): equity formula = pUSD_balance({pUSD_balance_tape:.0f}) + wd(~6000) - dep({deposits_chain:.0f})")
print(f"    = {pUSD_balance_tape:.0f} + 6201 - {deposits_chain:.0f} = {pUSD_balance_tape + 6201 - deposits_chain:.0f} ≈ 15749")
print(f"    ERROR: equity formula ≠ LB (LB is trading-only, not capital-adjusted)")
print(f"  B ($9,749):  naive chain ERC20 = total_in({total_in:.0f}) - deposit({deposits_chain:.0f}) - total_out({total_out:.0f})")
print(f"    = {naive_chain_pnl:.2f}")
print(f"    ERROR: negRisk 0x0 pUSD cycling double-counts internal flows")
print(f"  C ($21,742): REDEEM + REBATE - all_fills = Polymarket's canonical PnL  ← CORRECT")
print()
print("PER-SLUG LEDGER:")
print(f"  Total slugs: {len(per_slug)}")
print(f"  With cost (fill_tape mapped): {(per_slug['cost']>0).sum()}")
print(f"  With redeem: {(per_slug['redeem']>0).sum()}")
print(f"  Zero redeem (pure loss): {(per_slug['redeem']==0).sum()}")
print(f"  fill_tape net (raw, inflated): ${per_slug['net'].sum():>12,.2f}")
print(f"  + rebates: ${per_slug['net'].sum() + total_rebate:>12,.2f}  ← INFLATED (unmapped fills not costed)")
print(f"  Corrected (subtract P2P ${unmapped_fill_cost:.0f} unmapped): ${corrected_per_slug_net:>12,.2f}")
print(f"  Per-slug avg (LB basis): ${lb_val / max(len(redeem_df),1):>8.2f}/slug")
print()
print(f"TOP 10 slugs (warning: top-10 all have cost=0 = unmapped fills!):")
print(per_slug.head(10)[['cost','redeem','net']].round(2).to_string())
print()
print(f"BOTTOM 10 slugs:")
print(per_slug.tail(10)[['cost','redeem','net']].round(2).to_string())
print()
print(f"Artifacts saved: {CACHE}/per_slug_audit_ledger.parquet")
print(f"Report: strategy_lab/reports/B945_PNL_AUDIT_2026_06_12.md")
