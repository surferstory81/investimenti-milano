"""Giudizi dell'utente sugli annunci, dalle pagine studenti e famiglia
(data/preferiti.json):

- "mi_piace": l'annuncio è tra i preferiti; a ogni valutazione si registra se è
  ancora sui portali, prezzo e posizione, così il report del mattino può dire
  "calo di prezzo" o "non più trovato" anche se l'annuncio è sparito.
- "scartato": l'annuncio non compare più in classifica né nel report (si può
  ripristinare dalla pagina).

Si salva anche titolo, url e prezzo del momento, così la voce resta leggibile
anche quando l'annuncio non è più tra quelli trovati."""
from datetime import datetime

from .common import load_json, save_json

FILE = "preferiti.json"
PROFILI = ("studenti", "famiglia")
STATI = ("mi_piace", "scartato")


def tutti():
    p = load_json(FILE, {}) or {}
    for v in p.values():
        v.setdefault("stato", "mi_piace")  # voci salvate prima dello "scarta"
    return p


def ids(profilo, stato):
    return {k for k, v in tutti().items() if v["profilo"] == profilo and v["stato"] == stato}


def imposta(id_, profilo, stato, annuncio=None, adesso=None):
    """stato: "mi_piace", "scartato" o None (toglie il giudizio). Per compatibilità
    accetta anche True/False (= mi piace / niente)."""
    if stato is True:
        stato = "mi_piace"
    elif stato is False:
        stato = None
    if not id_ or profilo not in PROFILI or stato not in (*STATI, None):
        raise ValueError("id, profilo o stato non validi")
    p = tutti()
    if stato:
        a, prima = annuncio or {}, p.get(id_) or {}
        quando = (adesso or datetime.now()).isoformat(timespec="seconds")
        voce = {**prima, "profilo": profilo, "stato": stato,
                **{k: a.get(k) for k in ("titolo", "url", "prezzo", "fonte") if a.get(k) is not None}}
        if prima.get("stato") != stato:
            voce["dal"] = quando
            voce["prezzo_iniziale"] = a.get("prezzo")
        p[id_] = voce
    else:
        p.pop(id_, None)
    save_json(FILE, p)
    return p


def aggiorna(profilo, annunci, adesso=None):
    """Dopo una valutazione: per i preferiti del profilo presenti tra `annunci`
    (in ordine di classifica) registra ultima vista, prezzo e posizione; se il
    prezzo è cambiato rispetto all'ultima volta tiene il precedente e la data."""
    quando = (adesso or datetime.now()).isoformat(timespec="seconds")
    p = tutti()
    posizione = {a["id"]: (i, a) for i, a in enumerate(annunci, 1)}
    cambiati = False
    for id_, v in p.items():
        if v["profilo"] != profilo or v["stato"] != "mi_piace" or id_ not in posizione:
            continue
        pos, a = posizione[id_]
        if v.get("prezzo") is not None and a.get("prezzo") is not None and a["prezzo"] != v["prezzo"]:
            v["prezzo_precedente"], v["variato_il"] = v["prezzo"], quando
        v.update(prezzo=a.get("prezzo"), posizione=pos, ultima_vista=quando,
                 titolo=a.get("titolo") or v.get("titolo"), url=a.get("url") or v.get("url"))
        cambiati = True
    if cambiati:
        save_json(FILE, p)
    return p


def riepilogo(profilo, oggi):
    """Righe per il report: [{titolo, url, prezzo, posizione, note: [...]}], prima
    le novità (cali di prezzo, spariti), poi gli altri preferiti."""
    out = []
    for id_, v in tutti().items():
        if v["profilo"] != profilo or v["stato"] != "mi_piace":
            continue
        note, novita = [], False
        visto_oggi = (v.get("ultima_vista") or "")[:10] == oggi
        if not visto_oggi:
            ultima = v.get("ultima_vista")
            note.append(f"non più trovato dal {ultima[8:10]}/{ultima[5:7]}" if ultima
                        else "non trovato tra gli annunci di oggi")
            novita = (ultima or "")[:10] >= _ieri(oggi)  # sparito da oggi
        if visto_oggi and (v.get("variato_il") or "")[:10] == oggi and v.get("prezzo_precedente"):
            diff = v["prezzo"] - v["prezzo_precedente"]
            note.append(f"prezzo {'sceso' if diff < 0 else 'salito'} oggi di {_eur(abs(diff))}")
            novita = True
        if v.get("prezzo_iniziale") and v.get("prezzo") and v["prezzo"] != v["prezzo_iniziale"]:
            diff = v["prezzo"] - v["prezzo_iniziale"]
            note.append(f"{'−' if diff < 0 else '+'}{_eur(abs(diff))} da quando l'hai segnato")
        out.append({"id": id_, "titolo": v.get("titolo") or id_, "url": v.get("url"),
                    "prezzo": v.get("prezzo"), "posizione": v.get("posizione") if visto_oggi else None,
                    "note": note, "novita": novita})
    return sorted(out, key=lambda r: (not r["novita"], r["posizione"] is None, r["posizione"] or 0))


def _ieri(oggi):
    from datetime import date, timedelta
    return (date.fromisoformat(oggi) - timedelta(days=1)).isoformat()


def _eur(x):
    return f"{x:,.0f} €".replace(",", ".")


def sezione_report(righe):
    """(testo, html, n_novita) della sezione "I tuoi preferiti" per i report email."""
    if not righe:
        return "", "", 0
    import html as h
    t = ["I TUOI PREFERITI"]
    rh = ['<tr><td colspan="4" style="padding:4px 8px 6px;font-weight:700;font-size:15px">I tuoi preferiti</td></tr>']
    for r in righe:
        dove = f"#{r['posizione']} in classifica" if r["posizione"] else ""
        prezzo = _eur(r["prezzo"]) if r["prezzo"] else "—"
        t.append(f"{'* ' if r['novita'] else '- '}{r['titolo']}\n  {prezzo}"
                 f"{' · ' + dove if dove else ''}{' · ' + ' · '.join(r['note']) if r['note'] else ''}\n  {r['url'] or ''}")
        note = "".join(
            f'<span style="background:{"#fbf0dc" if r["novita"] else "#f0eee8"};color:{"#a86a00" if r["novita"] else "#5c5b56"};'
            f'border-radius:99px;padding:1px 8px;margin:0 4px 4px 0;display:inline-block;font-size:12px">{h.escape(n)}</span>'
            for n in r["note"])
        titolo = (f'<a href="{h.escape(r["url"])}" style="color:#1f5f4a;font-weight:600">{h.escape(r["titolo"])}</a>'
                  if r["url"] else h.escape(r["titolo"]))
        rh.append(f"""<tr style="border-top:1px solid #e3e0d8;{'background:#fffaf0' if r['novita'] else ''}">
<td style="padding:8px;vertical-align:top;color:#b23b2e;font-size:16px">♥</td>
<td colspan="2" style="padding:8px;vertical-align:top">{titolo}
<div style="font-size:13px;color:#5c5b56;margin:2px 0 4px">{prezzo}{' · ' + h.escape(dove) if dove else ''}</div>{note}</td>
<td></td></tr>""")
    rh.append('<tr><td colspan="4" style="padding:14px 0 0"></td></tr>')
    return "\n".join(t) + "\n\n", "".join(rh), sum(r["novita"] for r in righe)
