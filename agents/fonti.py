"""Fonti di annunci usate dall'Agente Ricerca. Ogni fonte restituisce una lista
di annunci normalizzati con lo stesso schema."""
import hashlib
import html as htmlmod
import json
import random
import re
import time
import urllib.parse
import urllib.request

from .common import http_get, load_json, log, save_json

AGENT = "Ricerca"


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _num_it(x):
    """Numero in formato italiano: '189.000' -> 189000."""
    return _num(str(x).replace(".", "").replace(",", ".")) if x else None


def base_record(**kw):
    rec = {k: None for k in (
        "id", "fonte", "url", "titolo", "descrizione", "indirizzo", "data_annuncio",
        "prezzo", "prezzo_precedente", "mq", "locali", "bagni", "piano", "stato",
        "classe_energetica", "riscaldamento", "lat", "lon", "inserzionista",
        "telefono_inserzionista")}
    rec.update({"arredato": False, "balcone": False, "ascensore": False,
                "aria_condizionata": False, "agenzia": True, "asta": False,
                "pin_preciso": False, "immagini": []})
    rec.update(kw)
    return rec


# --------------------------------------------------------------- Subito.it
SUBITO = "https://www.subito.it/annunci-lombardia/{tipo}/appartamenti/milano/milano/"


def _subito_feat(item, key):
    f = item.get("features", {}).get(key)
    if not f or not f.get("values"):
        return None
    v = f["values"][0]
    return v.get("key") if f.get("type") == "number" else v.get("value")


def _subito_item(item):
    mp = (item.get("geo") or {}).get("map") or {}
    m = re.search(r":(\d+)$", item.get("urn", ""))
    adv = item.get("advertiser") or {}
    f = lambda k: _subito_feat(item, k)  # noqa: E731
    return base_record(
        id="subito-" + (m.group(1) if m else item.get("urn", "")),
        fonte="Subito.it",
        url=(item.get("urls") or {}).get("default"),
        titolo=item.get("subject"),
        descrizione=item.get("body", ""),
        data_annuncio=item.get("date"),
        prezzo=_num(f("/price")), mq=_num(f("/size")),
        locali=f("/room"), bagni=f("/bathrooms"), piano=f("/floor"),
        stato=f("/building_condition"), classe_energetica=f("/energy_class"),
        riscaldamento=f("/heating"),
        arredato=f("/furnished") == "Sì", balcone=f("/balcony") == "Sì",
        ascensore=f("/elevator") == "Sì", aria_condizionata=f("/air_conditioning") == "Sì",
        lat=_num(mp.get("latitude")), lon=_num(mp.get("longitude")),
        pin_preciso=bool(mp.get("showPin")),
        comune=((item.get("geo") or {}).get("town") or {}).get("value"),
        inserzionista=adv.get("name"), agenzia=bool(adv.get("company")),
        immagini=[i["cdnBaseUrl"] + "?rule=gallery-desktop-1x-auto"
                  for i in item.get("images", [])[:8] if i.get("cdnBaseUrl")],
    )


def subito(tipo, cfg):
    r = cfg["ricerca"]
    params = f"?rs={r['locali_min']}&re={r['locali_max']}"
    if tipo == "vendita":
        params += f"&ps={r['prezzo_min']}&pe={r['prezzo_max']}"
    out, page, pages = [], 1, 1
    while page <= min(pages, r["max_pagine"]):
        url = SUBITO.format(tipo=tipo) + params + (f"&o={page}" if page > 1 else "")
        try:
            h = http_get(url)
            m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S)
            items = json.loads(m.group(1))["props"]["pageProps"]["initialState"]["items"]
        except Exception as e:
            log(AGENT, f"Subito {tipo} pagina {page}: errore {e}")
            break
        pages = items.get("totalPages") or 1
        batch = [_subito_item(i) for i in items.get("originalList", [])
                 if i.get("kind") == "AdItem"]
        out.extend(batch)
        log(AGENT, f"Subito {tipo}: pagina {page}/{pages} → {len(batch)}")
        page += 1
    return out


TIPOLOGIE = {1: "monolocali", 2: "bilocali", 3: "trilocali"}


def tipologie(r):
    """[(n. locali, "monolocali"), ...] richiesti da ricerca.locali_min/max."""
    return [(n, TIPOLOGIE[n]) for n in range(r["locali_min"], r["locali_max"] + 1)
            if n in TIPOLOGIE]


def _pagine_browser(r):
    """Casa.it e Idealista bloccano chi fa molte richieste ravvicinate: poche
    pagine (le più recenti) e pause lunghe, una volta al giorno."""
    return min(r["max_pagine"], r.get("browser_max_pagine", 3))


def _pausa_browser():
    time.sleep(random.uniform(8, 15))


# ----------------------------------------------------------------- Casa.it
CASA = "https://www.casa.it/vendita/residenziale/{tipo}/milano/"


def _casa_item(x):
    ft = x.get("features") or {}
    gi = x.get("geoInfos") or {}
    pub = x.get("publisher") or {}
    price = ((ft.get("price") or {}).get("marker") or {}).get("originalPrice")
    labels = [l.lower() for l in (x.get("labels") or [])]
    stato = None
    if any("ristrutturat" in l for l in labels):
        stato = "Ottimo - ristrutturato"
    elif any("nuov" in l for l in labels):
        stato = "Nuovo - in costruzione"
    elif any("da ristrutturare" in l for l in labels):
        stato = "Da ristrutturare"
    via = gi.get("street") if gi.get("show_address") else None
    zona = ", ".join(z for z in (gi.get("district_name"), gi.get("block_name")) if z)
    return base_record(
        id=f"casa-{x['id']}", fonte="Casa.it",
        url="https://www.casa.it" + x.get("uri", ""),
        titolo=((x.get("title") or {}).get("main") or "") +
        (f" — {zona}" if zona else ""),
        descrizione=(x.get("highlight") or "") + "\n" + (x.get("description") or ""),
        indirizzo=", ".join(p for p in (via, zona, "Milano") if p),
        prezzo=_num(price), mq=_num(ft.get("mq")), locali=ft.get("rooms"),
        bagni=ft.get("bathrooms"), piano=ft.get("level"), stato=stato,
        classe_energetica=ft.get("energyClass"),
        lat=_num(gi.get("lat")), lon=_num(gi.get("lon")),
        pin_preciso=gi.get("geo_visibility_level") == 1 and bool(via),
        inserzionista=pub.get("publisherName"),
        telefono_inserzionista=pub.get("publisherPhone"),
        agenzia=pub.get("publisherType") == "Agency",
        asta=bool(x.get("isAuction")),
        immagini=["https://images-1.casa.it/360x265" + m["uri"]
                  for m in ((x.get("media") or {}).get("items") or [])[:8] if m.get("uri")],
    )


def casa(ff, cfg):
    r = cfg["ricerca"]
    out = []
    for n, tipo in tipologie(r):
        page, pages = 1, 1
        while page <= min(pages, _pagine_browser(r)):
            url = CASA.format(tipo=tipo) + (f"?page={page}" if page > 1 else "")
            _pausa_browser()
            try:
                h = ff.get(url, wait=4)
                m = re.search(r'window\.__INITIAL_STATE__ = JSON\.parse\((".*?")\);', h, re.S)
                if not m:
                    log(AGENT, f"Casa.it {tipo} pagina {page}: richiesta verifica anti-bot, interrompo")
                    return out
                s = json.loads(json.loads(m.group(1)))["search"]
            except Exception as e:
                log(AGENT, f"Casa.it {tipo} pagina {page}: errore {e}")
                break
            pages = s["paginator"]["totalPages"]
            batch = [_casa_item(x) for x in s.get("list", [])]
            for b in batch:
                b["locali"] = b["locali"] or str(n)
            out.extend(b for b in batch if b["prezzo"] and
                       r["prezzo_min"] <= b["prezzo"] <= r["prezzo_max"])
            log(AGENT, f"Casa.it {tipo}: pagina {page}/{pages} → {len(batch)}")
            page += 1
    return out


# ---------------------------------------------------------------- Idealista
IDEALISTA = ("https://www.idealista.it/vendita-case/milano-milano/con-prezzo_{pmax},"
             "prezzo-min_{pmin},{tipo}/")


def _text(fragment):
    return htmlmod.unescape(re.sub(r"<[^>]+>", " ", fragment)).strip()


def _idealista_parse(h, locali="1"):
    out = []
    for art in re.findall(r'<article class="item[^"]*"[^>]*data-element-id="(\d+)"'
                          r'[^>]*>(.*?)</article>', h, re.S):
        eid, body = art
        t = re.search(r'class="item-link[^"]*" title="([^"]+)"', body)
        p = re.search(r'class="item-price[^"]*">([\d.]+)', body)
        if not (t and p):
            continue
        det = [_text(d) for d in re.findall(r'<span class="item-detail">(.*?)</span>',
                                            body, re.S)]
        mq = next((_num(re.sub(r"[^\d]", "", d)) for d in det if "m²" in d), None)
        piano = next((d for d in det if "piano" in d.lower()), None)
        old = re.search(r'pricedown_price">\s*([\d.]+)', body)
        desc = re.search(r'item-description[^>]*>(.*?)</div>', body, re.S)
        agz = re.search(r'class="logo-branding">\s*<a [^>]*title="([^"]+)"', body)
        imgs = re.findall(r'<img src="(https://img\d\.idealista\.it/[^"]+)"', body)
        title = htmlmod.unescape(t.group(1))
        out.append(base_record(
            id=f"idealista-{eid}", fonte="Idealista",
            url=f"https://www.idealista.it/immobile/{eid}/",
            titolo=title, descrizione=_text(desc.group(1)) if desc else "",
            indirizzo=re.sub(r"^\S+ in ", "", title),
            prezzo=_num_it(p.group(1)), prezzo_precedente=_num_it(old.group(1)) if old else None,
            mq=mq, locali=locali, piano=piano,
            ascensore=bool(piano and "con ascensore" in piano),
            inserzionista=htmlmod.unescape(agz.group(1)) if agz else "Privato",
            agenzia=bool(agz),
            immagini=[i.replace("/blur/480_360_mq/", "/blur/WEB_LISTING/") for i in imgs[:6]],
        ))
    return out


def idealista(ff, cfg):
    r = cfg["ricerca"]
    out = []
    for n, tipo in tipologie(r):
        base = IDEALISTA.format(pmax=r["prezzo_max"], pmin=r["prezzo_min"], tipo=tipo)
        page = 1
        while page <= _pagine_browser(r):
            url = base + (f"pagina-{page}.htm" if page > 1 else "") + "?ordine=pubblicazione-desc"
            _pausa_browser()
            try:
                h = ff.get(url, wait=4)
            except Exception as e:
                log(AGENT, f"Idealista {tipo} pagina {page}: errore {e}")
                break
            if "captcha" in h[:5000].lower() and "<article" not in h:
                log(AGENT, "Idealista: richiesta verifica anti-bot, interrompo")
                geocode_all(out)
                return out
            batch = _idealista_parse(h, str(n))
            new = [b for b in batch if b["id"] not in {o["id"] for o in out}]
            log(AGENT, f"Idealista {tipo}: pagina {page} → {len(new)}")
            if not new:
                break  # oltre l'ultima pagina Idealista ripete l'ultima
            out.extend(new)
            if f"pagina-{page + 1}.htm" not in h:
                break
            page += 1
    geocode_all(out)
    return out


# --------------------------------------------- Geocoding (OpenStreetMap)
def geocode(q, cache):
    if q in cache:
        return cache[q]
    time.sleep(1.1)  # policy Nominatim: max 1 richiesta/s
    url = ("https://nominatim.openstreetmap.org/search?format=json&limit=1&"
           "countrycodes=it&q=" + urllib.parse.quote(q))
    req = urllib.request.Request(url, headers={"User-Agent": "investimenti-milano/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            res = json.loads(resp.read())
        cache[q] = [float(res[0]["lat"]), float(res[0]["lon"])] if res else None
    except Exception:
        return None
    return cache[q]


def geocode_all(records):
    cache = load_json("geocache.json", {})
    for r in records:
        if r["lat"] or not r["indirizzo"]:
            continue
        parts = [p.strip() for p in r["indirizzo"].split(",") if p.strip()]
        comune = parts[-1] if len(parts) > 1 and not re.search(r"\d", parts[-1]) else "Milano"
        # indirizzo completo, via + comune, quartiere + comune, solo comune (fuori Milano)
        for q in (", ".join(parts), f"{parts[0]}, {comune}",
                  f"{parts[-2]}, {comune}" if len(parts) > 2 else None,
                  comune if comune != "Milano" else None):
            if not q:
                continue
            c = geocode(q, cache)
            # Milano e cintura (circa 15 km dal Duomo)
            if c and 45.33 < c[0] < 45.60 and 9.00 < c[1] < 9.40:
                r["lat"], r["lon"] = c
                r["pin_preciso"] = q == ", ".join(parts) and any(ch.isdigit() for ch in parts[0])
                break
    save_json("geocache.json", cache)


# ---------------------------------------------------------------- Tecnocasa
TECNOCASA = "https://www.tecnocasa.it/annunci/immobili/lombardia/milano/milano.html"


def _vue_attr(h, name):
    m = re.search(r' :' + name + r'="([^"]*)"', h)
    return json.loads(htmlmod.unescape(m.group(1))) if m else None


def _tecnocasa_detail(url, base):
    e = _vue_attr(http_get(url, delay=(1.0, 2.0)), "estate")
    if not e:
        return base
    data = {d["label"]: htmlmod.unescape(str(d["valore"])) for d in e.get("data") or []}
    ft = e.get("features") or {}
    ag = e.get("agency") or {}
    spese = _num_it(re.sub(r"[^\d.,]", "", data.get("Spese Annue", "")))
    metro = [p for p in (e.get("points_of_interest") or {}).get("public_transport", [])
             if p.get("subclass") == "subway"]
    base.update(
        descrizione=_text(e.get("description") or ""),
        indirizzo=(data.get("Indirizzo") or e.get("address") or "") + ", " + (data.get("Comune") or "Milano"),
        lat=_num(e.get("latitude")), lon=_num(e.get("longitude")),
        pin_preciso=bool(e.get("publish_map")),
        data_annuncio=e.get("last_published_at"),
        mq=_num(e.get("numeric_surface")) or base["mq"],
        prezzo=_num(e.get("numeric_price")) or base["prezzo"],
        piano=ft.get("floor"), bagni=data.get("Bagni"),
        classe_energetica=((e.get("energy_data") or {}).get("class") or "").upper() or None,
        riscaldamento=ft.get("heating_immo"),
        arredato=ft.get("furnitured") not in (None, "No", "Non arredato"),
        balcone=bool(ft.get("balconies")), ascensore=ft.get("elevator_immo") == "Sì",
        aria_condizionata=ft.get("air_conditioning_immo") not in (None, "No"),
        inserzionista=f"Tecnocasa — {ag.get('name', '')}".strip(" —"),
        email_agenzia=ag.get("email"),
        telefono_inserzionista=ag.get("phone") or ag.get("mobile"),
        spese_condominio_mese=round(spese / 12) if spese else None,
        tipo_proprieta=data.get("Tipo proprieta"),
        libero=ft.get("free"),
        anno_costruzione=ft.get("build_year"),
        metro_vicina=f"{metro[0]['name']} ({metro[0]['distance']})" if metro else None,
        camere=ft.get("bedrooms"), terrazzi=ft.get("terraces"), box=ft.get("box"),
        giardino=ft.get("garden"),
        anno_ristrutturazione=ft.get("inside_renovation_year") or ft.get("renovation_year"),
    )
    return base


def _tecnocasa_locali(x, r):
    """N. locali ("1", "2"...) se la card è una tipologia cercata, altrimenti None."""
    titolo = (x.get("title") or "").lower()
    for n, tipo in tipologie(r):
        if tipo[:-1] + "e" in titolo:  # "monolocale", "bilocale"
            return str(n)
        if ("appartament" in (x.get("detail_url") or "")
                and str(x.get("rooms", "")).startswith(f"{n} local")
                and not re.search(r"box|posto auto|garage|magazzin|negozio|ufficio", titolo)):
            return str(n)
    return None


def tecnocasa(cfg, unis_filter):
    """unis_filter(lat, lon) -> bool: i dettagli si scaricano solo per gli
    annunci vicini alle università (geocodificati dalla card)."""
    r = cfg["ricerca"]
    cards, page, pages, errori = [], 1, 1, 0
    while page <= min(pages, max(r["max_pagine"], 80)):
        url = TECNOCASA + (f"/pag-{page}" if page > 1 else "")
        try:
            h = http_get(url, delay=(1.0, 2.0))
            est = _vue_attr(h, "estates") or []
            pages = (_vue_attr(h, "pagination") or {}).get("total_pages", 1)
        except Exception as e:
            log(AGENT, f"Tecnocasa pagina {page}: errore {e}, la salto")
            errori += 1
            if errori >= 5:
                break
            page += 1
            continue
        mono = [x for x in est if _tecnocasa_locali(x, r)]
        cards.extend(mono)
        if page % 10 == 0 or page == pages:
            log(AGENT, f"Tecnocasa: pagina {page}/{pages}, annunci finora {len(cards)}")
        page += 1

    out = []
    for x in cards:
        prezzo = _num_it(re.sub(r"[^\d.]", "", x.get("price") or ""))
        if not prezzo or not (r["prezzo_min"] <= prezzo <= r["prezzo_max"]):
            continue
        rec = base_record(
            id=f"tecnocasa-{x['id']}", fonte="Tecnocasa", url=x.get("detail_url"),
            titolo=f"{x.get('title', '')} — {x.get('subtitle', '')}",
            indirizzo=(x.get("subtitle") or "").replace(" - ", ", "),
            prezzo=prezzo, prezzo_precedente=_num_it(re.sub(r"[^\d.]", "",
                                                            x.get("previous_price") or "")),
            mq=_num(re.sub(r"[^\d]", "", x.get("surface") or "")), locali=_tecnocasa_locali(x, r),
            immagini=[i["url"]["gallery"] for i in (x.get("images") or [])[:8]
                      if (i.get("url") or {}).get("gallery")],
        )
        try:
            rec = _tecnocasa_detail(rec["url"], rec)
        except Exception as e:
            log(AGENT, f"Tecnocasa dettaglio {x['id']}: {e}")
        out.append(rec)
    geocode_all(out)
    log(AGENT, f"Tecnocasa: {len(out)} annunci nel range di prezzo")
    return out


# ------------------------------------- Immobiliare.it (avvisi email via IMAP)
# Immobiliare.it blocca le visite automatiche (DataDome), ma invia gli annunci
# nuovi delle ricerche salvate per email: li leggiamo dalla casella Gmail.
_IMM_BLOCCO = re.compile(
    r"﻿?(?P<titolo>[^\n]+?)﻿?\s*\(\s*(?P<url>https://clicks\.immobiliare\.it/\S+)\s*\)"
    r"(?P<corpo>(?:(?!https://clicks).)*?)VEDI DETTAGLI", re.S)


def _imm_url(click):
    """Il link dell'email è un redirect di tracciamento: ne leggiamo solo la
    destinazione (senza visitare immobiliare.it) per avere l'ID dell'annuncio."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **kw):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    try:
        opener.open(urllib.request.Request(
            click, headers={"User-Agent": "investimenti-milano/1.0"}), timeout=15)
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location") or ""
        m = re.search(r"immobiliare\.it/annunci/(\d+)", loc)
        if m:
            return m.group(1), f"https://www.immobiliare.it/annunci/{m.group(1)}/"
    except Exception:
        pass
    return None, click


def _imm_parse(testo):
    out = []
    for b in _IMM_BLOCCO.finditer(testo):
        corpo = htmlmod.unescape(b["corpo"])
        prezzo = re.search(r"€\s*([\d.]+)", corpo)
        mq = re.search(r"(\d+)\s*m(?:²|2)", corpo)
        locali = re.search(r"(\d+)\s*local", corpo)
        bagni = re.search(r"(\d+)\s*bagn", corpo)
        titolo = b["titolo"].strip()
        # "Monolocale via Tal dei Tali 8, Quartiere, Milano" -> indirizzo dopo la tipologia
        indirizzo = re.sub(r"^\S+\s+", "", titolo)
        out.append(dict(titolo=titolo, click=b["url"], indirizzo=indirizzo,
                        prezzo=_num_it(prezzo.group(1)) if prezzo else None,
                        mq=_num(mq.group(1)) if mq else None,
                        locali=locali.group(1) if locali else ("1" if "monolocale" in titolo.lower() else None),
                        bagni=bagni.group(1) if bagni else None))
    return out


def _imm_email(cfg, giorni):
    """Annunci dagli avvisi di Immobiliare.it degli ultimi `giorni`, ciascuno con
    il nome della ricerca salvata che l'ha generato (campo "ricerca")."""
    import email
    import imaplib
    from datetime import datetime, timedelta
    from email.header import decode_header, make_header
    e = cfg["email"]
    if not e.get("password_app"):
        raise RuntimeError("serve email.password_app in config.json")
    dal = (datetime.now() - timedelta(days=giorni)).strftime("%d-%b-%Y")
    M = imaplib.IMAP4_SSL(e.get("imap_host", "imap.gmail.com"))
    M.login(e["utente"], e["password_app"].replace(" ", ""))
    M.select("INBOX", readonly=True)
    _, d = M.search(None, "FROM", "immobiliare.it", "SINCE", dal)
    trovati = {}
    for num in d[0].split():
        _, m = M.fetch(num, "(BODY.PEEK[])")
        msg = email.message_from_bytes(m[0][1])
        oggetto = str(make_header(decode_header(msg["Subject"] or "")))
        for p in msg.walk():
            if p.get_content_type() == "text/plain":
                testo = p.get_payload(decode=True).decode(p.get_content_charset() or "utf-8", "replace")
                nome = re.search(r"per la tua ricerca\s+([^\n]+)", testo)
                ricerca = (nome.group(1) if nome else oggetto.split(":")[-1]).strip()
                for x in _imm_parse(testo):
                    x["ricerca"] = ricerca
                    trovati[x["click"]] = x
    M.logout()
    return list(trovati.values())


def profilo_ricerca(nome):
    """Ricerche salvate sui portali: "famiglia"/"family" nel nome → profilo famiglia."""
    return "famiglia" if re.search(r"famigli|family", nome or "", re.I) else "studenti"


def _imap(cfg):
    import imaplib
    e = cfg["email"]
    if not e.get("password_app"):
        raise RuntimeError("serve email.password_app in config.json")
    M = imaplib.IMAP4_SSL(e.get("imap_host", "imap.gmail.com"))
    M.login(e["utente"], e["password_app"].replace(" ", ""))
    M.select("INBOX", readonly=True)
    return M


def immobiliare_email(cfg, r=None, profilo="studenti"):
    """Profilo "famiglia": solo le ricerche salvate con "famiglia" nel nome;
    profilo "studenti": tutte le altre."""
    r = r or cfg["ricerca"]
    giorni = r.get("immobiliare_email_giorni", 30)
    out, visti = [], set()
    for x in _imm_email(cfg, giorni):
        if profilo_ricerca(x["ricerca"]) != profilo:
            continue
        if not x["prezzo"] or not (r["prezzo_min"] <= x["prezzo"] <= r["prezzo_max"]):
            continue
        if x["locali"] and not (r["locali_min"] <= int(x["locali"]) <= r["locali_max"]):
            continue
        ann_id, url = _imm_url(x["click"])
        if (ann_id or url) in visti:
            continue
        visti.add(ann_id or url)
        out.append(base_record(
            id="immobiliare-" + (ann_id or hashlib.sha1(url.encode()).hexdigest()[:12]),
            fonte="Immobiliare.it", url=url,
            titolo=x["titolo"], indirizzo=x["indirizzo"], prezzo=x["prezzo"],
            mq=x["mq"], locali=x["locali"], bagni=x["bagni"]))
    geocode_all(out)
    log(AGENT, f"Immobiliare.it {profilo} (avvisi email ultimi {giorni} giorni): {len(out)} annunci nel range")
    return out


# -------------------------------------------- Casa.it (avvisi email via IMAP)
def _casa_email_parse(h):
    """Avviso Casa.it (HTML): "per la tua ricerca <nome>", poi per ogni annuncio
    titolo, "€ <prezzo>", "<mq> m²", "<n> locali", "<n> bagni", "Vedi N foto"."""
    righe = [x.strip() for x in htmlmod.unescape(re.sub(r"<[^>]+>", "\n", re.sub(
        r"<style.*?</style>", "", h, flags=re.S))).splitlines() if x.strip()]
    testo = "\n".join(righe)
    nome = re.search(r"per la tua ricerca\s+([^\n]+)", testo)
    link = list(dict.fromkeys(re.findall(r"https://www\.casa\.it/immobili/(\d+)/", h)))
    out = []
    for i, b in enumerate(re.finditer(
            r"(?P<titolo>[^\n]+(?:\n[^\n€]+)?)\n€\n(?P<prezzo>[\d.]+)\n(?P<corpo>.*?)Vedi \d+ foto", testo, re.S)):
        corpo = b["corpo"]
        g = lambda rx: re.search(rx, corpo)  # noqa: E731
        mq, loc, bag = g(r"(\d+)\s*m²"), g(r"(\d+)\s*local"), g(r"(\d+)\s*bagn")
        titolo = " ".join(b["titolo"].split("\n")[-2:]) if "\n" in b["titolo"] else b["titolo"]
        out.append(dict(
            id=link[i] if i < len(link) else None, titolo=titolo,
            indirizzo=re.sub(r"^.*? in vendita (?:in )?", "", titolo).replace(" (MI)", ""),
            prezzo=_num_it(b["prezzo"]), mq=_num(mq.group(1)) if mq else None,
            locali=loc.group(1) if loc else None, bagni=bag.group(1) if bag else None,
            box=bool(re.search(r"posti? auto|box", corpo)),
            ricerca=(nome.group(1).strip() if nome else "")))
    return out


def casa_email(cfg, r=None, profilo="studenti"):
    import email
    from datetime import datetime, timedelta
    r = r or cfg["ricerca"]
    giorni = r.get("immobiliare_email_giorni", 30)
    M = _imap(cfg)
    dal = (datetime.now() - timedelta(days=giorni)).strftime("%d-%b-%Y")
    _, d = M.search(None, "FROM", "noreply@casa.it", "SINCE", dal)
    trovati = {}
    for num in d[0].split():
        _, m = M.fetch(num, "(BODY.PEEK[])")
        for p in email.message_from_bytes(m[0][1]).walk():
            if p.get_content_type() == "text/html":
                for x in _casa_email_parse(p.get_payload(decode=True).decode(
                        p.get_content_charset() or "utf-8", "replace")):
                    if x["id"]:
                        trovati[x["id"]] = x
    M.logout()
    out = []
    for x in trovati.values():
        if profilo_ricerca(x["ricerca"]) != profilo:
            continue
        if not x["prezzo"] or not (r["prezzo_min"] <= x["prezzo"] <= r["prezzo_max"]):
            continue
        if x["locali"] and not (r["locali_min"] <= int(x["locali"]) <= r["locali_max"]):
            continue
        out.append(base_record(
            id=f"casa-{x['id']}", fonte="Casa.it", url=f"https://www.casa.it/immobili/{x['id']}/",
            titolo=x["titolo"], indirizzo=x["indirizzo"], prezzo=x["prezzo"], mq=x["mq"],
            locali=x["locali"], bagni=x["bagni"], box=1 if x["box"] else None))
    geocode_all(out)
    log(AGENT, f"Casa.it {profilo} (avvisi email ultimi {giorni} giorni): {len(out)} annunci nel range")
    return out
