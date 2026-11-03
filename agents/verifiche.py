"""Dati degli annunci importati a mano dal browser dell'utente (segnalibro
"Importa annuncio" della pagina famiglia).

Casa.it, Idealista e Immobiliare.it bloccano le visite automatiche: l'utente apre
l'annuncio nel proprio browser e il segnalibro manda alla dashboard il testo
della pagina (più gli eventuali dati strutturati JSON-LD). Qui si ricavano camere,
bagni e locali; il testo completo sostituisce la descrizione mancante o troncata
degli avvisi email, così salone, cucina e plus si leggono come per le altre fonti.
I dati restano in data/verifiche.json e valgono per tutte le valutazioni successive."""
import json
import re
from datetime import datetime

from .common import load_json, save_json

FILE = "verifiche.json"
MAX_TESTO = 40000

# URL dell'annuncio → id usato dalle fonti (fonti.casa_email, idealista_email, immobiliare_email)
_ID_URL = (
    (r"casa\.it/immobili/(\d+)", "casa-{}"),
    (r"idealista\.it/immobile/(\d+)", "idealista-{}"),
    (r"immobiliare\.it/annunci/(\d+)", "immobiliare-{}"),
)

_PAROLE = {"un": 1, "una": 1, "uno": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6}
_NUM = r"(\d{1,2}|due|tre|quattro|cinque|sei)"


def id_da_url(url):
    for rx, fmt in _ID_URL:
        m = re.search(rx, url or "")
        if m:
            return fmt.format(m.group(1))
    return None


def _n(x):
    x = str(x).strip().lower()
    return _PAROLE.get(x) or (int(x) if x.isdigit() else None)


def _jsonld(testo):
    """Valori numerici dai blocchi JSON-LD (schema.org: numberOfBedrooms, ...)."""
    out = {}

    def visita(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("numberOfBedrooms", "numberOfBathroomsTotal", "numberOfRooms") and k not in out:
                    v = v.get("value") if isinstance(v, dict) else v
                    try:
                        out[k] = int(float(v))
                    except (TypeError, ValueError):
                        pass
                else:
                    visita(v)
        elif isinstance(o, list):
            for v in o:
                visita(v)

    for blocco in re.split(r"\n(?=[\[{])", testo or ""):
        try:
            visita(json.loads(blocco))
        except ValueError:
            continue
    return out


def _cerca(testo, *regex):
    """Primo valore trovato: le schede dei portali hanno sia "3 camere da letto"
    sia l'etichetta seguita dal valore ("Camere da letto\\n3", "Bagni: 2")."""
    for rx in regex:
        m = re.search(rx, testo, re.I)
        if m:
            v = _n(m.group(1))
            if v is not None and 0 < v < 20:
                return v
    return None


def estrai(testo, jsonld=""):
    t = testo or ""
    j = _jsonld(jsonld)
    camere = j.get("numberOfBedrooms") or _cerca(
        t, r"\b" + _NUM + r"[ \t]+camer[ae] da letto", r"camer[ae] da letto\s*:?\s*\n?\s*(\d{1,2})\b",
        r"\bcamere\s*:?\s*\n\s*(\d{1,2})\b")
    bagni = j.get("numberOfBathroomsTotal") or _cerca(
        t, r"\b" + _NUM + r"[ \t]+bagn[io]\b", r"\bbagn[io]\s*:?\s*\n?\s*(\d{1,2})\b")
    locali = j.get("numberOfRooms") or _cerca(
        t, r"\b" + _NUM + r"[ \t]+locali\b", r"\blocali\s*:?\s*\n?\s*(\d{1,2})\b")
    return {"camere": camere, "bagni": bagni, "locali": locali}


def importa(payload, adesso=None):
    """payload dal segnalibro: {"u": url, "t": titolo pagina, "x": testo, "j": JSON-LD}.
    Restituisce la verifica salvata (con l'id dell'annuncio)."""
    url = (payload.get("u") or "").strip()
    aid = id_da_url(url)
    if not aid:
        raise ValueError("pagina non riconosciuta: apri un annuncio Casa.it, Idealista o Immobiliare.it")
    testo = (payload.get("x") or "").strip()[:MAX_TESTO]
    if len(testo) < 200 or re.search(r"captcha|verifica di sicurezza|sei un robot", testo[:2000], re.I):
        raise ValueError("la pagina non contiene l'annuncio (caricamento incompleto o verifica anti-bot "
                         "ancora aperta): completala nel browser e riprova")
    v = {"id": aid, "url": url, "titolo_pagina": (payload.get("t") or "")[:300], "testo": testo,
         "importato": (adesso or datetime.now()).isoformat(timespec="seconds"),
         **estrai(testo, payload.get("j") or "")}
    tutte = load_json(FILE, {})
    tutte[aid] = v
    save_json(FILE, tutte)
    return v


def applica(annuncio, verifiche):
    """Completa un annuncio con la verifica importata, se c'è. Il testo della
    pagina diventa la descrizione; camere/bagni/locali solo se trovati."""
    v = verifiche.get(annuncio.get("id"))
    if not v:
        return annuncio
    annuncio["descrizione"] = v["testo"]
    for k in ("camere", "bagni", "locali"):
        if v.get(k):
            annuncio[k] = v[k]
    annuncio["verificato"] = v["importato"]
    return annuncio
