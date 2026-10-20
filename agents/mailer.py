"""AGENTE EMAIL: per gli immobili che hai confermato sulla pagina web, scrive
all'agenzia per chiedere un appuntamento. Invia solo dopo la tua conferma
esplicita; senza credenziali SMTP salva le email come bozze (.eml)."""
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from .common import DATA, load_config, load_json, log, save_json

AGENT = "Email"


def smtp_connessione(cfg):
    """Restituisce una connessione SMTP autenticata, o None se non configurata."""
    e = cfg["email"]
    if not (e.get("abilitato") and e.get("password_app")):
        return None
    smtp = smtplib.SMTP_SSL(e["smtp_host"], e["smtp_port"],
                            context=ssl.create_default_context(), timeout=30)
    smtp.login(e["utente"], e["password_app"])
    return smtp


def _eur(x):
    return f"{x:,.0f} €".replace(",", ".")


def componi(a, cfg):
    e = cfg["email"]
    ind = a.get("indirizzo") or a.get("titolo")
    tipo = "bilocale" if str(a.get("locali") or "1") == "2" else "monolocale"
    oggetto = f"Richiesta appuntamento — {tipo} {ind} ({_eur(a['prezzo'])})"
    tel = f"\nPuò contattarmi anche al {e['telefono']}." if e.get("telefono") else ""
    corpo = f"""Buongiorno,

ho visto il vostro annuncio su {a['fonte']}:
{a.get('titolo')}
{a.get('url')}

Prezzo: {_eur(a['prezzo'])} — Superficie: {a['mq']:.0f} mq

Sto valutando l'acquisto dell'immobile a scopo di investimento e vorrei
fissare un appuntamento per visitarlo. Sarei disponibile nei prossimi giorni,
anche in orario serale o il sabato: mi indichi pure le disponibilità.

Se possibile, potreste inviarmi in anticipo anche:
- planimetria catastale e visura
- importo delle spese condominiali annue e delle eventuali spese straordinarie deliberate
- attestato di prestazione energetica (APE)
- stato locativo (libero o locato) e data di disponibilità
{tel}
{e['firma']}
"""
    return {"id": a["id"], "a": a.get("email"), "oggetto": oggetto, "corpo": corpo,
            "titolo": a.get("titolo"), "inserzionista": a.get("inserzionista"),
            "telefono": a.get("telefono"), "url": a.get("url")}


def trova(ids):
    c = load_json("classifica.json", {})
    tutti = {a["id"]: a for a in c.get("top", []) + c.get("altri", [])}
    return [tutti[i] for i in ids if i in tutti]


def anteprima(ids):
    cfg = load_config()
    return [componi(a, cfg) for a in trova(ids)]


def invia(bozze):
    """bozze: lista di {id, a, oggetto, corpo} confermate dall'utente (eventualmente
    modificate sulla pagina). Restituisce l'esito per ciascuna."""
    cfg = load_config()
    e = cfg["email"]
    registro = load_json("email_inviate.json", {})
    attivo = e.get("abilitato") and e.get("password_app")
    esiti, smtp = [], None
    try:
        if attivo:
            smtp = smtp_connessione(cfg)
        for b in bozze:
            if not b.get("a"):
                esiti.append({"id": b["id"], "esito": "senza_email",
                              "messaggio": "Nessuna email: contattare dal portale o per telefono"})
                continue
            msg = EmailMessage()
            msg["From"] = formataddr((e["mittente_nome"], e["utente"]))
            msg["To"] = b["a"]
            msg["Bcc"] = e["utente"]  # copia per te
            msg["Subject"] = b["oggetto"]
            msg["Message-ID"] = make_msgid()
            msg.set_content(b["corpo"])
            now = datetime.now().isoformat(timespec="seconds")
            if attivo:
                smtp.send_message(msg)
                stato = "inviata"
            else:
                d = DATA / "bozze"
                d.mkdir(exist_ok=True)
                (d / f"{b['id']}.eml").write_bytes(bytes(msg))
                stato = "bozza"
            registro[b["id"]] = {"stato": stato, "data": now, "a": b["a"],
                                 "oggetto": b["oggetto"]}
            esiti.append({"id": b["id"], "esito": stato})
            log(AGENT, f"{stato}: {b['a']} — {b['oggetto']}")
    except Exception as ex:
        log(AGENT, f"errore invio: {ex}")
        esiti.append({"id": None, "esito": "errore", "messaggio": str(ex)})
    finally:
        if smtp:
            smtp.quit()
        save_json("email_inviate.json", registro)
    return {"smtp_attivo": bool(attivo), "esiti": esiti}
