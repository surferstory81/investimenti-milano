"""Avvio nel container: dashboard (server.py) + ricerca giornaliera con report
all'orario di config.json → report.orario (sostituisce il timer systemd)."""
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agents.common import load_config, log  # noqa: E402
from agents.orario import attendi, prossima  # noqa: E402

server = subprocess.Popen([sys.executable, "server.py"])
ultimo_giorno = None  # un solo giro per data, anche nel giorno del cambio d'ora
while True:
    hh, mm = map(int, load_config()["report"].get("orario", "08:00").split(":"))
    attendi(prossima(datetime.now(), hh, mm, ultimo_giorno))
    ultimo_giorno = datetime.now().date()
    log("Orchestratore", "ricerca giornaliera programmata")
    subprocess.run([sys.executable, "run.py", "--report"])
    if load_config().get("famiglia"):
        subprocess.run([sys.executable, "-m", "agents.famiglia", "--report"])
    if server.poll() is not None:
        server = subprocess.Popen([sys.executable, "server.py"])
