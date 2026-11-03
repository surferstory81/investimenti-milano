"""AGENTE CATALOGATORE: normalizza gli annunci grezzi di tutte le fonti,
estrae informazioni dal testo (spese condominiali, email, telefono, criticità),
elimina i doppioni tra portali e assegna ogni annuncio a una categoria."""
import re

from .common import haversine_km, load_json, log, save_json

AGENT = "Catalogatore"

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:\+39[\s.]?)?(?:0\d{1,3}|3\d{2})[\s./-]?\d{2,4}[\s./-]?\d{2,4}[\s./-]?\d{0,4}")

# (regex, etichetta, gravità: "esclusione" | "attenzione" | "positivo")
SEGNALI = [
    (r"\bnuda propriet", "Nuda proprietà", "esclusione"),
    (r"\basta\b|aste giudiziarie|vendita giudiziaria|tribunale", "Asta giudiziaria", "esclusione"),
    (r"\busufrutto\b", "Usufrutto", "esclusione"),
    (r"\bin affitto\b.*\bproponiamo in locazione\b|\bsolo affitto\b", "Annuncio d'affitto", "esclusione"),
        (r"seminterrat|\bpiano -1\b|interrato", "Seminterrato", "attenzione"),
    (r"piano terra|piano rialzato|\bpiano 0\b|\bpt\b", "Piano terra/rialzato", "attenzione"),
    (r"\bsoppalc", "Soppalco", "attenzione"),
    (r"\bc/2\b|categoria c2|\bmagazzino\b|\bdeposito\b|\blaboratorio\b|uso ufficio|\bc/1\b|\bnegozio\b",
     "Possibile non residenziale (C/2, ufficio)", "attenzione"),
    (r"non abitabil|senza abitabilit", "Non abitabile", "esclusione"),
    (r"\b(?:attualmente |gi[aà] )?(?:locato|affittato|occupato)\b(?! da subito)|messo a reddito|con inquilino|contratto (?:di locazione )?in essere",
     "Già locato (reddito immediato)", "positivo"),
    (r"cantina", "Cantina", "positivo"),
    (r"portineria|portiere|custode", "Portineria", "positivo"),
    (r"\bm[1-5]\b|metropolitana|\bmm\d?\b", "Vicino metro", "positivo"),
    (r"terrazz", "Terrazzo", "positivo"),
    (r"cedolare|canone concordato|studenti", "Target studenti citato", "positivo"),
]

STATI = [
    ("da ristrutturare", "da ristrutturare"), ("ristrutturar", "da ristrutturare"),
    ("nuov", "nuovo"), ("ottimo", "ottimo"), ("ristrutturat", "ottimo"),
    ("buono", "buono"), ("abitabile", "buono"),
]


def stato_norm(stato, testo):
    s = (stato or "").lower()
    for k, v in STATI:
        if k in s:
            return v
    t = testo.lower()
    if re.search(r"da ristrutturare|da rimodernare|necessita di (?:interventi|lavori)", t):
        return "da ristrutturare"
    if re.search(r"nuova costruzione|mai abitat|classe a\d?\b", t):
        return "nuovo"
    if re.search(r"ristrutturat|rinnovat|ottimo stato|ottime condizioni", t):
        return "ottimo"
    if re.search(r"buono stato|buone condizioni|abitabile", t):
        return "buono"
    return "sconosciuto"


def _eur(s):
    s = s.replace(" ", "")
    s = re.sub(r",\d{2}$", "", s)
    s = s.replace(".", "").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def estrai_spese_mese(testo):
    """Cerca le spese condominiali nel testo e restituisce €/mese."""
    t = testo.replace("\n", " ")
    for m in re.finditer(r"spese[^.]{0,60}?(?:€|euro|eur)\.?\s*([\d.,]+)[^.]{0,25}", t, re.I):
        v = _eur(m.group(1))
        ctx = m.group(0).lower()
        if not v:
            continue
        if re.search(r"ann|/a\b|all'anno|l'anno", ctx) or v > 400:
            v = v / 12
        if 15 <= v <= 600:
            return round(v)
    m = re.search(r"spese[^.]{0,40}?([\d.,]+)\s*(?:€|euro)[^.]{0,20}", t, re.I)
    if m:
        v = _eur(m.group(1))
        if v:
            if re.search(r"ann", m.group(0), re.I) or v > 400:
                v /= 12
            if 15 <= v <= 600:
                return round(v)
    return None


def segnali(a):
    testo = f"{a.get('titolo') or ''} {a.get('descrizione') or ''} {a.get('piano') or ''}".lower()
    out = []
    for rx, etichetta, tipo in SEGNALI:
        if etichetta and re.search(rx, testo):
            out.append({"etichetta": etichetta, "tipo": tipo})
    if a.get("asta"):
        out.append({"etichetta": "Asta giudiziaria", "tipo": "esclusione"})
    tp = (a.get("tipo_proprieta") or "").lower()
    if "nuda" in tp:
        out.append({"etichetta": "Nuda proprietà", "tipo": "esclusione"})
    if a.get("libero") == "No":
        out.append({"etichetta": "Già locato (reddito immediato)", "tipo": "positivo"})
    if a.get("mq") and a["mq"] < 28:
        out.append({"etichetta": f"Sotto 28 mq: verificare abitabilità", "tipo": "attenzione"})
    if a.get("prezzo_precedente") and a["prezzo_precedente"] > (a.get("prezzo") or 0):
        calo = 100 * (1 - a["prezzo"] / a["prezzo_precedente"])
        out.append({"etichetta": f"Prezzo ribassato del {calo:.0f}%", "tipo": "positivo"})
    # dedup per etichetta
    seen, res = set(), []
    for s in out:
        if s["etichetta"] not in seen:
            seen.add(s["etichetta"])
            res.append(s)
    return res


def contatti(a):
    testo = a.get("descrizione") or ""
    emails = [e for e in EMAIL_RE.findall(testo)
              if not e.lower().endswith((".jpg", ".png")) and "subito" not in e.lower()]
    tel = None
    for m in PHONE_RE.finditer(testo):
        digits = re.sub(r"\D", "", m.group(0))
        if 9 <= len(digits) <= 12:
            tel = m.group(0).strip()
            break
    return (a.get("email_agenzia") or (emails[0] if emails else None),
            a.get("telefono_inserzionista") or tel)


def da_avviso_email(a):
    """Annuncio letto da un avviso email (senza descrizione o con un estratto).
    I dati salvati prima del campo avviso_email: Immobiliare.it arriva solo così."""
    return a.get("avviso_email", a.get("fonte") == "Immobiliare.it")


def duplicati(annunci):
    """Stesso immobile su più portali: prezzo ±2%, mq ±2, distanza < 400 m.
    Si tiene la versione più completa: prima quelle dai siti (Tecnocasa, poi
    Casa.it, poi le altre), per ultime quelle dagli avvisi email."""
    tenuti = []
    for a in sorted(annunci, key=lambda x: (da_avviso_email(x), x["fonte"] != "Tecnocasa",
                                            x["fonte"] != "Casa.it")):
        dup = None
        for b in tenuti:
            if (a["prezzo"] and b["prezzo"] and abs(a["prezzo"] - b["prezzo"]) <= 0.02 * b["prezzo"]
                    and a["mq"] and b["mq"] and abs(a["mq"] - b["mq"]) <= 2
                    and a["lat"] and b["lat"]
                    and haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]) < 0.4):
                dup = b
                break
        if dup:
            dup.setdefault("altre_fonti", []).append({"fonte": a["fonte"], "url": a["url"]})
            if not dup.get("email") and a.get("email"):
                dup["email"] = a["email"]
        else:
            tenuti.append(a)
    return tenuti


def run():
    g = load_json("grezzi.json")
    if not g:
        raise RuntimeError("nessun dato grezzo: eseguire prima l'Agente Ricerca")
    catalogo, scartati = [], []
    for a in g["vendita"]:
        a = dict(a)
        testo = f"{a.get('titolo') or ''}\n{a.get('descrizione') or ''}"
        if re.search(r"\b(box|posto auto|posti auto|garage|autorimessa|magazzino|negozio|"
                     r"ufficio|terreno|stanza in)\b", (a.get("titolo") or "").lower()):
            scartati.append({"id": a["id"], "url": a["url"], "titolo": a["titolo"],
                             "motivo": "non è un'abitazione"})
            continue
        if not a.get("prezzo") or not a.get("mq") or a["mq"] < 12 or a["mq"] > 80:
            scartati.append({"id": a["id"], "motivo": "prezzo/superficie mancanti o anomali"})
            continue
        a["prezzo_mq"] = round(a["prezzo"] / a["mq"])
        a["stato_norm"] = stato_norm(a.get("stato"), testo)
        a["spese_condominio_mese"] = a.get("spese_condominio_mese") or estrai_spese_mese(testo)
        a["email"], a["telefono"] = contatti(a)
        a["segnali"] = segnali(a)
        a["zona_universitaria"] = a["universita_vicine"][0]["nome"]
        a["distanza_uni_km"] = a["universita_vicine"][0]["km"]
        esclusioni = [s["etichetta"] for s in a["segnali"] if s["tipo"] == "esclusione"]
        if esclusioni:
            scartati.append({"id": a["id"], "url": a["url"], "titolo": a["titolo"],
                             "motivo": ", ".join(esclusioni)})
            continue
        catalogo.append(a)
    prima = len(catalogo)
    catalogo = duplicati(catalogo)
    log(AGENT, f"catalogati {len(catalogo)} annunci ({prima - len(catalogo)} doppioni "
               f"tra portali uniti, {len(scartati)} scartati)")

    # canoni d'affitto per zona universitaria (€/mq/mese, mediana)
    canoni, canoni_nil = {}, {}
    for a in g["affitto"]:
        try:
            if not (a["prezzo"] and a["mq"] and a["universita_vicine"]):
                continue
            if not (300 <= a["prezzo"] <= 3000 and 15 <= a["mq"] <= 70):
                continue
            u = a["universita_vicine"][0]
            if u["km"] <= 2.0:
                canoni.setdefault(u["nome"], []).append([a["prezzo"], a["mq"]])
            if a.get("nil"):
                canoni_nil.setdefault(a["nil"], []).append([a["prezzo"], a["mq"]])
        except (KeyError, TypeError):
            continue
    save_json("catalogo.json", {"aggiornato": g["aggiornato"], "annunci": catalogo,
                                "scartati": scartati, "per_fonte": g.get("per_fonte", {}),
                                "canoni_eur_mq": canoni, "canoni_nil": canoni_nil})
    return len(catalogo)


if __name__ == "__main__":
    run()
