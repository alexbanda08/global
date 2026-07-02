import json, sys, os

base = os.path.dirname(__file__)
for f in sys.argv[1:]:
    path = os.path.join(base, f + ".json")
    print(f"=== {f} ===")
    try:
        d = json.load(open(path))
        if isinstance(d, list):
            print(f"list len={len(d)}")
            if d:
                print(json.dumps(d[0], indent=2)[:1500])
        else:
            print(json.dumps(d, indent=2)[:1500])
    except Exception as e:
        print("ERROR", e)
    print()
