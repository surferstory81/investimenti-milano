"""Avvio nel container: dashboard (server.py) + ricerca giornaliera con report
all'orario di config.json → report.orario (sostituisce il timer systemd)."""
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agents.common import load_config, log  # noqa: E402

server = subprocess.Popen([sys.executable, "server.py"])
while True:
    hh, mm = map(int, load_config()["report"].get("orario", "08:00").split(":"))
    ora = datetime.now()
    prossima = ora.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if prossima <= ora:
        prossima += timedelta(days=1)
    time.sleep((prossima - ora).total_seconds())
    log("Orchestratore", "ricerca giornaliera programmata")
    subprocess.run([sys.executable, "run.py", "--report"])
    if server.poll() is not None:
        server = subprocess.Popen([sys.executable, "server.py"])
