import pandas as pd, numpy as np, urllib.request, json, time

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

df = pd.read_csv('b945_buys_parsed_2026_07_13.csv')
slugs = sorted(df['eventSlug'].dropna().unique()) if 'eventSlug' in df.columns else sorted(df['slug'].dropna().unique())
print("unique slugs to resolve:", len(slugs))

results = {}
n = 0
for s in slugs:
    n += 1
    url = f"https://gamma-api.polymarket.com/events?slug={s}"
    try:
        d = get(url)
        if d and isinstance(d, list) and len(d) > 0:
            ev = d[0]
            markets = ev.get('markets', [])
            if markets:
                m = markets[0]
                op = m.get('outcomePrices')
                outcomes = m.get('outcomes')
                results[s] = {'outcomePrices': op, 'outcomes': outcomes, 'closed': m.get('closed')}
            else:
                results[s] = {'outcomePrices': None, 'outcomes': None, 'closed': None}
        else:
            results[s] = {'outcomePrices': None, 'outcomes': None, 'closed': None}
    except Exception as e:
        results[s] = {'error': str(e)}
    if n % 150 == 0:
        print(f"{n}/{len(slugs)} done, sleeping...")
        time.sleep(0.15)
    else:
        time.sleep(0.02)

with open('b945_resolutions_2026_07_13.json', 'w') as f:
    json.dump(results, f, indent=1)

ok = sum(1 for v in results.values() if v.get('outcomePrices'))
print(f"resolved {ok}/{len(slugs)}")
print("saved b945_resolutions_2026_07_13.json")
