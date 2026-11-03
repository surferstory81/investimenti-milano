"""Piano normalizzato (agents/piano.py) e preferenza per piani intermedi e alti
nel punteggio famiglia. Formati e frasi da annunci reali del 2026-11-03."""
import unittest

from agents import famiglia, piano


def classe(v=None, descrizione=None):
    return piano.piano({"piano": v, "descrizione": descrizione})["classe"]


class CampoFonte(unittest.TestCase):
    def test_subito(self):
        self.assertEqual([classe(v) for v in ("0", "1", "2", "3", "4", "7", "Rialzato", "Seminterrato", "Oltre il 7°")],
                         ["terra", "primo", "intermedio", "intermedio", "alto", "alto", "terra", "seminterrato", "alto"])
        self.assertEqual(piano.piano({"piano": "Oltre il 7°"})["n"], 8)

    def test_tecnocasa(self):
        p = piano.piano({"piano": "5 di 5 con ascensore (ultimo piano)"})
        self.assertEqual((p["n"], p["ultimo"], p["classe"]), (5, True, "alto"))
        p = piano.piano({"piano": "3 di 3 con ascensore"})
        self.assertEqual((p["n"], p["ultimo"], p["classe"]), (3, True, "alto"))  # ultimo anche se 3°
        self.assertEqual(classe("2 di 6 con ascensore (piano medio)"), "intermedio")
        self.assertEqual(classe("1 di 8 con ascensore (piano basso)"), "primo")
        self.assertEqual(classe("Attico di 3 con ascensore"), "alto")
        self.assertEqual(classe("Medio di 3 con ascensore"), "intermedio")
        self.assertEqual(classe("Basso di 1"), "primo")
        self.assertIsNone(classe("Su più livelli di 5 con ascensore"))

    def test_gabetti(self):
        self.assertEqual([classe(v) for v in ("Terra", "Primo", "Terzo", "Nono", "Sedicesimo")],
                         ["terra", "primo", "intermedio", "alto", "alto"])

    def test_dove(self):
        p = piano.piano({"piano": "5 - 6 di 6, con ascensore"})
        self.assertEqual((p["n"], p["ultimo"], p["classe"]), (5, True, "alto"))
        self.assertEqual(classe("3 di 5, con ascensore"), "intermedio")
        self.assertEqual(classe("terra di 6, con ascensore"), "terra")

    def test_idealista(self):
        self.assertEqual(classe("3º piano con ascensore"), "intermedio")
        self.assertEqual(classe("piano terra con ascensore"), "terra")
        self.assertEqual(classe("1° piano senza ascensore"), "primo")

    def test_vuoto(self):
        self.assertIsNone(classe())
        self.assertIsNone(classe(""))
        self.assertIsNone(classe("boh"))


class Descrizione(unittest.TestCase):
    def test_frasi_esplicite(self):
        self.assertEqual(classe(descrizione="un esclusivo appartamento al quarto piano, situato in una zona comoda"), "alto")
        self.assertEqual(classe(descrizione="l'appartamento è posto al secondo piano con ascensore"), "intermedio")
        self.assertEqual(classe(descrizione="situata all'ottavo ed ultimo piano, la proprietà gode di una vista"), "alto")
        self.assertEqual(classe(descrizione="l'appartamento al 6 piano è formato da soggiorno, cucina"), "alto")
        self.assertEqual(classe(descrizione="ampio quadrilocale situato al piano rialzato di un contesto condominiale"), "terra")
        p = piano.piano({"descrizione": "appartamento disposto su due livelli, situato all'ultimo piano in via 25 aprile"})
        self.assertEqual((p["n"], p["ultimo"], p["classe"], p["da_testo"]), (None, True, "alto", True))

    def test_altro_non_conta(self):
        for t in ("è compresa una cantina di pertinenza posta al piano terra",
                  "all'ingresso situato al piano terra, ci accoglie il locale lavanderia",
                  "box auto situato al primo piano interrato",
                  "al piano terra si trova la portineria"):
            with self.subTest(t=t):
                self.assertIsNone(classe(descrizione=t))

    def test_campo_prima_del_testo(self):
        p = piano.piano({"piano": "2", "descrizione": "appartamento situato al piano terra"})
        self.assertEqual((p["classe"], p["da_testo"]), ("intermedio", False))

    def test_primo_valido_dopo_uno_scartato(self):
        t = "cantina posta al piano terra. l'appartamento è situato al terzo piano"
        self.assertEqual(classe(descrizione=t), "intermedio")


class Etichetta(unittest.TestCase):
    def test_testi(self):
        e = lambda v: piano.etichetta(piano.piano({"piano": v}))  # noqa: E731
        self.assertEqual(e("3"), "3° piano")
        self.assertEqual(e("5 di 5 con ascensore"), "5° piano (ultimo)")
        self.assertEqual(e("0"), "piano terra")
        self.assertEqual(e("Seminterrato"), "seminterrato")
        self.assertEqual(e("Attico di 3"), "ultimo piano")
        self.assertEqual(e("Medio di 3"), "piano medio")
        self.assertIsNone(e(None))


class PunteggioFamiglia(unittest.TestCase):
    F = {"camere_min": 3, "bagni_min": 2, "mq_min": 95, "mq_ideale": 140,
         "pesi": {"posizione": 28, "camere": 12, "bagni": 9, "salone": 7, "cucina_abitabile": 7, "prezzo": 7,
                  "metratura": 3, **{k: 1 for k, _, _ in famiglia.PLUS + famiglia.BIMBI}}}

    def valuta(self, piano_campo, pesi=None):
        a = {"id": "x", "fonte": "Subito.it", "titolo": "Quadrilocale", "locali": "4", "bagni": "2", "mq": 120,
             "prezzo": 900000, "prezzo_mq": 7500, "piano": piano_campo, "comune": "Milano", "km_centro": 1.0,
             "descrizione": "salone doppio, cucina abitabile, tre spaziose camere da letto e due bagni. " * 2}
        a["caratteristiche"] = famiglia.caratteristiche(a)
        famiglia.valuta(a, {"_tutti": 7500}, dict(self.F, pesi=pesi or self.F["pesi"]))
        return a

    def test_alti_e_intermedi_davanti(self):
        p = {v: self.valuta(v)["punteggio"] for v in ("0", "1", "3", "6", None)}
        self.assertEqual(p["3"], p["6"])
        self.assertGreater(p["3"], p[None])
        self.assertGreater(p[None], p["1"])
        self.assertGreater(p["1"], p["0"])

    def test_peso_e_campi(self):
        a = self.valuta("6")
        self.assertEqual(a["punteggi"]["piano"], famiglia.PESO_PIANO)
        self.assertEqual((a["piano_info"], a["piano_classe"]), ("6° piano", "alto"))
        self.assertNotIn("Piano", " ".join(a["mancano"]))  # preferenza, non requisito
        self.assertIsNone(self.valuta(None)["piano_info"])

    def test_peso_dal_config(self):
        a = self.valuta("0", pesi=dict(self.F["pesi"], piano=20))
        self.assertAlmostEqual(a["punteggi"]["piano"], 2.0)

    def test_punteggio_resta_su_100(self):
        self.assertLessEqual(self.valuta("6")["punteggio"], 100)


if __name__ == "__main__":
    unittest.main()
