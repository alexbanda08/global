"""Download bmoney1321/polymarket-crypto-5m-15m (full, ~1.6GB) to D:."""
from huggingface_hub import snapshot_download
p = snapshot_download(repo_id="bmoney1321/polymarket-crypto-5m-15m", repo_type="dataset",
                      local_dir=r"D:\bmoney_hf", max_workers=12, allow_patterns=["*.parquet"])
print("downloaded to", p)
from pathlib import Path
tot=sum(f.stat().st_size for f in Path(r"D:\bmoney_hf").rglob("*.parquet"))
print(f"{tot/1024/1024:.0f} MB across {len(list(Path(r'D:/bmoney_hf').rglob('*.parquet')))} files")
