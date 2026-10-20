"""AGENTE REPORT: invia via email la classifica aggiornata (top 20 con link)
ai destinatari in config.json → report.destinatari."""
import html
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from .common import DATA, load_config, load_json, log
from .mailer import smtp_connessione

AGENT = "Report"


def _eur(x):
    return "—" if x is None else f"{x:,.0f} €".replace(",", ".")


def _pct(x):
    return f"{x:.1f}%".replace(".", ",")


def componi(c, cfg):
    top = c["top"]
    porta = cfg["server"]["porta"]
    data = datetime.fromisoformat(c["aggiornato"]).strftime("%d/%m/%Y %H:%M")
    fonti = ", ".join(f"{k} {v}" if v else f"{k} n.d." for k, v in c.get("per_fonte", {}).items())
    nuovi = sum(1 for a in top if a.get("nuovo_in_top"))
    oggetto = (f"Monolocali universitari Milano — classifica del {data[:10]}"
               + (f" ({nuovi} nuovi)" if nuovi else ""))

    righe_txt, righe_html = [], []
    for a in top:
        v = a["valutazione"]
        nuovo = " [NUOVO]" if a.get("nuovo_in_top") else ""
        righe_txt.append(
            f"{a['posizione_classifica']:>2}. {a['titolo']}{nuovo}\n"
            f"    {_eur(a['prezzo'])} · {a['mq']:.0f} mq · {_eur(a['prezzo_mq'])}/mq · "
            f"affitto stimato {_eur(v['canone_stimato'])}/mese · rend. netto {_pct(v['rendimento_netto'])}\n"
            f"    {a['distanza_uni_km']:.1f} km da {a['zona_universitaria']} · punteggio "
            f"{v['punteggio']:.0f} ({v['giudizio']}) · {a['fonte']}\n"
            f"    {a['url']}\n")
        e = html.escape
        pro = " · ".join(e(p) for p in v["pro"][:3])
        contro = " · ".join(e(p) for p in v["contro"][:2])
        righe_html.append(f"""<tr style="border-bottom:1px solid #e3e0d8">
<td style="padding:10px 8px;font-size:18px;font-weight:700;color:#8b8a84;vertical-align:top">{a['posizione_classifica']}</td>
<td style="padding:10px 8px;vertical-align:top">
 <a href="{e(a['url'])}" style="color:#1f5f4a;font-weight:600;text-decoration:none">{e(a['titolo'])}</a>
 {'<span style="background:#e3efe9;color:#1f5f4a;font-size:11px;padding:1px 6px;border-radius:8px">NUOVO</span>' if nuovo else ''}
 <div style="color:#5c5b56;font-size:12px">{e(a['indirizzo']) + ' · ' if a.get('indirizzo') else ''}{e(a['fonte'])} · {a['distanza_uni_km']:.1f} km da {e(a['zona_universitaria'])}</div>
 <div style="font-size:13px;margin-top:3px"><b>{_eur(a['prezzo'])}</b> · {a['mq']:.0f} mq · {_eur(a['prezzo_mq'])}/mq ·
  affitto stimato {_eur(v['canone_stimato'])}/mese · rend. netto <b>{_pct(v['rendimento_netto'])}</b></div>
 {f'<div style="font-size:12px;color:#1f7a4d">+ {pro}</div>' if pro else ''}
 {f'<div style="font-size:12px;color:#b23b2e">− {contro}</div>' if contro else ''}
</td>
<td style="padding:10px 8px;text-align:right;vertical-align:top;white-space:nowrap">
 <div style="font-size:20px;font-weight:700">{v['punteggio']:.0f}</div>
 <div style="font-size:11px;color:#5c5b56">{e(v['giudizio'])}</div></td></tr>""")

    testo = (f"Classifica aggiornata il {data}: {c['totale_valutati']} monolocali valutati "
             f"vicino alle università di Milano.\nFonti: {fonti}\n\n"
             + "\n".join(righe_txt) +
             f"\nDettagli e richiesta appuntamenti: http://localhost:{porta}\n"
             "Rendimenti e costi sono stime indicative.\n")
    corpo_html = f"""<div style="font-family:system-ui,Segoe UI,Roboto,sans-serif;color:#1d1d1b;max-width:760px">
<h2 style="margin:0 0 4px">Monolocali universitari · Milano</h2>
<p style="color:#5c5b56;margin:0 0 14px;font-size:13px">Classifica aggiornata il {data} · {c['totale_valutati']} monolocali valutati
vicino agli atenei · Fonti: {html.escape(fonti)}</p>
<table style="border-collapse:collapse;width:100%">{''.join(righe_html)}</table>
<p style="color:#5c5b56;font-size:12px;margin-top:16px">Punteggio 0–100 da investitore (valore, rendimento netto, posizione, stato,
costi accessori, dimensione). Rendimenti e costi sono stime indicative. Dettagli e richiesta appuntamenti dalla dashboard
locale: http://localhost:{porta}</p></div>"""
    return oggetto, testo, corpo_html


def run():
    cfg = load_config()
    dest = cfg.get("report", {}).get("destinatari", [])
    c = load_json("classifica.json")
    if not c or not dest:
        log(AGENT, "nessuna classifica o nessun destinatario: report non inviato")
        return False
    oggetto, testo, corpo_html = componi(c, cfg)
    e = cfg["email"]
    msg = EmailMessage()
    msg["From"] = formataddr((e["mittente_nome"], e["utente"]))
    msg["To"] = ", ".join(dest)
    msg["Subject"] = oggetto
    msg["Message-ID"] = make_msgid()
    msg.set_content(testo)
    msg.add_alternative(corpo_html, subtype="html")
    smtp = smtp_connessione(cfg)
    if not smtp:
        d = DATA / "bozze"
        d.mkdir(exist_ok=True)
        f = d / f"report-{datetime.now():%Y%m%d-%H%M}.eml"
        f.write_bytes(bytes(msg))
        log(AGENT, f"SMTP non configurato: report salvato come bozza in {f}")
        return False
    try:
        smtp.send_message(msg)
    finally:
        smtp.quit()
    log(AGENT, f"report inviato a {', '.join(dest)}")
    return True


if __name__ == "__main__":
    run()
