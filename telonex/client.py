"""
Telonex downloader — handles Bearer auth + the S3 presigned redirect (strips auth
on the S3 leg, which S3 rejects) + retry on flaky SSL for large files.

Usage:
    from client import TelonexClient
    tc = TelonexClient("tlx_...")
    df = tc.download("polymarket", "book_snapshot_25", "2026-01-20",
                     slug="will-the-us-strike-iran-next-433", outcome="Yes")
    cat = tc.catalog("polymarket")   # 800MB markets catalog (slow)
"""
from __future__ import annotations
import io, time, urllib.request, urllib.error
import pandas as pd

API = "https://api.telonex.io/v1"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class TelonexClient:
    def __init__(self, api_key: str, retries: int = 8, timeout: int = 300):
        self.key = api_key
        self.retries = retries
        self.timeout = timeout
        self._opener = urllib.request.build_opener(_NoRedirect)

    def _resolve(self, url: str) -> str:
        """Hit the API with auth; return the presigned S3 Location from the 302."""
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + self.key})
        try:
            self._opener.open(req, timeout=60)
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                return e.headers.get("Location")
            # non-redirect error: surface body
            raise RuntimeError(f"{e.code}: {e.read()[:200].decode(errors='replace')}")
        raise RuntimeError("expected redirect, got direct response")

    def _fetch_bytes(self, api_url: str) -> bytes:
        """Resolve presigned URL, then download WITHOUT auth header, retrying SSL drops."""
        last = None
        for _ in range(self.retries):
            loc = self._resolve(api_url)  # re-resolve each time (presigned may rotate)
            try:
                with urllib.request.urlopen(urllib.request.Request(loc), timeout=self.timeout) as r:
                    buf = io.BytesIO()
                    while True:
                        chunk = r.read(65536)
                        if not chunk:
                            break
                        buf.write(chunk)
                    data = buf.getvalue()
                if data[:4] == b"PAR1":
                    return data
                last = data[:200]
            except Exception as e:
                last = str(e).encode()
                time.sleep(1)
        raise RuntimeError(f"download failed after {self.retries} tries: {last!r}")

    def download(self, exchange: str, channel: str, date: str,
                 slug: str | None = None, outcome: str | None = None,
                 asset_id: str | None = None, market_id: str | None = None) -> pd.DataFrame:
        q = []
        if asset_id:  q.append(f"asset_id={asset_id}")
        if market_id: q.append(f"market_id={market_id}")
        if slug:      q.append(f"slug={slug}")
        if outcome:   q.append(f"outcome={outcome}")
        url = f"{API}/downloads/{exchange}/{channel}/{date}?" + "&".join(q)
        return pd.read_parquet(io.BytesIO(self._fetch_bytes(url)))

    def catalog(self, exchange: str = "polymarket", dataset: str = "markets") -> pd.DataFrame:
        """Full market catalog (~800MB for polymarket/markets) or tags. Slow + SSL-flaky."""
        url = f"{API}/datasets/{exchange}/{dataset}"
        return pd.read_parquet(io.BytesIO(self._fetch_bytes(url)))


if __name__ == "__main__":
    tc = TelonexClient("tlx_14ecdbcbfd155a0defaf857fa0950e45")
    df = tc.download("polymarket", "book_snapshot_25", "2026-01-20",
                     slug="will-the-us-strike-iran-next-433", outcome="Yes")
    print(f"book_snapshot_25: {len(df)} rows, cols={list(df.columns)[:9]}...")
