"""Riconoscimento delle camere nelle descrizioni (agents/camere.py). Le frasi
sono prese da annunci reali (Subito, Tecnocasa, Gabetti, Dove.it) del 2026-11-03."""
import unittest

from agents import camere, famiglia


def n(testo, locali=4, minimo=3):
    return camere.camere(testo, locali, minimo)


class NumeroEsplicito(unittest.TestCase):
    def test_con_aggettivi(self):
        self.assertEqual(n("la zona notte presenta tre spaziose camere da letto e due bagni"), 3)
        self.assertEqual(n("tre comode e funzionali camere da letto, due bagni, di cui uno finestrato"), 3)
        self.assertEqual(n("* zona notte: tre confortevoli camere da letto e un bagno finestrato"), 3)
        self.assertEqual(n("la zona notte offre tre autentiche camere matrimoniali"), 3)
        self.assertEqual(n("la zona notte comprende due spaziose camere da letto, doppi servizi"), 2)
        self.assertEqual(n("con 3 camere da letto"), 3)

    def test_il_numero_non_e_dei_bagni(self):
        self.assertEqual(n("troviamo zona cucina oltre ad un gran disimpegno per due bagni e tre camere da letto"), 3)
        self.assertEqual(n("salone doppio, cucina abitabile, due bagni e tre camere di ampia metratura"), 3)

    def test_ulteriori(self):
        self.assertEqual(n("cucina abitabile, a una camera da letto e a un bagno finestrato. "
                           "composta da tre ulteriori camere da letto, di cui una con balcone"), 4)
        self.assertEqual(n("una prima camera comoda e luminosa, due ulteriori camere da letto spaziose"), 3)
        self.assertEqual(n("un bagno e una camera da letto padronale. il piano superiore ospita due ulteriori "
                           "stanze, ideali da adibire a camere da letto"), 3)

    def test_coda_e_una_singola(self):
        self.assertEqual(n("3 grandi camere e una camera matrimoniale, a seguire un bagno"), 4)
        self.assertEqual(n("due camere da letto, una matrimoniale e una doppia"), 2)  # spiega le due
        self.assertEqual(n("tre camere da letto -- due matrimoniali e una singola -- e doppi servizi"), 3)

    def test_refuso_singolare(self):
        self.assertEqual(n("piano primo composto da due camera matrimoniali entrambe con balcone"), 2)

    def test_stanze_senza_da_letto_non_contano(self):
        self.assertIsNone(n("predisposizione nelle altre stanze, zanzariere"))


class Ordinali(unittest.TestCase):
    def test_terza_camera(self):
        self.assertEqual(n("la zona notte ospita due spaziose camere matrimoniali, oltre a una terza camera, "
                           "ideale come cameretta o studio"), 3)
        self.assertEqual(n("2° camera, bagno con doccia, 3° camera, bagno con doccia e finestra"), 3)
        self.assertEqual(n("due camere da letto e un bagno finestrato. completano il piano un ulteriore "
                           "disimpegno con una terza camera con balconcino", locali=5), 3)

    def test_prima_camera_da_sola_non_conta(self):
        self.assertIsNone(camere.conta("completano il piano una prima camera da letto e un bagno di design"))

    def test_almeno_n_sotto_la_stima_resta_da_verificare(self):
        # quadrilocale: "seconda camera" dice almeno 2, ma potrebbe essercene una terza non citata
        self.assertIsNone(n("composta da camera matrimoniale, seconda camera da letto e due bagni"))
        # se la stima dai locali è 2 (trilocale), "almeno 2" basta
        self.assertEqual(n("composta da camera matrimoniale, seconda camera da letto e due bagni", locali=3), 2)


class Elenco(unittest.TestCase):
    def test_qualificativi_diversi(self):
        self.assertEqual(n("ingresso, ampio soggiorno, cucina semi- abitabile, camera doppia, cameretta, "
                           "camera matrimoniale con bagno"), 3)
        self.assertEqual(n("camera padronale con bagno en suite e cabina armadio, cameretta, camera/studio, bagno"), 3)

    def test_riferimenti_non_contano(self):
        self.assertIsNone(n("cameretta, ripostiglio e camera matrimoniale. aria condizionata in soggiorno e "
                            "in camera da letto"))

    def test_descrizione_troncata(self):
        self.assertIsNone(n("la zona notte è composta da una camera singola con bagno en suite finestrato, "
                            "una camera matrimoniale...", locali=5))

    def test_una_sola_menzione(self):
        self.assertIsNone(n("camera matrimoniale con angolo cabina armadio, bagno padronale finestrato"))


class SoloPotenziali(unittest.TestCase):
    def test_esclusi(self):
        casi = [
            "camera matrimoniale, cameretta, doppi servizi e possibilita' di ricavare facilmente la 3° camera da letto",
            "la zona pranzo può essere facilmente trasformata in una terza camera da letto",
            "consentono di valutare la realizzazione di una terza camera da letto",
            "uno studio (ideale per lo smart working o come terza camera)",
            "la soluzione si può facilmente riconvertire ad appartamento con 3 camere da letto",
            "la possibilità di ricavare da quattro a cinque camere, a seconda del progetto",
            "appartamento di circa 115 mq con possibilità di tre camere, ampio soggiorno",
            "hai bisogno di una terza camera da letto?",
            "una stanza versatile, ideale come studio, palestra o camera per ospiti",
            "si presta a essere utilizzato come camera per ragazzi",
        ]
        for t in casi:
            with self.subTest(t=t):
                r = camere.conta(t)
                self.assertTrue(r is None or r[0] < 3, (t, r))

    def test_reali_con_potenziale_accanto(self):
        # due camere reali + terza solo possibile → 2
        self.assertEqual(n("attualmente composta da due camere da letto, una matrimoniale e una doppia. "
                           "consentono di valutare la realizzazione di una terza camera da letto"), 2)
        self.assertEqual(n("cucina abitabile, tre camere da letto, doppi servizi. di ricavare una quarta camera "
                           "utilizzando una parte del soggiorno"), 3)

    def test_tre_o_quattro(self):
        self.assertEqual(n("tre camere da letto, doppi servizi. ideale per chi cerca tre o quattro camere"), 3)

    def test_ristrutturato_non_e_potenziale(self):
        self.assertEqual(n("perfettamente ristrutturato con travi a vista 2 camere da letto piu 2 bagni", locali=3), 2)


class FalsiAmici(unittest.TestCase):
    def test_infissi_e_altro(self):
        for t in ("infissi in pvc con doppia camera e triplo vetro", "triplo vetro con camera d'aria e gas argon",
                  "tetto con isolamento termoacustico, camera di ventilazione e manto in coppi",
                  "iscritta alla camera di commercio"):
            with self.subTest(t=t):
                self.assertIsNone(camere.conta(t))

    def test_vuoto(self):
        self.assertIsNone(camere.conta(""))
        self.assertIsNone(camere.conta(None))
        self.assertIsNone(n(None))


class Integrazione(unittest.TestCase):
    def test_famiglia_usa_il_nuovo_riconoscimento(self):
        a = {"fonte": "Subito.it", "titolo": "Quadrilocale", "locali": "4",
             "descrizione": "ingresso, soggiorno doppio, cucina abitabile. la zona notte presenta tre spaziose camere "
                            "da letto e due bagni, di cui uno finestrato. cantina e box."}
        c = famiglia.caratteristiche(a)
        self.assertEqual((c["camere"], c["camere_stimate"]), (3, False))

    def test_famiglia_dati_strutturati_prima_del_testo(self):
        c = famiglia.caratteristiche({"fonte": "Tecnocasa", "camere": 4, "descrizione": "tre spaziose camere " * 10})
        self.assertEqual(c["camere"], 4)

    def test_famiglia_stima_se_incerto(self):
        a = {"fonte": "Subito.it", "titolo": "Quadrilocale", "locali": "4",
             "descrizione": "composta da camera matrimoniale, seconda camera da letto e due bagni. " * 3}
        c = famiglia.caratteristiche(a)
        self.assertEqual((c["camere"], c["camere_stimate"]), (3, True))

    def test_minimo_dal_config(self):
        a = {"fonte": "Subito.it", "locali": "5",
             "descrizione": "due camere da letto e un bagno finestrato. un ulteriore disimpegno con una terza camera. " * 2}
        self.assertTrue(famiglia.caratteristiche(a, camere_min=4)["camere_stimate"])
        self.assertEqual(famiglia.caratteristiche(a, camere_min=3)["camere"], 3)


if __name__ == "__main__":
    unittest.main()
