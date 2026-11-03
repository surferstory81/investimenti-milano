"""Annunci segnati con "mi piace" dalle pagine studenti e famiglia
(data/preferiti.json). Si salva anche titolo, url e prezzo del momento, così
un preferito resta visibile anche se l'annuncio sparisce dai portali."""
from datetime import datetime

from .common import load_json, save_json

FILE = "preferiti.json"
PROFILI = ("studenti", "famiglia")


def tutti():
    return load_json(FILE, {}) or {}


def imposta(id_, profilo, mi_piace, annuncio=None, adesso=None):
    if not id_ or profilo not in PROFILI:
        raise ValueError("id o profilo non validi")
    p = tutti()
    if mi_piace:
        a = annuncio or {}
        p[id_] = {"profilo": profilo, "dal": (p.get(id_) or {}).get("dal")
                  or (adesso or datetime.now()).isoformat(timespec="seconds"),
                  **{k: a.get(k) for k in ("titolo", "url", "prezzo", "fonte")}}
    else:
        p.pop(id_, None)
    save_json(FILE, p)
    return p
