"""Piano dell'immobile normalizzato da tutte le fonti, e classe per il punteggio.

Formati in ingresso (campo "piano"):
  Subito "3", "0", "Rialzato", "Seminterrato", "Oltre il 7°"; Tecnocasa
  "2 di 6 con ascensore (piano medio)", "5 di 5 … (ultimo piano)"; Gabetti "Terzo",
  "Terra"; Dove.it "5 - 6 di 6, con ascensore", "terra di 6"; Idealista
  "3º piano con ascensore", "piano terra". Se manca (Casa.it, Immobiliare dagli
  avvisi) si cerca nella descrizione, solo con frasi esplicite ("situato al terzo
  piano", "all'ultimo piano"): "piano terra" da solo spesso parla di altro
  (portineria, box), quindi lì serve "appartamento/situato al piano terra".

Classi: seminterrato, terra (anche rialzato), primo, intermedio (2°-3°), alto
(dal 4° o ultimo piano). Per la famiglia contano intermedi e alti."""
import re

_ORD = {"primo": 1, "secondo": 2, "terzo": 3, "quarto": 4, "quinto": 5, "sesto": 6, "settimo": 7, "ottavo": 8,
        "nono": 9, "decimo": 10, "undicesimo": 11, "dodicesimo": 12, "tredicesimo": 13, "quattordicesimo": 14,
        "quindicesimo": 15, "sedicesimo": 16, "diciassettesimo": 17, "diciottesimo": 18, "diciannovesimo": 19,
        "ventesimo": 20}
_ORD_RX = "|".join(sorted(_ORD, key=len, reverse=True))
_TERRA = re.compile(r"\b(terra|rialzato|pt|piano 0)\b")
# frasi della descrizione che parlano davvero del piano dell'appartamento
_TESTO = re.compile(r"(?:situat\w*|post\w*|sit\w|ubicat\w*|collocat\w*|appartamento|si trova|si sviluppa|trova)\s+"
                    r"(?:\w+\s+){0,2}?(?:al|all'|a l)\s*(" + _ORD_RX + r"|\d{1,2}\s*[°ºª]?|ultimo)\s+(?:ed\s+ultimo\s+)?piano"
                    r"|(?:situat\w*|post\w*|ubicat\w*|appartamento|si trova)\s+(?:\w+\s+){0,2}?al\s+piano\s+(terra|rialzato)"
                    r"|\ball'(ultimo)\s+piano\b")

CLASSI = ("seminterrato", "terra", "primo", "intermedio", "alto")
# quanto vale ogni classe nel punteggio famiglia (piano ignoto: metà)
VALORE = {"seminterrato": 0.0, "terra": 0.1, "primo": 0.4, "intermedio": 1.0, "alto": 1.0, None: 0.5}


def _da_campo(v):
    """(numero, ultimo) dal campo piano della fonte, o (None, False)."""
    if v is None or str(v).strip() == "":
        return None, False
    s = str(v).strip().lower()
    if "seminterrat" in s or "interrato" in s or re.match(r"^-\d", s):
        return -1, False
    ultimo = "ultimo" in s
    tot = re.search(r"\bdi\s+(\d{1,2})\b", s)
    if re.match(r"^(terra|rialzato|piano terra|piano rialzato)\b", s) or s in ("0", "t", "pt"):
        return 0, False
    m = re.match(r"^oltre il\s*(\d+)", s)
    if m:
        return int(m.group(1)) + 1, ultimo
    m = re.match(r"^(\d{1,2})", s) or re.search(r"\b(\d{1,2})\s*[°ºª]\s*piano", s)
    if m:
        n = int(m.group(1))
        if tot and re.match(r"^\d{1,2}\s*-\s*(\d{1,2})", s):  # "5 - 6 di 6": su due livelli, conta il più basso
            ultimo = ultimo or int(re.match(r"^\d{1,2}\s*-\s*(\d{1,2})", s).group(1)) == int(tot.group(1))
        elif tot:
            ultimo = ultimo or n == int(tot.group(1))
        return n, ultimo
    m = re.match(r"^(" + _ORD_RX + r")\b", s)
    if m:
        return _ORD[m.group(1)], ultimo
    if _TERRA.search(s):
        return 0, False
    return None, ultimo


_ALTRO = re.compile(r"cantin|\bbox\b|posto auto|posti auto|garage|autorimess|ingresso|portineri|lavanderi|taverna|"
                    r"solaio|soffitt|deposito|magazzin|ripostigl|negozio|ufficio|locale tecnico")
_SOGGETTO = re.compile(r"appartament|immobile|abitazion|unit|propriet|soluzion|locale|bilocal|trilocal|quadrilocal|"
                       r"villa|attico|casa")


def _da_testo(t):
    """Primo piano citato in modo esplicito per l'appartamento (non per cantina, box, ingresso…)."""
    t = (t or "").lower()
    for m in _TESTO.finditer(t):
        prima = re.split(r"[.;!?\n]", t[max(0, m.start() - 45):m.start()])[-1] + m.group(0)  # solo la stessa frase
        if _ALTRO.search(prima):
            continue
        v = next(g for g in m.groups() if g)
        if v in ("terra", "rialzato"):
            if not _SOGGETTO.search(prima):
                continue
            return 0, False
        if v == "ultimo":
            return None, True
        v = re.sub(r"\D", "", v) or v
        return (_ORD[v] if v in _ORD else int(v)), False
    return None, False


# Tecnocasa a volte dà solo la fascia: "Attico di 3", "Medio di 3", "Basso di 1"
_FASCE = {"attico": "alto", "alto": "alto", "medio": "intermedio", "basso": "primo"}


def piano(a):
    """{"n": numero o None, "ultimo": bool, "classe": una di CLASSI o None, "da_testo": bool}"""
    fascia = re.match(r"^(attico|alto|medio|basso)\b", str(a.get("piano") or "").strip().lower())
    if fascia:
        return {"n": None, "ultimo": fascia.group(1) == "attico", "classe": _FASCE[fascia.group(1)], "da_testo": False}
    n, ultimo = _da_campo(a.get("piano"))
    da_testo = False
    if n is None and not ultimo:
        n, ultimo = _da_testo(a.get("descrizione"))
        da_testo = n is not None or ultimo
    if n is not None and n < 0:
        classe = "seminterrato"
    elif n == 0:
        classe = "terra"
    elif ultimo or (n is not None and n >= 4):
        classe = "alto"
    elif n == 1:
        classe = "primo"
    elif n is not None:
        classe = "intermedio"
    else:
        classe = None
    return {"n": n, "ultimo": ultimo, "classe": classe, "da_testo": da_testo}


def etichetta(p):
    if p["classe"] is None:
        return None
    if p["n"] is None:
        return "ultimo piano" if p["ultimo"] else {"alto": "piano alto", "intermedio": "piano medio",
                                                  "primo": "piano basso"}.get(p["classe"], p["classe"])
    base = "seminterrato" if p["n"] < 0 else "piano terra" if p["n"] == 0 else f"{p['n']}° piano"
    return base + (" (ultimo)" if p["ultimo"] and p["n"] and p["n"] > 0 else "")
