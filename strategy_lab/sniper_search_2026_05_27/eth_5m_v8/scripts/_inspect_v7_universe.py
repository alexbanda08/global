"""Inspect V7 universe schema."""
import pyarrow.parquet as pq

u = r'C:\Users\alexandre bandarra\Desktop\global\data\v4\canonical\_results\_sniper_eth5m_v7_universe.parquet'
schema = pq.read_schema(u)
print('NUM COLS:', len(schema.names))
g_cols = [n for n in schema.names if n.startswith('g_')]
print('NUM g_ cols:', len(g_cols))
for c in g_cols:
    print(' ', c)
print()
print('Non-g cols:')
oth = [n for n in schema.names if not n.startswith('g_')]
for c in oth:
    print(' ', c)
