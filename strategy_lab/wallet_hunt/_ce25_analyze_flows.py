"""
_ce25_analyze_flows.py — Analyze transfer flows for chain-true PnL.
Diagnoses what each category of pUSD/USDCE transfer represents.
"""
import pyarrow.parquet as pq
import pandas as pd
import json
from pathlib import Path

CACHE = Path(__file__).resolve().parent / "cache" / "0xce25e214"
PARQUET = CACHE / "alchemy_transfers_full.parquet"

WALLET = "0xce25e214d5cfe4f459cf67f08df581885aae7fdc"
DEP = "0xf70da97812cb96acdf810712aa562db8dfa3dbef"   # pUSD deposit contract
CONV = "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"  # USDCE->pUSD conversion
ZERO = "0x0000000000000000000000000000000000000000"   # CTF mint/burn / pUSD mint

df = pq.read_table(PARQUET).to_pandas()
df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")

usdc = df[df.asset.isin(["pUSD", "USDCE", "USDC"])].copy()
usdc["from_lc"] = usdc["from"].str.lower().fillna("")
usdc["to_lc"] = usdc["to"].str.lower().fillna("")
usdc["rc_lc"] = usdc["raw_contract"].str.lower().fillna("")

print(f"Total rows: {len(df):,}")
print(f"USDC/pUSD rows: {len(usdc):,}")
print(f"ERC1155 rows: {(df.category == 'erc1155').sum():,}")
print()

# --- pUSD from 0x0 breakdown (what raw_contract is it?) ---
from0x0 = usdc[(usdc.direction == "to") & (usdc["from_lc"] == ZERO)]
print(f"=== pUSD arriving FROM 0x0 (31k rows) ===")
print(from0x0.groupby("rc_lc")["value"].agg(["sum", "count"]).sort_values("sum", ascending=False).head(10))
print()

# --- pUSD to 0x0 breakdown ---
to0x0 = usdc[(usdc.direction == "from") & (usdc["to_lc"] == ZERO)]
print(f"=== pUSD going TO 0x0 ===")
print(to0x0.groupby("rc_lc")["value"].agg(["sum", "count"]).sort_values("sum", ascending=False).head(10))
print()

# --- Main flow classification ---
# pUSD from 0x0 via CONV contract = pUSD mint from USDC (user depositing; NOT trading income)
# pUSD from 0x0 via other = actual CTF resolution redemption
# pUSD from DEP = external pUSD deposit

conv_mint = usdc[(usdc.direction == "to") & (usdc["from_lc"] == ZERO) & (usdc["rc_lc"] == CONV)]
ctf_redemption = usdc[(usdc.direction == "to") & (usdc["from_lc"] == ZERO) & (usdc["rc_lc"] != CONV)]
deposit_from_dep = usdc[(usdc.direction == "to") & (usdc["from_lc"] == DEP)]
other_in = usdc[(usdc.direction == "to") & (usdc["from_lc"] != ZERO) & (usdc["from_lc"] != DEP)]

to_conv = usdc[(usdc.direction == "from") & (usdc["to_lc"] == ZERO) & (usdc["rc_lc"] == CONV)]
ctf_mint_cost = usdc[(usdc.direction == "from") & (usdc["to_lc"] == ZERO) & (usdc["rc_lc"] != CONV)]
withdrawal_to_dep = usdc[(usdc.direction == "from") & (usdc["to_lc"] == DEP)]
other_out = usdc[(usdc.direction == "from") & (usdc["to_lc"] != ZERO) & (usdc["to_lc"] != DEP)]

print("=== Corrected flow classification ===")
print(f"IN flows:")
print(f"  conv_mint (pUSD minted from USDC via conv contract): ${conv_mint['value'].sum():>15,.2f}  n={len(conv_mint):,}")
print(f"  ctf_redemption (winner resolution from CTF non-conv): ${ctf_redemption['value'].sum():>12,.2f}  n={len(ctf_redemption):,}")
print(f"  deposit_from_dep (pUSD deposit contract IN):          ${deposit_from_dep['value'].sum():>12,.2f}  n={len(deposit_from_dep):,}")
print(f"  other_in:                                             ${other_in['value'].sum():>12,.2f}  n={len(other_in):,}")
print()
print(f"OUT flows:")
print(f"  to_conv (USDC sent for pUSD conversion):              ${to_conv['value'].sum():>12,.2f}  n={len(to_conv):,}")
print(f"  ctf_mint_cost (CTF token mint cost non-conv):         ${ctf_mint_cost['value'].sum():>12,.2f}  n={len(ctf_mint_cost):,}")
print(f"  withdrawal_to_dep (pUSD deposit contract OUT):        ${withdrawal_to_dep['value'].sum():>12,.2f}  n={len(withdrawal_to_dep):,}")
print(f"  other_out:                                            ${other_out['value'].sum():>12,.2f}  n={len(other_out):,}")
print()

# --- Check if conv_mint ≈ to_conv (they should net to ~0) ---
print(f"Conv net (conv_mint - to_conv): ${conv_mint['value'].sum() - to_conv['value'].sum():,.2f} (should be ~0)")
print()

# --- Corrected chain-true PnL ---
# External capital:
#   Actual external deposits = money from outside Polymarket ecosystem
#   Here DEP = deposit contract, so:
deposits_external = deposit_from_dep["value"].sum()
withdrawals_external = withdrawal_to_dep["value"].sum()

# Trading income/costs (net of capital):
# CTF redemption = resolution income (winner pays out $1)
# CTF mint cost = buying the CTF token sets (but Alchemy doesn't capture this for ERC1155 separately)
# CLOB: other_in = CLOB sell income (selling shares mid-window), other_out = CLOB buy costs
# conv_mint and to_conv cancel out (USDCE<->pUSD swap, internal)
redemption_net = ctf_redemption["value"].sum()
clob_in = other_in["value"].sum()
clob_out = other_out["value"].sum()
ctf_mc = ctf_mint_cost["value"].sum()

chain_pnl_corrected = redemption_net + clob_in - ctf_mc - clob_out

print(f"=== Corrected chain-true PnL ===")
print(f"CTF redemption income:    ${redemption_net:>12,.2f}")
print(f"CLOB sell income:         ${clob_in:>12,.2f}")
print(f"CTF mint costs:           ${ctf_mc:>12,.2f}")
print(f"CLOB buy costs:           ${clob_out:>12,.2f}")
print(f"                          -------------------")
print(f"Chain-true trading PnL:   ${chain_pnl_corrected:>12,.2f}")
print()
print(f"External deposits IN:     ${deposits_external:>12,.2f}")
print(f"External withdrawals OUT: ${withdrawals_external:>12,.2f}")
print(f"Net cash in wallet:       ${conv_mint['value'].sum() + ctf_redemption['value'].sum() + deposit_from_dep['value'].sum() + other_in['value'].sum() - to_conv['value'].sum() - ctf_mint_cost['value'].sum() - withdrawal_to_dep['value'].sum() - other_out['value'].sum():>12,.2f}")
print()

# --- b945 method: deposits - withdrawals + current_balance ---
# current_balance ≈ net_cash (if wallet started at ~0)
net_cash = usdc[usdc.direction == "to"]["value"].sum() - usdc[usdc.direction == "from"]["value"].sum()
b945 = net_cash - deposits_external + withdrawals_external
print(f"b945 method: net_cash({net_cash:,.2f}) - deposits({deposits_external:,.2f}) + withdrawals({withdrawals_external:,.2f}) = ${b945:,.2f}")
print()

# --- Wallet age ---
first_ts = df["ts"].min()
last_ts = df["ts"].max()
age_days = (last_ts - first_ts).total_seconds() / 86400
print(f"First transfer: {first_ts}")
print(f"Last transfer:  {last_ts}")
print(f"Wallet age: {age_days:.1f} days")
print(f"PnL/day (corrected): ${chain_pnl_corrected / age_days:,.0f}/day")
print()

# --- May 15-16 window exact ---
may15 = usdc[(usdc["ts"] >= "2026-05-15") & (usdc["ts"] < "2026-05-17")]
may15_redemptions = may15[(may15.direction == "to") & (may15["from_lc"] == ZERO) & (may15["rc_lc"] != CONV)]
may15_mints = may15[(may15.direction == "from") & (may15["to_lc"] == ZERO) & (may15["rc_lc"] != CONV)]
may15_clob_in = may15[(may15.direction == "to") & (may15["from_lc"] != ZERO) & (may15["from_lc"] != DEP)]
may15_clob_out = may15[(may15.direction == "from") & (may15["to_lc"] != ZERO) & (may15["to_lc"] != DEP)]
may15_conv_mint = may15[(may15.direction == "to") & (may15["from_lc"] == ZERO) & (may15["rc_lc"] == CONV)]
may15_to_conv = may15[(may15.direction == "from") & (may15["to_lc"] == ZERO) & (may15["rc_lc"] == CONV)]

print(f"=== May 15-16 exact ===")
print(f"CTF redemption income: ${may15_redemptions['value'].sum():>12,.2f}  (n={len(may15_redemptions):,})")
print(f"CTF mint costs:        ${may15_mints['value'].sum():>12,.2f}  (n={len(may15_mints):,})")
print(f"CLOB sell income:      ${may15_clob_in['value'].sum():>12,.2f}  (n={len(may15_clob_in):,})")
print(f"CLOB buy costs:        ${may15_clob_out['value'].sum():>12,.2f}  (n={len(may15_clob_out):,})")
print(f"Conv mint (neutral):   ${may15_conv_mint['value'].sum():>12,.2f}")
print(f"Conv out (neutral):    ${may15_to_conv['value'].sum():>12,.2f}")
may15_net = may15_redemptions["value"].sum() + may15_clob_in["value"].sum() - may15_mints["value"].sum() - may15_clob_out["value"].sum()
print(f"Net May 15-16 PnL:     ${may15_net:>12,.2f}")
print(f"Implied daily rate:    ${may15_net / (2 / 1):>12,.2f}/2days = ${may15_net / (14.0/24):>12,.2f}/day (if 14h window)")
print()

# --- Also check ctf_redemption raw_contracts to understand what they are ---
print(f"=== CTF redemption raw contracts (top 5) ===")
print(ctf_redemption.groupby("rc_lc")["value"].agg(["sum", "count"]).sort_values("sum", ascending=False).head(5))
