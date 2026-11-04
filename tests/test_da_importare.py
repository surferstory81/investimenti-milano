"""Annunci da completare col segnalibro (dagli avvisi email, non ancora importati)
e segnale "Asta giudiziaria" senza falsi positivi sulla posizione."""
import unittest
from unittest import mock

from agents import catalogatore, famiglia, fonti
from tests.test_zone_preferiti import WASHINGTON, Memoria, ZoneFamiglia


def asta(testo):
    return any(s["etichetta"] == "Asta giudiziaria" for s in catalogatore.segnali({"descrizione": testo}))


class Asta(unittest.TestCase):
    def test_tribunale_come_posizione_non_e_asta(self):
        # testo reale di casa-54672211 (Corso di Porta Romana), importato il 2026-11-04
        self.assertFalse(asta("La posizione è particolarmente strategica: a pochi passi dal Tribunale di Milano "
                              "e dal quartiere Guastalla"))
        self.assertFalse(asta("Portineria con custode, vicino al tribunale"))

    def test_aste_vere(self):
        for t in ("Vendita all'asta del 12/12", "aste giudiziarie Milano", "vendita giudiziaria",
                  "Tribunale di Milano, procedura esecutiva n. 123/2024", "R.G.E. 456/2023",
                  "rivolgersi al custode giudiziario", "professionista delegato alla vendita"):
            self.assertTrue(asta(t), t)

    def test_parole_che_contengono_asta(self):
        self.assertFalse(asta("basta poco per renderlo perfetto, pastasciutta, castano"))


class DaImportare(unittest.TestCase):
    def esegui(self, verifiche=None):
        # prezzi e metrature diversi: altrimenti sono doppioni dello stesso immobile
        annunci = [fonti.base_record(id=i, fonte=fonte, lat=WASHINGTON[0] + k / 1000, lon=WASHINGTON[1],
                                     titolo="Quadrilocale", prezzo=800000.0 + k * 70000, mq=110.0 + k * 15,
                                     locali="4", bagni="2")
                   for k, (i, fonte) in enumerate((("casa-1", "Casa.it"), ("idealista-2", "Idealista"),
                                                   ("subito-3", "Subito.it")))]
        mem = Memoria({"famiglia_grezzi.json": {"annunci": annunci, "per_fonte": {}},
                       "verifiche.json": verifiche or {}})
        with mock.patch.object(famiglia, "load_config", return_value={"famiglia": ZoneFamiglia.F}), \
                mock.patch.object(famiglia, "load_json", mem.load), \
                mock.patch.object(famiglia, "save_json", mem.save), \
                mock.patch.object(famiglia, "log"):
            famiglia.run(solo_valuta=True)
        d = mem.dati["famiglia.json"]
        return d, {a["id"]: a["da_importare"] for a in d["top"] + d["altri"]}

    def test_avvisi_non_importati(self):
        d, da = self.esegui()
        self.assertEqual(da, {"casa-1": True, "idealista-2": True, "subito-3": False})
        self.assertEqual({a["id"] for a in d["avvisi"]}, {"casa-1", "idealista-2"})

    def test_importato_esce_dalla_lista(self):
        v = {"casa-1": {"id": "casa-1", "testo": "Quadrilocale con salone e cucina abitabile, tre camere",
                        "importato": "2026-11-04T12:44:46", "camere": 3, "bagni": 2, "locali": 4}}
        d, da = self.esegui(v)
        self.assertEqual(da, {"casa-1": False, "idealista-2": True, "subito-3": False})
        self.assertEqual([a["id"] for a in d["avvisi"]], ["idealista-2"])


if __name__ == "__main__":
    unittest.main()
