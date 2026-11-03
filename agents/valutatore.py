"""AGENTE VALUTATORE: valuta ogni annuncio come farebbe un investitore che
compra per affittare a studenti. Sei criteri (0-100), pesati da config.json:

  valore      €/mq rispetto alla mediana dello stesso quartiere (NIL) o zona universitaria
  rendimento  rendimento netto stimato (canone reale di quartiere, spese, tasse)
  posizione   distanza dall'università, numero di atenei vicini, metro
  stato       condizioni dell'immobile + classe energetica
  costi       costi accessori d'acquisto e spese ricorrenti
  dimensione  taglio ideale per l'affitto a studenti (monolocale 28-40 mq, bilocale 40-60)
"""
from datetime import datetime

from .common import load_config, load_json, log, median, percentile, save_json

AGENT = "Valutatore"


def clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


def lin(x, x0, x1):
    """0 a x0, 100 a x1 (anche con x1 < x0)."""
    return clamp(100 * (x - x0) / (x1 - x0))


PRUDENZA = 0.92  # canone richiesto negli annunci ≠ canone effettivamente spuntato


def canone_stimato(a, canoni, c, canoni_nil=None):
    """40° percentile dei canoni di affitti con taglio simile (±8 mq) nello stesso
    quartiere (NIL); se il campione è scarso il €/mq di quartiere, poi gli stessi
    due calcoli sulla zona universitaria (solo entro 2 km dall'ateneo: più lontano
    i canoni non sono rappresentativi), infine il default."""
    mq = a["mq"]
    candidati = [((canoni_nil or {}).get(a.get("nil")) or [], "nel quartiere")]
    if a.get("distanza_uni_km", 0) <= 2.0:
        candidati.append((canoni.get(a["zona_universitaria"], []), "in zona universitaria"))
    for serie, dove in candidati:
        simili = [p for p, m in serie if abs(m - mq) <= 8]
        if len(simili) >= 6:
            canone = percentile(simili, 0.4) * PRUDENZA
            metodo = f"40° percentile di {len(simili)} affitti simili {dove}"
            break
        if len(serie) >= 8:
            canone = percentile([p / m for p, m in serie], 0.4) * mq * PRUDENZA
            metodo = f"€/mq mediano di {len(serie)} affitti {dove}"
            break
    else:
        canone = c["affitto_eur_mq_default"] * mq * PRUDENZA
        metodo = "stima di default (pochi affitti in zona)"
    return round(canone / 10) * 10, round(canone / mq, 1), metodo


def mediana_zona(a, ctx):
    """€/mq di riferimento: quartiere (NIL) se ci sono almeno 5 annunci, poi zona
    universitaria (entro 2 km), poi tutta la ricerca."""
    return (ctx.get("mediana_nil", {}).get(a.get("nil"))
            or (ctx["mediana_eur_mq"].get(a["zona_universitaria"]) if a.get("distanza_uni_km", 0) <= 2.0 else None)
            or ctx["mediana_globale"])


def costi_acquisto(a, c):
    p = a["prezzo"]
    locato = any(s["etichetta"].startswith("Già locato") for s in a["segnali"])
    ag = p * c["agenzia_pct"] / 100 * (1 + c["iva_agenzia_pct"] / 100) if a.get("agenzia") else 0
    imposte = p * c["imposte_acquisto_pct_prezzo"] / 100
    # se è già locato si compra il reddito in essere: niente lavori/arredo immediati
    lavori = 0 if locato else c["ristrutturazione_eur_mq"].get(a["stato_norm"], 300) * a["mq"]
    arredo = 0 if (a.get("arredato") or locato) else c["arredo_eur"]
    return {
        "agenzia": round(ag), "imposte": round(imposte), "notaio": c["notaio_eur"],
        "lavori": round(lavori), "arredo": arredo,
        "totale_accessori": round(ag + imposte + c["notaio_eur"] + lavori + arredo),
    }


def valuta(a, ctx, cfg):
    c = cfg["costi"]
    p = a["prezzo"]
    acq = costi_acquisto(a, c)
    investimento = p + acq["totale_accessori"]
    canone, eur_mq_aff, metodo_canone = canone_stimato(a, ctx["canoni"], c, ctx.get("canoni_nil"))
    spese_mese = a.get("spese_condominio_mese")
    spese_stimate = spese_mese is None
    if spese_stimate:
        spese_mese = c["spese_condominio_mese_default"] + (0.6 * max(0, a["mq"] - 30))
    lordo_anno = canone * 12 * (1 - c["sfitto_pct"] / 100)
    imu = p * c["imu_pct_prezzo"] / 100
    tasse = canone * 12 * c["tassazione_affitto_pct"] / 100
    # il proprietario sostiene circa il 30% delle spese condominiali (straordinarie,
    # quota proprietà); il resto è ribaltato sull'inquilino
    costi_anno = imu + tasse + c["assicurazione_anno_eur"] + spese_mese * 12 * 0.3
    netto_anno = lordo_anno - costi_anno
    rend_lordo = 100 * canone * 12 / p
    rend_netto = 100 * netto_anno / investimento

    # --- punteggi -------------------------------------------------------
    med_zona = mediana_zona(a, ctx)
    sconto = 100 * (1 - a["prezzo_mq"] / med_zona)
    s_valore = clamp(50 + sconto * 1.6)                     # -30% → 0, +30% → 100

    s_rend = lin(rend_netto, 2.0, 6.0)                       # 2% → 0, 6% → 100

    d = a["distanza_uni_km"]
    vicine = sum(1 for u in a["universita_vicine"] if u["km"] <= 1.5)
    s_pos = lin(d, 1.6, 0.3) * 0.75 + min(vicine, 3) / 3 * 15
    if any(s["etichetta"] == "Vicino metro" for s in a["segnali"]) or a.get("metro_vicina"):
        s_pos += 10
    if not a.get("pin_preciso"):
        s_pos -= 3  # posizione approssimativa sul portale
    s_pos = clamp(s_pos)

    s_stato = {"nuovo": 95, "ottimo": 85, "buono": 60, "sconosciuto": 45,
               "da ristrutturare": 25}[a["stato_norm"]]
    ce = (a.get("classe_energetica") or "").upper()[:1]
    s_stato += {"A": 10, "B": 7, "C": 4, "D": 0, "E": -3, "F": -6, "G": -8}.get(ce, 0)
    for sg in a["segnali"]:
        if sg["etichetta"] in ("Seminterrato",):
            s_stato -= 20
        elif sg["etichetta"].startswith("Piano terra"):
            s_stato -= 8
    s_stato = clamp(s_stato)

    acc_pct = 100 * acq["totale_accessori"] / p
    s_costi = clamp(lin(acc_pct, 22, 6) * 0.6 + lin(spese_mese, 220, 50) * 0.4)

    mq = a["mq"]
    lo, hi = (40, 60) if str(a.get("locali") or "1") == "2" else (28, 40)
    if lo <= mq <= hi:
        s_dim = 100
    elif mq < lo:
        s_dim = clamp(100 - (lo - mq) * 8)
    else:
        s_dim = clamp(100 - (mq - hi) * 4)

    pesi = cfg["pesi"]
    punteggi = {"valore": s_valore, "rendimento": s_rend, "posizione": s_pos,
                "stato": s_stato, "costi": s_costi, "dimensione": s_dim}
    totale = sum(punteggi[k] * pesi[k] for k in pesi) / sum(pesi.values())
    # penalità per criticità
    penal = 0
    for sg in a["segnali"]:
        if sg["etichetta"].startswith("Possibile non residenziale"):
            penal += 8
        elif sg["etichetta"] == "Soppalco":
            penal += 2
    if any(sg["etichetta"].startswith("Già locato") for sg in a["segnali"]):
        totale += 2
    totale = clamp(totale - penal)

    pro, contro = [], []
    if sconto >= 8:
        pro.append(f"€/mq {sconto:.0f}% sotto la mediana di zona")
    elif sconto <= -10:
        contro.append(f"€/mq {-sconto:.0f}% sopra la mediana di zona")
    if rend_netto >= 4.5:
        pro.append(f"rendimento netto stimato {rend_netto:.1f}%")
    elif rend_netto < 3:
        contro.append(f"rendimento netto basso ({rend_netto:.1f}%)")
    if d <= 0.6:
        pro.append(f"a {int(d * 1000)} m da {a['zona_universitaria']}")
    if vicine >= 2:
        pro.append(f"{vicine} atenei entro 1,5 km")
    if a["stato_norm"] == "da ristrutturare":
        contro.append(f"da ristrutturare (~{acq['lavori']:,} € di lavori)".replace(",", "."))
    if spese_mese and not spese_stimate and spese_mese > 180:
        contro.append(f"spese condominiali alte ({spese_mese} €/mese)")
    if ce in ("F", "G"):
        contro.append(f"classe energetica {ce}")
    for sg in a["segnali"]:
        (pro if sg["tipo"] == "positivo" else contro).append(sg["etichetta"])

    giudizio = ("Ottimo affare" if totale >= 72 else "Interessante" if totale >= 60
                else "Nella media" if totale >= 48 else "Debole")
    a["valutazione"] = {
        "punteggio": round(totale, 1), "giudizio": giudizio,
        "punteggi": {k: round(v) for k, v in punteggi.items()},
        "canone_stimato": canone, "canone_eur_mq": eur_mq_aff,
        "metodo_canone": metodo_canone,
        "rendimento_lordo": round(rend_lordo, 2), "rendimento_netto": round(rend_netto, 2),
        "investimento_totale": round(investimento), "costi_acquisto": acq,
        "spese_condominio_mese": round(spese_mese), "spese_stimate": spese_stimate,
        "costi_annui": round(costi_anno), "netto_annuo": round(netto_anno),
        "mediana_zona_eur_mq": round(med_zona), "sconto_vs_zona_pct": round(sconto, 1),
        "pro": pro, "contro": contro,
    }
    return a


def run():
    cfg = load_config()
    cat = load_json("catalogo.json")
    annunci = cat["annunci"]
    per_zona, per_nil = {}, {}
    for a in annunci:
        per_zona.setdefault(a["zona_universitaria"], []).append(a["prezzo_mq"])
        if a.get("nil"):
            per_nil.setdefault(a["nil"], []).append(a["prezzo_mq"])
    ctx = {
        "canoni": cat["canoni_eur_mq"], "canoni_nil": cat.get("canoni_nil", {}),
        "mediana_eur_mq": {z: median(v) for z, v in per_zona.items() if len(v) >= 5},
        "mediana_nil": {z: median(v) for z, v in per_nil.items() if len(v) >= 5},
        "mediana_globale": median([a["prezzo_mq"] for a in annunci]),
    }
    valutati = sorted((valuta(a, ctx, cfg) for a in annunci),
                      key=lambda a: -a["valutazione"]["punteggio"])
    for i, a in enumerate(valutati, 1):
        a["posizione_classifica"] = i

    # mantiene selezioni e stato email già esistenti
    prec = load_json("classifica.json", {}) or {}
    storico = load_json("storico.json", {})
    for a in valutati:
        h = storico.get(a["id"], {})
        a["prima_vista"] = h.get("prima_vista")
        a["storico_prezzi"] = h.get("prezzi", [])
    prev_ids = {a["id"] for a in prec.get("top", [])}
    top = valutati[:20]
    for a in top:
        a["nuovo_in_top"] = bool(prev_ids) and a["id"] not in prev_ids

    zone = {}
    for z in sorted(set(per_zona)):
        serie = cat["canoni_eur_mq"].get(z, [])
        zone[z] = {"annunci": len(per_zona[z]),
                   "mediana_eur_mq": round(median(per_zona[z])),
                   "canone_eur_mq": round(median([p / m for p, m in serie]), 1) if serie else None,
                   "canone_mediano": round(median([p for p, m in serie])) if serie else None,
                   "campione_affitti": len(serie)}
    save_json("classifica.json", {
        "aggiornato": datetime.now().isoformat(timespec="seconds"),
        "dati_raccolti": cat["aggiornato"],
        "per_fonte": cat.get("per_fonte", {}),
        "totale_valutati": len(valutati),
        "scartati": cat["scartati"],
        "zone": zone,
        "top": top,
        "altri": valutati[20:],
    })
    log(AGENT, f"valutati {len(valutati)} annunci; migliore: "
               f"{top[0]['titolo']} ({top[0]['valutazione']['punteggio']})" if top else
               "nessun annuncio da valutare")
    return len(valutati)


if __name__ == "__main__":
    run()
