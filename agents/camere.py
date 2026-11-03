"""Numero di camere da letto ricavato dalla descrizione di un annuncio.

Le descrizioni le citano in molti modi; si combinano quattro indizi e si tiene il
massimo:
  1. numero esplicito, anche con aggettivi in mezzo: "tre spaziose camere",
     "tre comode e funzionali camere da letto", "2 camerette";
     "N ulteriori/altre camere (o stanze)" vuol dire N più quella già citata;
     "N camere … e una singola" aggiunge quella in coda;
  2. ordinali: "una terza camera", "la 2° camera" → almeno 3, 2;
  3. elenco di camere al singolare con qualificativi diversi ("camera
     matrimoniale…, cameretta…, camera singola") → quante sono, solo se almeno 2
     e solo se la descrizione non è troncata ("…"), perché potrebbe continuare;
  4. niente: None, e il chiamante resta sulla stima dai locali.
Si scartano le frasi su camere solo potenziali ("possibilità di ricavare la 3ª
camera", "trasformabile in terza camera", "utilizzabile come camera") e i falsi
amici ("doppia camera" degli infissi, "camera d'aria", "camera di commercio")."""
import re

_NUM = {"una": 1, "un": 1, "uno": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6}
_ORD = {"prima": 1, "seconda": 2, "terza": 3, "quarta": 4, "quinta": 5, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5}
_N = r"(\d|due|tre|quattro|cinque|sei)"
# parole che, tra il numero e "camere", indicano che il numero si riferisce ad altro
_STOP = {"bagni", "bagno", "servizi", "balconi", "terrazzi", "terrazze", "ripostigli", "locali", "piani", "livelli",
         "vani", "box", "posti", "cantine", "soggiorni", "cucine", "studi", }
_PAROLA = r"[a-zàèéìòù']+"
# contesto che rende la camera solo potenziale (nella stessa frase, prima della menzione)
_POTENZIALE = re.compile(r"(ricava|possibil|trasforma|eventual|potenzial|realizza|riconvert|ristrutturazione|"
                         r"ristrutturando|progetto|valutare|desider|bisogno|in caso di|adattabile a|utilizzabil|utilizzat[oa]|"
                         r"si presta|\bcome\s+(?:\w+\s+){0,2}$)", re.I)
_FALSI = re.compile(r"(doppia|tripla|singola)\s+camera(?!\s+(?:da letto|matrimoniale))|camera\s+(d'aria|di commercio|"
                    r"oscura|di combustione|a gas|stagna)|camera\s+con\s+vista\s+sul", re.I)


def _frasi(testo):
    return [f for f in re.split(r"[.;:\n•*]|\s-\s", testo.lower()) if f.strip()]


def _potenziale(frase, inizio):
    return bool(_POTENZIALE.search(frase[max(0, inizio - 60):inizio]))


def conta(descrizione):
    if not descrizione:
        return None
    testo = _FALSI.sub(" ", descrizione.lower())
    esplicito, ordinale, tipi = 0, 0, set()
    for frase in _frasi(testo):
        prima_camera = None
        for m in re.finditer(r"\bcamer(?:a|etta)\b", frase):
            prima_camera = m.start() if prima_camera is None else prima_camera
        # 1. numero esplicito: tra numero e "camere" solo aggettivi (non "due bagni e tre camere")
        for m in re.finditer(r"\b" + _N + r"\b", frase):
            g = re.match(r"\s+((?:" + _PAROLA + r"\s+){0,3}?)(camer(?:e|ette|a)|stanze)\b", frase[m.end():])
            if not g or _potenziale(frase, m.start()):
                continue
            parole, cosa, fine = g.group(1), g.group(2), m.end() + g.end()
            if set(parole.split()) & (set(_NUM) | _STOP) or re.search(r"\d", parole):
                continue
            if re.match(r"\s*o\s+" + _N, frase[fine - len(cosa) - 1 - len(parole):]) or \
                    re.search(r"\b" + _N + r"\s+o\s+$", frase[max(0, m.start() - 12):m.start()]):
                continue  # "tre o quattro camere": non si sa
            if cosa == "stanze" and not re.match(r"\s*(?:da letto|,?\s*ideali da adibire a camer|adibit[ei] a camer)",
                                                 frase[fine:fine + 40]):
                continue
            n = _NUM.get(m.group(1)) or int(m.group(1))
            if cosa == "camera" and n < 2:
                continue  # "1 camera" lo conta l'elenco; "due camera matrimoniali" è un refuso del plurale
            if re.search(r"\b(ulteriori|altre)\b", parole):
                n += 1
            coda = re.match(r"([^,]{0,40}?)\be\s+(?:una|un')\s+(?:camera\s+|stanza\s+)?(singola|cameretta|doppia|matrimoniale)",
                            frase[fine:])
            if coda and not re.search(r"\b" + _N + r"\b|\d", coda.group(1)):
                n += 1
            esplicito = max(esplicito, n)
        # 2. ordinali
        for m in re.finditer(r"\b(prima|seconda|terza|quarta|quinta|[1-5])\s*[°ªº]?\s+(?:" + _PAROLA + r"\s+)?camer(?:a|etta)\b",
                             frase):
            if not _potenziale(frase, m.start()) and _ORD[m.group(1)] >= 2:
                ordinale = max(ordinale, _ORD[m.group(1)])
        # 3. elenco al singolare
        for m in re.finditer(r"\b(camera(?:\s+da\s+letto)?(?:\s+(matrimoniale|singola|doppia|padronale|ospiti|"
                             r"padronale|matrimoniale))?|cameretta)\b", frase):
            if _potenziale(frase, m.start()) or re.search(r"(seconda|terza|quarta|[2-5]\s*[°ªº]?)\s+(?:\w+\s+)?$",
                                                         frase[max(0, m.start() - 20):m.start()]):
                continue  # gli ordinali li conta il punto 2
            if not m.group(2) and m.group(1) != "cameretta" and \
                    re.search(r"\b(in|nella|della|dalla|sulla|alla|delle|nelle|dalle|alle)\s+$", frase[max(0, m.start() - 8):m.start()]):
                continue  # "aria condizionata in camera da letto": un riferimento, non un'altra camera
            tipi.add("cameretta" if m.group(1) == "cameretta" else (m.group(2) or "camera"))
    troncata = descrizione.rstrip().endswith(("...", "…"))
    elenco = len(tipi) if len(tipi) >= 2 and not troncata else 0
    n = max(esplicito, ordinale, elenco)
    if not n:
        return None
    return n, "esplicito" if n == esplicito else "ordinale" if n == ordinale else "elenco"


def camere(descrizione, locali=None, minimo=3):
    """Camere dalla descrizione, altrimenti None. Ordinali ed elenchi dicono
    "almeno N": bastano se N raggiunge il minimo richiesto o la stima dai locali
    (locali − 1); se sono meno potrebbero esserci camere non citate, quindi meglio
    restare sulla stima ("da verificare") che dichiarare il requisito mancante."""
    r = conta(descrizione)
    if not r:
        return None
    n, come = r
    if come != "esplicito" and n < minimo and locali and n < locali - 1:
        return None
    return n
