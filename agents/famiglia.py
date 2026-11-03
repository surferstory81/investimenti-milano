"""PROFILO FAMIGLIA: appartamenti in vendita a Milano e prima cintura per una
famiglia di 5 persone. Requisiti: almeno 3 camere da letto, 2 bagni, salone,
cucina abitabile. Plus: terrazzo, balcone, box, aria condizionata, domotica,
ristrutturato. Parametri in config.json → famiglia.

Fonti: Subito.it (provincia), Tecnocasa, Gabetti, Dove.it (Milano + comuni
della cintura) e Casavo via HTTP; Immobiliare.it dagli avvisi email delle ricerche salvate con "famiglia"
nel nome. Uso: python3 -m agents.famiglia [--report]"""
import html
import json
import re
import sys
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

from . import fonti, fonti_extra, preferiti, verifiche, zone
from .catalogatore import duplicati, segnali, stato_norm
from .common import DATA, haversine_km, http_get, load_config, load_json, log, median, save_json
from .mailer import smtp_connessione

AGENT = "Famiglia"
FONTI_EMAIL = ("Immobiliare.it", "Casa.it", "Idealista")  # annunci dagli avvisi: senza descrizione
CENTRO = (45.4642, 9.1900)  # Duomo
SUBITO = "https://www.subito.it/annunci-lombardia/vendita/appartamenti/{prov}/"
TECNOCASA = "https://www.tecnocasa.it/annunci/immobili/lombardia/{comune}.html"

NUMERI = {"due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6}
_N = r"(\d|due|tre|quattro|cinque|sei)"

# (chiave, etichetta, regex sul testo dell'annuncio)
REQUISITI = [
    ("salone", "Salone", r"salone|doppio soggiorno|soggiorno doppio|ampio (?:soggiorno|living)|living"),
    ("cucina_abitabile", "Cucina abitabile",
     r"cucina abitabile|cucina (?:separata|indipendente)|tinello|cucina con zona pranzo"),
]
PLUS = [
    ("terrazzo", "Terrazzo", r"terrazz"),
    ("balcone", "Balcone", r"balcon|loggia"),
    ("box", "Box", r"\bbox\b(?!\s*doccia)|garage|autorimessa|posto auto"),
    ("aria_condizionata", "Aria condizionata",
     r"(?<!predisposizione )(?<!predisposizione per )(?<!predisposizione all')(?:aria condizionata|climatizzat|condizionator)"),
    ("domotica", "Domotica", r"domotic|smart home|\bknx\b"),
    ("ristrutturato", "Ristrutturato", r"ristrutturat|rinnovat|nuova costruzione"),
]
# plus per i bambini (spazi del complesso/condominio)
BIMBI = [
    ("piscina", "Piscina", r"piscin"),
    ("area_giochi", "Area giochi / campi",
     r"(?:parco|area|zona|spazio) (?:giochi|bimbi|bambini)|playground|giochi per bambini|ludoteca|"
     r"camp[oi] (?:da |di )?(?:calcio|calcetto|tennis|basket|pallavolo|padel|gioco)"),
    ("spazi_comuni", "Spazi comuni attrezzati",
     r"palestra (?:condominiale|comune|interna)|sala (?:comune|polifunzionale|feste|condominiale|hobby)|"
     r"spazi comuni attrezzat|kids room|area fitness|club house|clubhouse|co-?working condominiale"),
    ("giardino_condominiale", "Giardino condominiale",
     r"giardino condominiale|parco condominiale|(?:area|spazio) verde (?:condominiale|comune)"),
]
# fasce di posizione: (etichetta, km max dal Duomo, punteggio 0..1); fuori Milano = cintura
ZONE = [("Centro", 2.5, 1.0), ("Semicentro", 5.0, 0.75), ("Periferia Milano", 99, 0.4)]
CINTURA = ("Cintura", 0.15)


def _n(x):
    try:
        return int(str(x).strip().split()[0])
    except (TypeError, ValueError, IndexError):
        return None


def _da_testo(rx, testo):
    m = re.search(rx, testo)
    return NUMERI.get(m.group(1), None) or _n(m.group(1)) if m else None


# ------------------------------------------------------------------ raccolta
def subito(f):
    out = []
    for prov in f["subito_province"]:
        params = f"?rs={f['locali_min']}&ps={f['prezzo_min']}&pe={f['prezzo_max']}"
        page, pages = 1, 1
        while page <= min(pages, f["max_pagine"]):
            url = SUBITO.format(prov=prov) + params + (f"&o={page}" if page > 1 else "")
            try:
                h = http_get(url)
                m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S)
                items = json.loads(m.group(1))["props"]["pageProps"]["initialState"]["items"]
            except Exception as e:
                log(AGENT, f"Subito {prov} pagina {page}: errore {e}")
                break
            pages = items.get("totalPages") or 1
            out += [fonti._subito_item(i) for i in items.get("originalList", [])
                    if i.get("kind") == "AdItem"]
            if page % 10 == 0 or page == pages:
                log(AGENT, f"Subito {prov}: pagina {page}/{pages}, annunci finora {len(out)}")
            page += 1
    return out


def tecnocasa(f):
    cards = []
    for comune in f["tecnocasa_comuni"]:
        page, pages = 1, 1
        while page <= min(pages, f["max_pagine"]):
            url = TECNOCASA.format(comune=comune) + (f"/pag-{page}" if page > 1 else "")
            try:
                h = http_get(url, delay=(1.0, 2.0))
                est = fonti._vue_attr(h, "estates") or []
                pages = (fonti._vue_attr(h, "pagination") or {}).get("total_pages", 1)
            except Exception as e:
                log(AGENT, f"Tecnocasa {comune} pagina {page}: errore {e}")
                break
            cards += [x for x in est if "appartament" in (x.get("detail_url") or "")
                      and (_n(x.get("rooms")) or 0) >= f["locali_min"]]
            page += 1
        log(AGENT, f"Tecnocasa {comune}: {pages} pagine, candidati finora {len(cards)}")

    out = []
    for x in cards:
        prezzo = fonti._num_it(re.sub(r"[^\d.]", "", x.get("price") or ""))
        if not prezzo or not (f["prezzo_min"] <= prezzo <= f["prezzo_max"]):
            continue
        rec = fonti.base_record(
            id=f"tecnocasa-{x['id']}", fonte="Tecnocasa", url=x.get("detail_url"),
            titolo=f"{x.get('title', '')} — {x.get('subtitle', '')}",
            indirizzo=(x.get("subtitle") or "").replace(" - ", ", "),
            prezzo=prezzo, mq=fonti._num(re.sub(r"[^\d]", "", x.get("surface") or "")),
            locali=str(_n(x.get("rooms"))),
            immagini=[i["url"]["gallery"] for i in (x.get("images") or [])[:8]
                      if (i.get("url") or {}).get("gallery")])
        try:
            rec = fonti._tecnocasa_detail(rec["url"], rec)
        except Exception as e:
            log(AGENT, f"Tecnocasa dettaglio {x['id']}: {e}")
        out.append(rec)
    fonti.geocode_all(out)
    return out


# ------------------------------------------------------------------ analisi
def caratteristiche(a):
    testo = f"{a.get('titolo') or ''}\n{a.get('descrizione') or ''}".lower()
    # gli avvisi email non hanno descrizione (Idealista solo un estratto troncato):
    # quello che vi si trova conta, ma l'assenza di salone/cucina non è un'informazione
    # (salvo che l'utente abbia importato la pagina dell'annuncio: agents/verifiche.py)
    car = {"testo": len(a.get("descrizione") or "") >= 80
           and (a.get("fonte") not in FONTI_EMAIL or bool(a.get("verificato")))}
    camere = _n(a.get("camere")) or _da_testo(_N + r"[ \t]+(?:ampie\s+|grandi\s+)?camer[ae]", testo)
    car["camere_stimate"] = camere is None
    if camere is None and _n(a.get("locali")):
        camere = max(_n(a["locali"]) - 1, 1)  # sugli annunci Tecnocasa: 4 locali ≈ salone + 3 camere
    car["camere"] = camere
    bagni = _n(a.get("bagni")) or _da_testo(_N + r"[ \t]+(?:bagni|servizi)", testo)
    if bagni is None and re.search(r"doppi servizi|doppio bagno", testo):
        bagni = 2
    car["bagni"] = bagni
    for k, _, rx in REQUISITI + PLUS + BIMBI:
        car[k] = bool(re.search(rx, testo))
    car["terrazzo"] |= bool(a.get("terrazzi"))
    car["balcone"] |= bool(a.get("balcone"))
    car["box"] |= bool(a.get("box"))
    car["aria_condizionata"] |= bool(a.get("aria_condizionata"))
    car["piscina"] |= bool(a.get("piscina"))
    car["giardino_condominiale"] |= "condominial" in (a.get("giardino") or "").lower()
    st = stato_norm(a.get("stato"), testo)
    car["ristrutturato"] |= st in ("ottimo", "nuovo") or bool(a.get("anno_ristrutturazione"))
    car["stato"] = st
    return car


def zona(a):
    if (a.get("comune") or "Milano").lower() != "milano":
        return CINTURA
    for nome, km, punti in ZONE:
        if a["km_centro"] <= km:
            return nome, punti


def valuta(a, med_comune, f):
    c = a["caratteristiche"]
    p = f["pesi"]
    s = {}
    a["zona"], punti = zona(a)
    s["posizione"] = p["posizione"] * punti
    # requisiti
    cam = c["camere"] or 0
    s["camere"] = p["camere"] * (1 if cam >= f["camere_min"] else 0.3 if cam == f["camere_min"] - 1 else 0)
    if c["camere_stimate"]:
        s["camere"] *= 0.7
    s["bagni"] = p["bagni"] * (1 if (c["bagni"] or 0) >= f["bagni_min"] else 0.4 if c["bagni"] is None else 0)
    # senza descrizione salone e cucina non si possono verificare: metà punteggio
    ignoto = 0.5 if not c.get("testo", True) else 0
    s["salone"] = p["salone"] * (1 if c["salone"] else ignoto)
    s["cucina_abitabile"] = p["cucina_abitabile"] * (1 if c["cucina_abitabile"] else ignoto)
    # plus
    for k, _, _ in PLUS + BIMBI:
        s[k] = p[k] * c[k]
    # prezzo al mq rispetto alla mediana del comune (±20% → 0..1)
    med = med_comune.get(a["comune"]) or med_comune.get("_tutti")
    if a.get("prezzo_mq") and med:
        sconto = 1 - a["prezzo_mq"] / med
        s["prezzo"] = p["prezzo"] * max(0, min(1, 0.5 + sconto * 2.5))
        a["sconto_zona_pct"] = round(100 * sconto, 1)
    else:
        s["prezzo"] = p["prezzo"] * 0.5
    # metratura: pieno da mq_ideale in su
    mq = a.get("mq") or 0
    s["metratura"] = p["metratura"] * max(0, min(1, (mq - f["mq_min"]) / max(1, f["mq_ideale"] - f["mq_min"])))
    tot = sum(p.values())
    a["punteggi"] = {k: round(v, 1) for k, v in s.items()}
    a["punteggio"] = round(100 * sum(s.values()) / tot, 1)
    req = (("camere", f"{f['camere_min']}+ camere"), ("bagni", f"{f['bagni_min']} bagni"),
           ("salone", "Salone"), ("cucina_abitabile", "Cucina abitabile"))
    da_verificare = {"salone", "cucina_abitabile"} if ignoto else set()
    if c["camere_stimate"] and (c["camere"] or 0) >= f["camere_min"]:
        da_verificare.add("camere")
    if c["bagni"] is None:
        da_verificare.add("bagni")
    a["da_verificare"] = [et for k, et in req if k in da_verificare]
    a["mancano"] = [et for k, et in req if s[k] < p[k] and et not in a["da_verificare"]]
    a["plus"] = [et for k, et, _ in PLUS if c[k]]
    a["plus_bimbi"] = [et for k, et, _ in BIMBI if c[k]]


def _comune(a):
    ind = a.get("indirizzo") or ""
    parti = [x.strip() for x in ind.split(",") if x.strip()]
    for x in reversed(parti):
        if not re.search(r"\d|^via |^viale |^piazza |^corso ", x.lower()):
            return x
    return "Milano"


def run(report=False, solo_valuta=False):
    cfg = load_config()
    f = cfg["famiglia"]
    raccolti, per_fonte = [], {}
    if solo_valuta:
        g = load_json("famiglia_grezzi.json") or {"annunci": [], "per_fonte": {}}
        raccolti, per_fonte = g["annunci"], g["per_fonte"]

    def add(nome, fn):
        try:
            res = fn()
        except Exception as e:
            log(AGENT, f"{nome}: fonte non disponibile ({e})")
            res = []
        per_fonte[nome] = len(res)
        raccolti.extend(res)

    if not solo_valuta:
        _raccogli(cfg, f, add)
        save_json("famiglia_grezzi.json", {"per_fonte": per_fonte, "annunci": raccolti})

    importati = load_json(verifiche.FILE, {})
    zone_scelte = f.get("zone")  # {"Solari, Washington": [NIL, ...]}: come sui portali
    if zone.verifica_config(zone_scelte):
        log(AGENT, f"famiglia.zone: NIL inesistenti {zone.verifica_config(zone_scelte)}")
    tenuti, scartati = [], 0
    for a in raccolti:
        verifiche.applica(a, importati)
        if not (a.get("prezzo") and a.get("mq") and a.get("lat")):
            scartati += 1
            continue
        a["km_centro"] = round(haversine_km(a["lat"], a["lon"], *CENTRO), 1)
        if zone_scelte:
            a["zona_scelta"] = zone.zona_scelta(a["lat"], a["lon"], zone_scelte)
            if not a["zona_scelta"]:
                scartati += 1
                continue
        # per una famiglia un immobile già affittato è un problema, non un plus
        a["segnali"] = [dict(x, etichetta="Occupato / già locato", tipo="attenzione")
                        if x["etichetta"].startswith("Già locato") else x
                        for x in segnali(a) if not x["etichetta"].startswith(("Target studenti", "Sotto 28"))]
        if ((not zone_scelte and a["km_centro"] > f["raggio_km"]) or a["mq"] < f["mq_min"]
                or not (f["prezzo_min"] <= a["prezzo"] <= f["prezzo_max"])
                or any(x["tipo"] == "esclusione" for x in a["segnali"])):
            scartati += 1
            continue
        a["caratteristiche"] = caratteristiche(a)
        c = a["caratteristiche"]
        if (c["bagni"] is not None and c["bagni"] < f["bagni_min"]) or \
                (not c["camere_stimate"] and (c["camere"] or 0) < f["camere_min"] - 1):
            scartati += 1
            continue
        a["prezzo_mq"] = round(a["prezzo"] / a["mq"])
        a["comune"] = a.get("comune") or _comune(a)
        tenuti.append(a)
    tenuti = duplicati(tenuti)

    gruppi = {}
    for a in tenuti:
        gruppi.setdefault(a["comune"], []).append(a["prezzo_mq"])
    med_comune = {k: median(v) for k, v in gruppi.items() if len(v) >= 5}
    med_comune["_tutti"] = median([a["prezzo_mq"] for a in tenuti])
    for a in tenuti:
        valuta(a, med_comune, f)

    now = datetime.now().isoformat(timespec="seconds")
    storico = load_json("famiglia_storico.json", {})
    for a in tenuti:
        h = storico.setdefault(a["id"], {"prima_vista": now, "prezzi": []})
        if not h["prezzi"] or h["prezzi"][-1]["prezzo"] != a["prezzo"]:
            h["prezzi"].append({"data": now, "prezzo": a["prezzo"]})
        h["ultima_vista"] = now
        a["prima_vista"] = h["prima_vista"]
        a["prezzi_storico"] = h["prezzi"]
    save_json("famiglia_storico.json", storico)

    tenuti.sort(key=lambda a: -a["punteggio"])
    scartati_utente = preferiti.ids("famiglia", "scartato")  # "Scarta" dalla pagina
    tenuti = [a for a in tenuti if a["id"] not in scartati_utente]
    preferiti.aggiorna("famiglia", tenuti)
    n = f.get("top", 30)
    avvisi = [a for a in tenuti if a["fonte"] in FONTI_EMAIL]
    save_json("famiglia.json", {"aggiornato": now, "per_fonte": per_fonte,
                                "totale_valutati": len(tenuti), "scartati": scartati,
                                "top": tenuti[:n], "altri": tenuti[n:n + 300], "avvisi": avvisi})
    log(AGENT, f"raccolti {len(raccolti)} ({per_fonte}); valutati {len(tenuti)}, scartati {scartati}; "
               f"migliore: {tenuti[0]['titolo'][:60] if tenuti else '—'} "
               f"({tenuti[0]['punteggio'] if tenuti else 0})")
    if report:
        invia_report(cfg)


def _raccogli(cfg, f, add):
    log(AGENT, "=== avvio ricerca famiglia ===")
    add("Subito.it", lambda: subito(f))
    add("Tecnocasa", lambda: tecnocasa(f))
    comuni = [c.split("/")[-1] for c in f["tecnocasa_comuni"]]
    add("Gabetti", lambda: fonti_extra.gabetti(dict(f, locali_max=99), comuni))
    add("Dove.it", lambda: fonti_extra.dove(dict(f, locali_max=99), comuni))
    add("Casavo", lambda: fonti_extra.casavo(dict(f, locali_max=99)))
    add("Immobiliare.it", lambda: fonti.immobiliare_email(cfg, dict(f, locali_max=99), "famiglia"))
    add("Casa.it (avvisi)", lambda: fonti.casa_email(cfg, dict(f, locali_max=99), "famiglia"))
    add("Idealista (avvisi)", lambda: fonti.idealista_email(cfg, dict(f, locali_max=99), "famiglia"))


# ------------------------------------------------------------------ report
def _eur(x):
    return "—" if x is None else f"{x:,.0f} €".replace(",", ".")


def invia_report(cfg):
    d = load_json("famiglia.json")
    if not d or not d["top"]:
        log(AGENT, "nessun risultato da inviare")
        return False
    e, dest = cfg["email"], cfg["report"]["destinatari"]
    url_dash = cfg["server"].get("url_pubblico", f"http://localhost:{cfg['server']['porta']}")
    data = datetime.fromisoformat(d["aggiornato"]).strftime("%d/%m/%Y")
    oggi = d["aggiornato"][:10]
    top = d["top"][:cfg["famiglia"].get("top_report", 15)]
    nuovi = sum(1 for a in top if a.get("prima_vista", "")[:10] == oggi)
    pref_txt, pref_html, pref_nov = preferiti.sezione_report(preferiti.riepilogo("famiglia", oggi))
    righe_h, righe_t = [pref_html] if pref_html else [], [pref_txt] if pref_txt else []
    for i, a in enumerate(top, 1):
        c = a["caratteristiche"]
        info = (f"{a.get('zona', '')} · {_eur(a['prezzo'])} · {a['mq']:.0f} mq · {c['camere'] or '?'} camere"
                f"{' (stima)' if c['camere_stimate'] else ''} · {c['bagni'] or '?'} bagni · {a['comune']}")
        nuovo = " 🆕" if a.get("prima_vista", "")[:10] == oggi else ""
        righe_t.append(f"{i}. [{a['punteggio']:.0f}] {a['titolo']}{nuovo}\n   {info}\n"
                       f"   Bimbi: {', '.join(a.get('plus_bimbi', [])) or '—'} · Plus: {', '.join(a['plus']) or '—'}\n"
                       f"   {a['url']}\n")
        chips = "".join(f'<span style="background:#e6eefb;color:#2b5aa8;border-radius:99px;padding:1px 8px;'
                        f'margin:0 4px 4px 0;display:inline-block;font-size:12px">{html.escape(p)}</span>'
                        for p in a.get("plus_bimbi", []))
        chips += "".join(f'<span style="background:#e5f3eb;color:#1f7a4d;border-radius:99px;padding:1px 8px;'
                        f'margin:0 4px 4px 0;display:inline-block;font-size:12px">{html.escape(p)}</span>'
                        for p in a["plus"])
        chips += "".join(f'<span style="background:#fbf0dc;color:#a86a00;border-radius:99px;padding:1px 8px;'
                         f'margin:0 4px 4px 0;display:inline-block;font-size:12px">manca: {html.escape(m)}</span>'
                         for m in a["mancano"])
        chips += "".join(f'<span style="background:#f0eee8;color:#5c5b56;border-radius:99px;padding:1px 8px;'
                         f'margin:0 4px 4px 0;display:inline-block;font-size:12px">da verificare: {html.escape(m)}</span>'
                         for m in a.get("da_verificare", []))
        img = (f'<img src="{html.escape(a["immagini"][0])}" width="120" style="border-radius:6px;display:block">'
               if a.get("immagini") else "")
        righe_h.append(f"""<tr style="border-top:1px solid #e3e0d8">
<td style="padding:10px 8px;vertical-align:top;font-weight:700;color:#8b8a84">{i}</td>
<td style="padding:10px 8px;vertical-align:top">{img}</td>
<td style="padding:10px 8px;vertical-align:top"><a href="{html.escape(a['url'])}" style="color:#1f5f4a;font-weight:600">
{html.escape(a['titolo'] or '')}</a>{nuovo}<div style="font-size:13px;color:#5c5b56;margin:3px 0 6px">{html.escape(info)}</div>{chips}</td>
<td style="padding:10px 8px;text-align:right;vertical-align:top;font-size:20px;font-weight:700">{a['punteggio']:.0f}</td></tr>""")
    avvisi = [a for a in d.get("avvisi", []) if a.get("prima_vista", "")[:10] == oggi][:10]
    if avvisi:
        righe_t.append("\nNUOVI DAGLI AVVISI EMAIL (dati parziali, da verificare)\n")
        righe_h.append('<tr><td colspan="4" style="padding:18px 8px 4px;font-weight:700">Nuovi dagli avvisi email '
                       '<span style="font-weight:400;color:#5c5b56;font-size:13px">· dati parziali, da verificare</span></td></tr>')
        for a in avvisi:
            info = f"{a.get('zona', '')} · {_eur(a['prezzo'])} · {a['mq']:.0f} mq · {a.get('locali') or '?'} locali · {a['comune']}"
            righe_t.append(f"- {a['titolo']}\n  {info}\n  {a['url']}\n")
            righe_h.append(f"""<tr style="border-top:1px solid #e3e0d8"><td></td><td></td>
<td style="padding:8px"><a href="{html.escape(a['url'])}" style="color:#1f5f4a;font-weight:600">{html.escape(a['titolo'] or '')}</a>
<div style="font-size:13px;color:#5c5b56">{html.escape(info)} · {html.escape(a['fonte'])}</div></td>
<td style="padding:8px;text-align:right;color:#8b8a84">{a['punteggio']:.0f}</td></tr>""")
    fonti_txt = ", ".join(f"{k} {v}" for k, v in d["per_fonte"].items())
    oggetto = (f"Casa famiglia Milano — {len(top)} migliori del {data}"
               + (f" ({nuovi} {'nuovo' if nuovi == 1 else 'nuovi'})" if nuovi else "")
               + (f" · {pref_nov} novità sui preferiti" if pref_nov else ""))
    testo = (f"Ricerca casa per la famiglia aggiornata il {data}: {d['totale_valutati']} appartamenti valutati.\n"
             f"Fonti: {fonti_txt}\n\n" + "\n".join(righe_t) + f"\nTutti i risultati: {url_dash}/famiglia.html\n")
    corpo = f"""<div style="font-family:system-ui,Segoe UI,Roboto,sans-serif;color:#1d1d1b;max-width:760px">
<h2 style="margin:0 0 4px">Casa per la famiglia · Milano</h2>
<p style="color:#5c5b56;margin:0 0 14px;font-size:13px">Aggiornata il {data} · {d['totale_valutati']} appartamenti valutati ·
Fonti: {html.escape(fonti_txt)}</p><table style="border-collapse:collapse;width:100%">{''.join(righe_h)}</table>
<p style="font-size:13px"><a href="{url_dash}/famiglia.html">Apri tutti i risultati</a></p></div>"""
    msg = EmailMessage()
    msg["From"] = formataddr((e["mittente_nome"], e["utente"]))
    msg["To"] = ", ".join(dest)
    msg["Subject"] = oggetto
    msg["Message-ID"] = make_msgid()
    msg["Date"] = formatdate(localtime=True)
    msg.set_content(testo)
    msg.add_alternative(corpo, subtype="html")
    smtp = smtp_connessione(cfg)
    if not smtp:
        p = DATA / "bozze"
        p.mkdir(exist_ok=True)
        (p / f"famiglia-{datetime.now():%Y%m%d-%H%M}.eml").write_bytes(bytes(msg))
        log(AGENT, "SMTP non configurato: report salvato come bozza")
        return False
    try:
        smtp.send_message(msg)
    finally:
        smtp.quit()
    log(AGENT, f"report famiglia inviato a {', '.join(dest)}")
    return True


if __name__ == "__main__":
    run(report="--report" in sys.argv, solo_valuta="--solo-valuta" in sys.argv)
