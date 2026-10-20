"""Fonti di nicchia che rispondono a normali richieste HTTP (niente anti-bot):
Gabetti (gruppo Gabetti/Grimaldi/Professionecasa), Dove.it, Casavo.
Ogni funzione riceve un filtro {locali_min, locali_max, prezzo_min, prezzo_max,
max_pagine} e una lista di comuni (slug, es. "milano", "sesto-san-giovanni")."""
import json
import re

from .common import http_get, log
from .fonti import _num, _num_it, base_record, geocode_all

AGENT = "Ricerca"


def _ok(f, prezzo, locali):
    return (prezzo and f["prezzo_min"] <= prezzo <= f["prezzo_max"]
            and (locali is None or f["locali_min"] <= locali <= f["locali_max"]))


def _next_data(h):
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S)
    return json.loads(m.group(1))["props"]["pageProps"]


# ----------------------------------------------------------------- Gabetti
_RIGA_T = re.compile(rb"([0-9a-f]+):T([0-9a-f]+),")


def _rsc_testi(big):
    """Righe di testo del payload React: "<id>:T<lunghezza in byte hex>,<testo>"
    (senza a capo finale); le altre righe terminano con "\n"."""
    b, pos, out = big.encode(), 0, {}
    while pos < len(b):
        m = _RIGA_T.match(b, pos)
        if m:
            n = int(m.group(2), 16)
            out[m.group(1).decode()] = b[m.end():m.end() + n].decode("utf-8", "replace")
            pos = m.end() + n
            continue
        nl = b.find(b"\n", pos)
        if nl < 0:
            break
        pos = nl + 1
    return out


def _gabetti_pagina(h):
    """Dati dal payload React (self.__next_f): annunci in "initialData", le
    descrizioni lunghe sono riferimenti "$24" a righe "24:T<len>,<testo>"."""
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', h, re.S)
    big = "".join(json.loads('"' + c + '"') for c in chunks)
    i = big.find('"initialData":')
    if i < 0:
        return [], 0
    arr, _ = json.JSONDecoder().raw_decode(big, i + len('"initialData":'))
    pagine = re.search(r'"totalPages":(\d+)', big)

    testi = _rsc_testi(big)

    def testo(ref):
        if isinstance(ref, str) and ref.startswith("$"):
            return testi.get(ref[1:], "")
        return ref or ""
    for a in arr:
        a["description"] = testo(a.get("description"))
    return arr, int(pagine.group(1)) if pagine else 1


def gabetti(f, comuni):
    out = []
    for comune in comuni:
        page, pages = 1, 1
        while page <= min(pages, f["max_pagine"]):
            url = f"https://www.gabetti.it/vendita/{comune}" + (f"?page={page}" if page > 1 else "")
            try:
                arr, pages = _gabetti_pagina(http_get(url, delay=(1.0, 2.0)))
            except Exception as e:
                log(AGENT, f"Gabetti {comune} pagina {page}: errore {e}")
                break
            for a in arr:
                ft = a.get("features") or {}
                locali = _num(a.get("rooms"))
                if (a.get("typeSlug") not in ("appartamento", "attico", "loft", "mansarda")
                        or not _ok(f, a.get("price"), locali)):
                    continue
                stato = ft.get("property_condition")
                out.append(base_record(
                    id=f"gabetti-{a['id']}", fonte="Gabetti",
                    url=f"https://www.gabetti.it/vendita/{a.get('citySlug') or comune}/{a.get('typeSlug')}/{a['id']}",
                    titolo=f"{a.get('type', 'Appartamento')} {int(locali or 0)} locali — {a.get('address', '')}, "
                           f"{(a.get('city') or '').replace(' (MI)', '')}",
                    descrizione=a["description"],
                    indirizzo=f"{a.get('address', '')}, {(a.get('city') or '').split(' (')[0]}",
                    comune=(a.get("city") or "").split(" (")[0] or None,
                    prezzo=_num(a.get("price")), mq=_num(a.get("squareMeters")),
                    locali=str(int(locali)) if locali else None,
                    bagni=a.get("bathrooms"), camere=ft.get("bedrooms"),
                    piano=ft.get("floor"), stato=stato, classe_energetica=ft.get("energy_class"),
                    riscaldamento=ft.get("heating"), lat=_num(a.get("lat")), lon=_num(a.get("lon")),
                    pin_preciso=True, balcone=bool(ft.get("balconies")), terrazzi=ft.get("terraces"),
                    box=ft.get("garage"), ascensore=bool(ft.get("elevator")),
                    aria_condizionata=bool(ft.get("summer")) or None,
                    spese_condominio_mese=ft.get("condominium_fees"),
                    libero="No" if (ft.get("occupancy_status") or "").lower().startswith("occupat") else None,
                    anno_costruzione=ft.get("year_of_construction"),
                    inserzionista="Gabetti", agenzia=True,
                    immagini=(a.get("images") or [])[:8]))
            page += 1
        log(AGENT, f"Gabetti {comune}: {pages} pagine, annunci nel filtro finora {len(out)}")
    return out


# ----------------------------------------------------------------- Dove.it
def dove(f, comuni):
    out = []
    for comune in comuni:
        page, pages = 1, 1
        while page <= min(pages, f["max_pagine"]):
            url = f"https://www.dove.it/vendita-case/{comune}" + (f"?p={page}" if page > 1 else "")
            try:
                pp = _next_data(http_get(url, delay=(1.0, 2.0)))
            except Exception as e:
                if page == 1:
                    log(AGENT, f"Dove.it {comune}: errore {e}")
                break
            props = pp.get("properties") or {}
            pages = props.get("totalPages") or 1
            for c in props.get("content") or []:
                if not re.match(r"/vendita-case/[^/]+/(?:appartamento|attico|loft|mansarda)", c.get("relativePath", "")):
                    continue
                prezzo = _num_it(re.sub(r"[^\d.]", "", c.get("price") or ""))
                locali = _num(c.get("roomsNumber"))
                if not _ok(f, prezzo, locali):
                    continue
                url_a = "https://www.dove.it" + c["relativePath"]
                try:
                    p = _next_data(http_get(url_a, delay=(1.0, 2.0)))["property"]
                except Exception:
                    p = {}
                det = {d.get("term", "").lower(): d.get("description") for d in p.get("details") or []}
                testo = "\n".join(x for x in (p.get("description"), p.get("composition"),
                                              ", ".join(p.get("features") or [])) if x)
                out.append(base_record(
                    id=f"dove-{c['id']}", fonte="Dove.it", url=url_a,
                    titolo=c.get("title"), descrizione=testo or c.get("abstract"),
                    indirizzo=c.get("normalizedAddress") or f"{c.get('route')}, {c.get('locality')}",
                    comune=c.get("locality"), prezzo=prezzo,
                    mq=_num(re.sub(r"[^\d]", "", det.get("superficie") or "")) or None,
                    locali=str(int(locali)) if locali else None,
                    piano=det.get("piano"), classe_energetica=p.get("energyClass"),
                    riscaldamento=det.get("riscaldamento"),
                    aria_condizionata=bool(det.get("climatizzazione")),
                    lat=_num(p.get("latitude")), lon=_num(p.get("longitude")), pin_preciso=bool(p.get("latitude")),
                    inserzionista="Dove.it", agenzia=True, email_agenzia=p.get("agentEmail"),
                    data_annuncio=c.get("publishedAt"),
                    immagini=[c["coverImageSet"]["large"]] if c.get("coverImageSet") else []))
                if not out[-1]["mq"]:
                    hl = {x["label"]: x["value"] for x in c.get("highlights") or []}
                    out[-1]["mq"] = _num(re.sub(r"[^\d]", "", hl.get("superficie", "")))
            page += 1
    geocode_all(out)
    log(AGENT, f"Dove.it: {len(out)} annunci nel filtro")
    return out


# ------------------------------------------------------------------ Casavo
def casavo(f):
    """Casavo pubblica solo Milano città (immobili spesso già ristrutturati)."""
    out, page, pages = [], 1, 1
    while page <= min(pages, f["max_pagine"]):
        url = "https://casavo.com/it/case-in-vendita/milano/" + (f"?page={page}" if page > 1 else "")
        try:
            pp = _next_data(http_get(url, delay=(1.0, 2.0)))
            res = pp["serverState"]["initialResults"]["prod_listings"]["results"][0]
        except Exception as e:
            log(AGENT, f"Casavo pagina {page}: errore {e}")
            break
        pages = res.get("nbPages") or 1
        for h in res.get("hits") or []:
            locali = _num(h.get("nbPieces"))
            if h.get("typeBien") not in ("flat", "attic", "loft", "mansard") or not _ok(f, h.get("prix"), locali):
                continue
            ristrutturato = h.get("withoutRenovationWork")
            out.append(base_record(
                id=f"casavo-{h['objectID']}", fonte="Casavo",
                url=f"https://casavo.com/it/annuncio/{h['objectID']}/",
                titolo=h.get("titre"), descrizione=("Ristrutturato, senza lavori da fare." if ristrutturato else ""),
                indirizzo=f"{h.get('codePostal')}, {h.get('ville')}", comune=h.get("ville"),
                prezzo=_num(h.get("prix")), mq=_num(h.get("surface")),
                locali=str(int(locali)) if locali else None, camere=h.get("nbBedrooms"),
                stato="Ottimo - ristrutturato" if ristrutturato else None,
                ascensore=bool(h.get("hasLift")), box=1 if h.get("hasParking") else None,
                balcone=bool(h.get("hasOutdoorSpace")),
                inserzionista="Casavo", agenzia=True, data_annuncio=h.get("firstPublication"),
                immagini=[f"https://resize-picture-production.casavo.com/casavo/600x0/{p['dir']}raw_{p['name']}"
                          for p in (h.get("pictures") or [])[:6]]))
        page += 1
    geocode_all(out)  # solo CAP: posizione approssimativa
    log(AGENT, f"Casavo: {len(out)} annunci nel filtro")
    return out
