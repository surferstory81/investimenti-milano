"""Lettore degli avvisi email Casa.it: nome della ricerca salvata e annunci.
Email reali del 2026-11 ripulite (tests/dati/casa_*.html)."""
import unittest
from pathlib import Path

from agents import fonti

DATI = Path(__file__).parent / "dati"


def parse(nome, oggetto=""):
    return fonti._casa_email_parse((DATI / f"casa_{nome}.html").read_text(encoding="utf-8"), oggetto)


class NomeRicerca(unittest.TestCase):
    def test_riepilogo_non_prende_il_titolo_del_primo_annuncio(self):
        annunci = parse("riepilogo", "Riepilogo e suggerimenti per la tua ricerca Milano (prov.)")
        self.assertEqual(len(annunci), 10)
        self.assertEqual({a["ricerca"] for a in annunci}, {"Milano (prov.)"})

    def test_nuovo_annuncio(self):
        (a,) = parse("nuovo", "Un nuovo annuncio: 1.150.000 € | 320 mq | Via Aldo Moro, Buccinasco")
        self.assertEqual(a["ricerca"], "Milano (prov.)")

    def test_ordine_delle_fonti(self):
        r = fonti._casa_ricerca
        self.assertEqual(r("ciao\nLa tua ricerca Mono e bilocali\nCase in vendita"), "Mono e bilocali")
        self.assertEqual(r("guarda i nuovi annunci per la tua ricerca Famiglia centro\nAppartamento in vendita"),
                         "Famiglia centro")
        self.assertEqual(r("ecco il riepilogo per la tua ricerca\nCasa in vendita in Via X",
                           "Riepilogo e suggerimenti per la tua ricerca\n CityLife, Fiera"), "CityLife, Fiera")
        self.assertEqual(r("La tua ricerca è attiva!\nGuarda", "La tua ricerca è attiva!"), "")
        self.assertEqual(r(""), "")

    def test_smistamento_profili(self):
        self.assertIsNone(fonti.profilo_ricerca(fonti._casa_ricerca("La tua ricerca Milano (prov.)")))
        self.assertEqual(fonti.profilo_ricerca(fonti._casa_ricerca("La tua ricerca Casa.it - Family")), "famiglia")


class Annunci(unittest.TestCase):
    def test_campi(self):
        a = parse("riepilogo")[0]
        self.assertEqual((a["id"], a["prezzo"], a["mq"], a["locali"], a["bagni"]), ("55045777", 535000, 280, "5", "3"))
        self.assertEqual(a["indirizzo"], "Via Giacomo Leopardi 21, Arese")

    def test_posto_auto_singolare_e_plurale(self):
        self.assertTrue(parse("riepilogo")[0]["box"])  # "1 posto auto"
        self.assertTrue(parse("nuovo")[0]["box"])  # "2 posti auto"
        self.assertTrue(any(not a["box"] for a in parse("riepilogo")))


if __name__ == "__main__":
    unittest.main()
