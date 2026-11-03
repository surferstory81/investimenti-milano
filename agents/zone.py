"""Quartieri di Milano (NIL, Nuclei d'Identità Locale del Comune) e zone scelte
dall'utente.

- nil_di(lat, lon): nome del NIL che contiene il punto, None se fuori dal Comune.
- zona_scelta(lat, lon, zone): la zona dell'utente (config → famiglia.zone) che
  contiene il punto. Ogni zona è l'elenco dei NIL che la compongono, perché i
  portali usano nomi propri ("Solari, Washington") che non coincidono con i NIL.

Confini: agents/dati/nil_milano.geojson (Comune di Milano, PGT 2030, CC BY 4.0)."""
import json
from functools import lru_cache
from pathlib import Path

FILE = Path(__file__).resolve().parent / "dati" / "nil_milano.geojson"


@lru_cache(maxsize=1)
def _nil():
    out = []
    for f in json.loads(FILE.read_text(encoding="utf-8"))["features"]:
        g = f["geometry"]
        poligoni = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        xs = [p[0] for pol in poligoni for p in pol[0]]
        ys = [p[1] for pol in poligoni for p in pol[0]]
        out.append((f["properties"]["NIL"], (min(xs), min(ys), max(xs), max(ys)), poligoni))
    return out


def nomi():
    return sorted(n for n, _, _ in _nil())


def _dentro(x, y, anello):
    c, j = False, len(anello) - 1
    for i in range(len(anello)):
        xi, yi = anello[i][:2]
        xj, yj = anello[j][:2]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            c = not c
        j = i
    return c


def nil_di(lat, lon):
    if lat is None or lon is None:
        return None
    for nome, (x0, y0, x1, y1), poligoni in _nil():
        if not (x0 <= lon <= x1 and y0 <= lat <= y1):
            continue
        for pol in poligoni:  # primo anello: confine; gli altri: buchi
            if _dentro(lon, lat, pol[0]) and not any(_dentro(lon, lat, h) for h in pol[1:]):
                return nome
    return None


def zona_scelta(lat, lon, zone):
    """zone: {"Nome zona": ["NIL", ...]} → nome della zona o None."""
    n = nil_di(lat, lon)
    return next((z for z, elenco in (zone or {}).items() if n in elenco), None) if n else None


def verifica_config(zone):
    """NIL scritti male nel config (non esistono): meglio saperlo subito."""
    validi = set(nomi())
    return sorted({n for elenco in (zone or {}).values() for n in elenco if n not in validi})
