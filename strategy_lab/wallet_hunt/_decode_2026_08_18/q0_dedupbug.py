"""Testa se o fetcher perde fills: re-puxa UMA janela densa sem dedup e compara."""
import json, urllib.request, time
import pandas as pd, os
OUT=r"C:/Users/alexandre bandarra/Desktop/global/strategy_lab/wallet_hunt/_decode_2026_08_18"
W="0x21d0a97aac03917e752857a551bbe5103a00e8d7"
def get(u):
    r=urllib.request.Request(u,headers={"User-Agent":"curl/8"}); return json.loads(urllib.request.urlopen(r,timeout=30).read())
for SLOT,SLUG in [(1786458600,"btc-updown-5m-1786458600"),(1786466700,"btc-updown-5m-1786466700"),
                  (1786472700,"btc-updown-5m-1786472700")]:
    raw=[]
    for off in range(0,3500,500):
        b=get(f"https://data-api.polymarket.com/activity?user={W}&type=TRADE&limit=500&offset={off}&start={SLOT-3600}&end={SLOT+400}")
        if not b: break
        raw+=b
        if len(b)<500: break
        time.sleep(0.2)
    d=pd.DataFrame(raw)
    d=d[d.slug==SLUG]
    key=d.transactionHash.astype(str)+"|"+d.asset.astype(str)+"|"+d.side.astype(str)+"|"+(d["size"].astype(float)*100).round().astype(int).astype(str)+"|"+d.timestamp.astype(str)
    ded=d[~key.duplicated()]
    f=pd.read_parquet(os.path.join(OUT,"fills_PBot-6.parquet")); c=f[f.slug==SLUG]
    print(f"{SLUG}")
    print(f"   API bruta (sem dedup): {len(d):4d} linhas, {d['size'].astype(float).sum():9.1f} sh")
    print(f"   apos o dedup do fetcher: {len(ded):4d} linhas, {ded['size'].astype(float).sum():9.1f} sh   (perde {d['size'].astype(float).sum()-ded['size'].astype(float).sum():7.1f} sh)")
    print(f"   no cache local:          {len(c):4d} linhas, {c.sh.sum():9.1f} sh")
    print(f"   por lado (bruto):  " + str(d.groupby('outcome')['size'].apply(lambda s: round(s.astype(float).sum(),1)).to_dict()))
    print()
