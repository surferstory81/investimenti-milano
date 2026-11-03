"""Orario della ricerca giornaliera nei giorni del cambio d'ora (agents/orario.py)."""
import unittest
from datetime import date, datetime, timedelta

from agents import orario


class Orologio:
    """Orologio locale finto: il tempo reale scorre con dormi(); l'ora mostrata salta
    di `salto` quando il tempo reale passa `quando` (es. -1 h alle 03:00 di fine ottobre)."""

    def __init__(self, inizio, quando=None, salto=timedelta(0)):
        self.reale, self.inizio, self.quando, self.salto = timedelta(0), inizio, quando, salto
        self.pause = 0

    def adesso(self):
        t = self.inizio + self.reale
        return t + self.salto if self.quando and t >= self.quando else t

    def dormi(self, s):
        self.pause += 1
        self.reale += timedelta(seconds=s)


class Prossima(unittest.TestCase):
    def test_oggi_o_domani(self):
        self.assertEqual(orario.prossima(datetime(2026, 11, 3, 7, 0), 8, 0), datetime(2026, 11, 3, 8, 0))
        self.assertEqual(orario.prossima(datetime(2026, 11, 3, 8, 0), 8, 0), datetime(2026, 11, 4, 8, 0))
        self.assertEqual(orario.prossima(datetime(2026, 11, 3, 9, 30), 8, 0), datetime(2026, 11, 4, 8, 0))

    def test_gia_fatto_oggi(self):
        self.assertEqual(orario.prossima(datetime(2026, 11, 3, 7, 30), 8, 0, date(2026, 11, 3)),
                         datetime(2026, 11, 4, 8, 0))
        self.assertEqual(orario.prossima(datetime(2026, 11, 3, 7, 30), 8, 0, date(2026, 11, 2)),
                         datetime(2026, 11, 3, 8, 0))


class CambioOra(unittest.TestCase):
    def giri(self, orologio, giorni):
        """Simula il ciclo di docker/avvio.py e restituisce gli orari locali dei giri."""
        fatti, ultimo = [], None
        for _ in range(giorni):
            orario.attendi(orario.prossima(orologio.adesso(), 8, 0, ultimo), orologio.adesso, orologio.dormi)
            fatti.append(orologio.adesso())
            ultimo = orologio.adesso().date()
            orologio.dormi(40 * 60)  # durata della ricerca
        return fatti

    def test_ritorno_ora_solare(self):
        # 25/10/2026: alle 03:00 l'orologio torna alle 02:00
        o = Orologio(datetime(2026, 10, 24, 8, 45), quando=datetime(2026, 10, 25, 3, 0), salto=-timedelta(hours=1))
        self.assertEqual([g.strftime("%d %H:%M") for g in self.giri(o, 3)], ["25 08:00", "26 08:00", "27 08:00"])

    def test_ora_legale(self):
        # 28/03/2027: alle 02:00 l'orologio salta alle 03:00
        o = Orologio(datetime(2027, 3, 27, 8, 45), quando=datetime(2027, 3, 28, 2, 0), salto=timedelta(hours=1))
        self.assertEqual([g.strftime("%d %H:%M") for g in self.giri(o, 2)], ["28 08:00", "29 08:00"])

    def test_il_vecchio_metodo_sbagliava(self):
        # documenta il difetto: un'unica pausa calcolata sull'ora locale finisce alle 07:00
        o = Orologio(datetime(2026, 10, 24, 8, 45), quando=datetime(2026, 10, 25, 3, 0), salto=-timedelta(hours=1))
        obiettivo = orario.prossima(o.adesso(), 8, 0)
        o.dormi((obiettivo - o.adesso()).total_seconds())
        self.assertEqual(o.adesso().strftime("%d %H:%M"), "25 07:00")

    def test_pause_brevi(self):
        o = Orologio(datetime(2026, 11, 3, 8, 30))
        orario.attendi(datetime(2026, 11, 4, 8, 0), o.adesso, o.dormi, passo=300)
        self.assertEqual(o.adesso(), datetime(2026, 11, 4, 8, 0))
        self.assertEqual(o.pause, 282)  # 23 h 30 min a passi di 5 minuti

    def test_orario_gia_passato(self):
        o = Orologio(datetime(2026, 11, 3, 9, 0))
        orario.attendi(datetime(2026, 11, 3, 8, 0), o.adesso, o.dormi)
        self.assertEqual(o.pause, 0)


if __name__ == "__main__":
    unittest.main()
