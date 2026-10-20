"""AGENTE RICERCA: cerca monolocali in vendita su più portali e annunci d'affitto (per stimare i canoni). Tiene solo quelli vicini
alle università di Milano.

Fonti: Subito.it e Tecnocasa (HTTP diretto), Casa.it e Idealista (Firefox
headless, best-effort: se il portale chiede una verifica anti-bot la fonte viene
saltata). Immobiliare.it blocca le visite automatiche con CAPTCHA: i suoi annunci
arrivano dagli avvisi email delle ricerche salvate, letti via IMAP."""
from datetime import datetime

from . import fonti
from .browser import Firefox
from .common import load_config, load_json, log, nearest_universities, save_json

AGENT = "Ricerca"


def run():
    cfg = load_config()
    unis = cfg["universita"]
    raggio = cfg["ricerca"]["raggio_universita_km"]
    attive = cfg["ricerca"].get("fonti", ["subito", "casa", "idealista"])
    vendita, per_fonte = [], {}

    def add(nome, fn):
        try:
            res = fn()
        except Exception as e:
            log(AGENT, f"{nome}: fonte non disponibile ({e})")
            res = []
        per_fonte[nome] = len(res)
        vendita.extend(res)

    if "subito" in attive:
        add("Subito.it", lambda: fonti.subito("vendita", cfg))
    if "tecnocasa" in attive:
        add("Tecnocasa", lambda: fonti.tecnocasa(cfg, None))
    if "immobiliare_email" in attive:
        add("Immobiliare.it", lambda: fonti.immobiliare_email(cfg))
    if "casa" in attive or "idealista" in attive:
        try:
            with Firefox() as ff:
                if "casa" in attive:
                    add("Casa.it", lambda: fonti.casa(ff, cfg))
                if "idealista" in attive:
                    add("Idealista", lambda: fonti.idealista(ff, cfg))
        except Exception as e:
            log(AGENT, f"browser non disponibile: {e}")

    log(AGENT, "raccolta canoni d'affitto (Subito.it) per stima rendimento")
    affitto = fonti.subito("affitto", cfg)

    for a in vendita + affitto:
        a["universita_vicine"] = (nearest_universities(a["lat"], a["lon"], unis)[:3]
                                  if a["lat"] else [])
    vicini = [a for a in vendita
              if a["universita_vicine"] and a["universita_vicine"][0]["km"] <= raggio]

    now = datetime.now().isoformat(timespec="seconds")
    storico = load_json("storico.json", {})
    for a in vicini:
        h = storico.setdefault(a["id"], {"prima_vista": now, "prezzi": []})
        if not h["prezzi"] or h["prezzi"][-1]["prezzo"] != a["prezzo"]:
            h["prezzi"].append({"data": now, "prezzo": a["prezzo"]})
        h["ultima_vista"] = now
    save_json("storico.json", storico)
    save_json("grezzi.json", {"aggiornato": now, "vendita": vicini,
                              "vendita_tot_milano": len(vendita),
                              "per_fonte": per_fonte, "affitto": affitto})
    log(AGENT, f"totale {len(vendita)} monolocali in vendita ({per_fonte}); "
               f"{len(vicini)} entro {raggio} km da un'università; "
               f"{len(affitto)} affitti per i canoni")
    return len(vicini)


if __name__ == "__main__":
    run()
