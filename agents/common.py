"""Utility condivise dagli agenti: config, IO dati, HTTP, geografia."""
import json
import math
import random
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


def load_config():
    return json.loads((ROOT / "config.json").read_text())


def load_json(name, default=None):
    p = DATA / name
    if not p.exists():
        return default
    return json.loads(p.read_text())


def save_json(name, obj):
    p = DATA / name
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2))
    tmp.replace(p)


def log(agent, msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] [{agent}] {msg}"
    print(line, flush=True)
    with open(DATA / "agenti.log", "a") as f:
        f.write(line + "\n")


def http_get(url, delay=(1.5, 3.0), tentativi=3):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept-Language": "it-IT,it;q=0.9",
        "Accept": "text/html,application/xhtml+xml",
    })
    for i in range(tentativi):
        time.sleep(random.uniform(*delay) * (i + 1))
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            if i == tentativi - 1:
                raise


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_universities(lat, lon, universities):
    out = []
    for u in universities:
        d = haversine_km(lat, lon, u["lat"], u["lon"])
        out.append({"nome": u["nome"], "zona": u["zona"], "km": round(d, 2)})
    return sorted(out, key=lambda x: x["km"])


def median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def percentile(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    f = int(k)
    return xs[f] + (xs[min(f + 1, len(xs) - 1)] - xs[f]) * (k - f)
