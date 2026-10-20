"""Orchestratore: Ricerca → Catalogatore → Valutatore (→ Report via email).
Uso:  python3 run.py                 ricerca completa
      python3 run.py --solo-valuta   ricalcola la classifica sui dati già raccolti
      python3 run.py --report        ricerca completa + invio classifica via email
      python3 run.py --solo-report   invia solo la classifica attuale"""
import sys

from agents import catalogatore, report, ricerca, valutatore
from agents.common import log


def pipeline(solo_valuta=False):
    log("Orchestratore", "=== avvio pipeline ===")
    if not solo_valuta:
        ricerca.run()
    catalogatore.run()
    valutatore.run()
    log("Orchestratore", "=== pipeline completata: pagina aggiornata ===")


if __name__ == "__main__":
    if "--solo-report" in sys.argv:
        report.run()
    else:
        pipeline("--solo-valuta" in sys.argv)
        if "--report" in sys.argv:
            report.run()
