"""Orario della ricerca giornaliera (docker/avvio.py).

Prima si calcolavano i secondi fino alle 08:00 e si dormiva in un colpo solo:
nella notte del ritorno all'ora solare (25/10/2026) l'orologio torna indietro di
un'ora, quindi il risveglio arrivava alle 07:00 "nuove" e poi la ricerca ripartiva
alle 08:00 (due giri e due report). Ora si dorme a passi brevi ricontrollando l'ora
reale, e non si fa più di un giro per data."""
import time
from datetime import datetime, timedelta


def prossima(ora, hh, mm, ultimo_giorno=None):
    """Prossimo orario hh:mm dopo `ora`; se oggi il giro è già stato fatto, domani."""
    t = ora.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if t <= ora or ultimo_giorno == ora.date():
        t += timedelta(days=1)
    return t


def attendi(obiettivo, adesso=datetime.now, dormi=time.sleep, passo=300):
    """Dorme fino all'orario `obiettivo` dell'orologio locale (anche se l'ora cambia)."""
    while True:
        resto = (obiettivo - adesso()).total_seconds()
        if resto <= 0:
            return
        dormi(min(resto, passo))
