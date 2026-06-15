import os
os.chdir(r"C:\Users\alexandre bandarra\Desktop\global")
import pyarrow as pa
import pyarrow.parquet as pq
import numpy as np

src = r"data/v4/canonical/resolutions_hf.parquet"
t = pq.read_table(src)
df = t.to_pandas()

# Diagnosis: outcome-agreement sweep peaks at offset 0 for ALL (source,tf) groups
# => slot_start_us / slot_end_us are ALREADY the correct strike/settle times.
# No offset is unambiguously warranted. Pass through unchanged, tag offset=0.
df['timing_offset_applied_s'] = np.int32(0)

out = pa.Table.from_pandas(df, preserve_index=False)
dst = r"data/v4/canonical/resolutions_hf_timingfix_2026_06_10.parquet"
pq.write_table(out, dst)
print("wrote", dst, "rows", len(df), "cols", list(df.columns))
# verify identical timing
import pyarrow.compute as pc
v = pq.read_table(dst).to_pandas()
assert (v['slot_start_us'].values == df['slot_start_us'].values).all()
assert (v['timing_offset_applied_s']==0).all()
print("verified: slot_start_us unchanged; timing_offset_applied_s all 0")
