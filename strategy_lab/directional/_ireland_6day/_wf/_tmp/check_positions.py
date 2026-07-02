import json, os
base = os.path.dirname(__file__)
d = json.load(open(os.path.join(base, "positions_full.json")))
print("n positions", len(d))
