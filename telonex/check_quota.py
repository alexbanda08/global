"""Check Telonex quota/rate-limit from response headers (the API leg, before S3)."""
import urllib.request, urllib.error

KEY="tlx_14ecdbcbfd155a0defaf857fa0950e45"; B="https://api.telonex.io/v1"
HDR={"Authorization":"Bearer "+KEY}

class NR(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*a,**k): return None
op=urllib.request.build_opener(NR)

# Hit the API leg only (302 redirect) — inspect ALL headers for quota/rate info.
url=f"{B}/downloads/polymarket/quotes/2026-01-20?slug=will-the-us-strike-iran-next-433&outcome=Yes"
req=urllib.request.Request(url, headers=HDR)
try:
    r=op.open(req, timeout=30)
    hdrs=dict(r.headers); code=r.status
except urllib.error.HTTPError as e:
    hdrs=dict(e.headers); code=e.code

print(f"API status: {code}")
print("=== ALL response headers ===")
for k,v in hdrs.items():
    print(f"  {k}: {v[:120]}")
print("\n=== quota/rate-limit-looking headers ===")
for k,v in hdrs.items():
    if any(t in k.lower() for t in ["rate","limit","quota","remaining","credit","usage","download","reset","x-"]):
        print(f"  {k}: {v}")

# try plausible account/usage endpoints with full header dump
print("\n=== account/usage endpoint probes ===")
for p in ["/me","/account/usage","/usage/me","/key","/keys/me","/quota","/v1/me","/billing","/plan"]:
    try:
        rr=op.open(urllib.request.Request(B.replace('/v1','')+p if p.startswith('/v1') else B+p, headers=HDR), timeout=15)
        print(f"  {p}: {rr.status} {rr.read()[:160].decode(errors='replace')}")
    except urllib.error.HTTPError as e:
        body=e.read()[:160].decode(errors='replace')
        print(f"  {p}: {e.code} {body}")
    except Exception as e:
        print(f"  {p}: ERR {type(e).__name__}")
