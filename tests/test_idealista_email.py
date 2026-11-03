"""Lettore degli avvisi email di Idealista (agents.fonti, fonte idealista_email).

Le email in tests/dati/ sono avvisi reali ricevuti il 2026-11-03, ripuliti da
nome, indirizzi email, token di tracciamento e stili."""
import email.message
import unittest
from pathlib import Path
from unittest import mock

from agents import catalogatore, famiglia, fonti, ricerca

DATI = Path(__file__).parent / "dati"


def html(nome):
    return (DATI / f"idealista_{nome}.html").read_text(encoding="utf-8")


def parse(nome, oggetto=""):
    return fonti._idealista_email_parse(html(nome), oggetto)


R_STUDENTI = {"prezzo_min": 50000, "prezzo_max": 200000, "locali_min": 1, "locali_max": 2}


def grezzo(**kw):
    x = dict(id="1", titolo="Bilocale in Via Padova, 10, NoLo, Milano",
             indirizzo="Via Padova, 10, NoLo, Milano", prezzo=150000.0, prezzo_precedente=None,
             mq=45.0, locali="2", bagni=None, piano="2º piano con ascensore", ascensore=True,
             box=False, asta=False, descrizione="Bilocale luminoso", ricerca="Monolocali")
    x.update(kw)
    return x


class AvvisoSingolo(unittest.TestCase):
    def test_asta(self):
        (a,) = parse("asta")
        self.assertEqual(a["id"], "37349580")
        self.assertEqual(a["titolo"], "Monolocale in Via Francesco de Sanctis s.n.c, "
                                      "Stadera - Abbiategrasso, Milano")
        self.assertEqual(a["indirizzo"], "Via Francesco de Sanctis, Stadera - Abbiategrasso, Milano")
        self.assertEqual(a["prezzo"], 80797)
        self.assertIsNone(a["prezzo_precedente"])
        self.assertEqual((a["mq"], a["locali"]), (35, "1"))
        self.assertEqual(a["piano"], "3º piano senza ascensore")
        self.assertFalse(a["ascensore"])
        self.assertFalse(a["box"])
        self.assertTrue(a["asta"])
        self.assertTrue(a["descrizione"].startswith("DATA ASTA 12/01/2027"))
        self.assertNotIn("Contatta", a["descrizione"])
        self.assertEqual(a["ricerca"], "Monolocali")

    def test_diminuzione_di_prezzo(self):
        (a,) = parse("ribasso")
        self.assertEqual(a["id"], "35519054")
        self.assertEqual(a["prezzo"], 980000)
        self.assertEqual(a["prezzo_precedente"], 1050000)
        self.assertEqual((a["mq"], a["locali"]), (140, "4"))  # "4 locali" esplicito
        self.assertTrue(a["box"])  # "Box compreso"
        self.assertTrue(a["ascensore"])
        self.assertFalse(a["asta"])
        self.assertEqual(a["indirizzo"], "Via Sebastiano del Piombo, Fiera, Milano")
        self.assertEqual(a["ricerca"], "Case e appartamenti a Milano")

    def test_ricerca_dall_oggetto_se_manca_nel_corpo(self):
        h = html("asta").replace("Vedi tutti gli annunci: Monolocali", "")
        (a,) = fonti._idealista_email_parse(
            h, "Nuovo monolocale per la tua ricerca: Studenti\n Milano!")
        self.assertEqual(a["ricerca"], "Studenti Milano")

    def test_senza_ricerca_ne_oggetto(self):
        h = html("asta").replace("Vedi tutti gli annunci: Monolocali", "")
        self.assertEqual(fonti._idealista_email_parse(h)[0]["ricerca"], "")

    def test_email_non_di_annunci(self):
        self.assertEqual(fonti._idealista_email_parse("<p>Nuovo accesso al tuo account</p>"), [])

    def test_blocco_senza_prezzo_al_mq_ignorato(self):
        h = '<a href="https://www.idealista.it/immobile/1/">Bilocale in Via X, Milano</a><p>100.000 €</p>'
        self.assertEqual(fonti._idealista_email_parse(h), [])


class RiepilogoGiornaliero(unittest.TestCase):
    def setUp(self):
        self.annunci = parse("riepilogo", "Riepilogo giornaliero dei nuovi annunci")
        self.per_id = {a["id"]: a for a in self.annunci}

    def test_tutti_gli_annunci_una_volta(self):
        self.assertEqual(len(self.annunci), 33)
        self.assertEqual(len(self.per_id), 33)

    def test_ricerca_di_ogni_sezione(self):
        conta = {}
        for a in self.annunci:
            conta[a["ricerca"]] = conta.get(a["ricerca"], 0) + 1
        self.assertEqual(conta, {"Case e appartamenti a Sesto San Giovanni": 9,
                                 "Monolocali": 20, "Case e appartamenti a Milano": 4})
        self.assertEqual(self.annunci[0]["ricerca"], "Case e appartamenti a Sesto San Giovanni")
        self.assertEqual(self.annunci[-1]["ricerca"], "Case e appartamenti a Milano")

    def test_titoli_troncati_ricostruiti(self):
        self.assertFalse([a["titolo"] for a in self.annunci if a["titolo"].endswith("...")])
        a = self.per_id["37241616"]
        self.assertEqual(a["indirizzo"], "Via Risorgimento, 46, Rondò-Torretta, Sesto San Giovanni")

    def test_titolo_senza_via(self):
        a = self.per_id["36416494"]  # "Monolocale a Rondò-Torretta, Sesto San Giovanni"
        self.assertEqual(a["indirizzo"], "Rondò-Torretta, Sesto San Giovanni")

    def test_locali_dal_tipo_non_dalle_camere(self):
        # nel riepilogo "N cam. da letto" coincide con i locali: Monolocale → 1, Bilocale → 2
        self.assertEqual(self.per_id["37240665"]["locali"], "1")
        self.assertEqual(self.per_id["37241616"]["locali"], "2")

    def test_aste_marcate(self):
        self.assertEqual(sum(a["asta"] for a in self.annunci), 9)
        self.assertTrue(self.per_id["37240665"]["asta"])
        self.assertFalse(self.per_id["37241616"]["asta"])

    def test_campi_numerici(self):
        for a in self.annunci:
            self.assertGreater(a["prezzo"], 0, a["id"])
            self.assertGreater(a["mq"], 0, a["id"])
            self.assertTrue(a["locali"].isdigit(), a["id"])


class Indirizzo(unittest.TestCase):
    def test_casi(self):
        f = fonti._idealista_indirizzo
        self.assertEqual(f("Bilocale in Via Padova, 31, NoLo, Milano"), "Via Padova, 31, NoLo, Milano")
        self.assertEqual(f("Attico in Via X s.n.c, Brera, Milano"), "Via X, Brera, Milano")
        self.assertEqual(f("Bilocale in Via X, Brera, Mila..."), "Via X, Brera, Milano")
        self.assertEqual(f("Bilocale in Via X, Brera,..."), "Via X, Brera, Milano")
        self.assertEqual(f("Bilocale in Via X, 3, Indip..."), "Via X, 3")
        self.assertEqual(f("Monolocale a Centro, Sesto San Giovanni"), "Centro, Sesto San Giovanni")
        self.assertEqual(f("Appartamento su due piani in Via Y, 3, Milano"), "Via Y, 3, Milano")


class Filtri(unittest.TestCase):
    def test_record_normalizzato(self):
        (r,) = fonti.idealista_email_filtra([grezzo(box=True, prezzo_precedente=160000.0)], R_STUDENTI)
        self.assertEqual(r["id"], "idealista-1")
        self.assertEqual(r["fonte"], "Idealista")
        self.assertEqual(r["url"], "https://www.idealista.it/immobile/1/")
        self.assertEqual((r["prezzo"], r["prezzo_precedente"], r["mq"], r["locali"]),
                         (150000.0, 160000.0, 45.0, "2"))
        self.assertEqual(r["box"], 1)
        self.assertTrue(r["ascensore"])
        self.assertEqual(r["descrizione"], "Bilocale luminoso")
        self.assertIsNone(r["lat"])
        self.assertEqual(set(fonti.base_record()) - set(r), set())

    def test_senza_box(self):
        (r,) = fonti.idealista_email_filtra([grezzo()], R_STUDENTI)
        self.assertIsNone(r["box"])

    def test_prezzo_e_locali(self):
        tieni = fonti.idealista_email_filtra([
            grezzo(id="ok"), grezzo(id="caro", prezzo=250000.0), grezzo(id="basso", prezzo=10000.0),
            grezzo(id="senza_prezzo", prezzo=None), grezzo(id="tri", locali="3"),
            grezzo(id="locali_ignoti", locali=None)], R_STUDENTI)
        self.assertEqual([r["id"] for r in tieni], ["idealista-ok", "idealista-locali_ignoti"])

    def test_profilo_dalla_ricerca_salvata(self):
        annunci = [grezzo(id="f", ricerca="Famiglia Milano"), grezzo(id="s", ricerca="Studenti"),
                   grezzo(id="n", ricerca="Case e appartamenti a Milano")]
        studenti = fonti.idealista_email_filtra(annunci, R_STUDENTI, "studenti")
        fam = fonti.idealista_email_filtra(annunci, R_STUDENTI, "famiglia")
        self.assertEqual([r["id"] for r in studenti], ["idealista-s", "idealista-n"])
        self.assertEqual([r["id"] for r in fam], ["idealista-f", "idealista-n"])

    def test_asta_scartata_dal_catalogatore(self):
        (r,) = fonti.idealista_email_filtra([grezzo(asta=True)], R_STUDENTI)
        self.assertIn({"etichetta": "Asta giudiziaria", "tipo": "esclusione"}, catalogatore.segnali(r))


class FakeIMAP:
    """Casella finta: restituisce le email nell'ordine di arrivo."""

    def __init__(self, messaggi):
        self.messaggi = messaggi
        self.ricerche, self.chiusa = [], False

    def search(self, charset, *criteri):
        self.ricerche.append(criteri)
        return "OK", [" ".join(str(i + 1) for i in range(len(self.messaggi))).encode()]

    def fetch(self, num, parti):
        return "OK", [(b"1", self.messaggi[int(num) - 1].as_bytes())]

    def logout(self):
        self.chiusa = True


def messaggio(oggetto, corpo_html, testo=None):
    m = email.message.EmailMessage()
    m["Subject"] = oggetto
    m["From"] = "idealista <nonrispondere@idealista.it>"
    if testo:
        m.set_content(testo)
        m.add_alternative(corpo_html, subtype="html")
    else:
        m.set_content(corpo_html, subtype="html")
    return m


class LetturaCasella(unittest.TestCase):
    def test_email_piu_recente_vince(self):
        ribasso = html("ribasso")
        prima = ribasso.replace("980.000", "1.010.000")  # stesso annuncio, prezzo più vecchio
        imap = FakeIMAP([messaggio("Diminuzione di prezzo per la tua ricerca: X", prima),
                         messaggio("Diminuzione di prezzo per la tua ricerca: X", ribasso,
                                   testo="versione testo ignorata")])
        with mock.patch.object(fonti, "_imap", return_value=imap):
            (a,) = fonti._idealista_email_annunci({}, 30)
        self.assertEqual(a["prezzo"], 980000)
        self.assertTrue(imap.chiusa)
        (criteri,) = imap.ricerche
        self.assertEqual(criteri[:3], ("FROM", fonti.IDEALISTA_MITTENTE, "SINCE"))

    def test_idealista_email_completo(self):
        imap = FakeIMAP([messaggio("Riepilogo giornaliero dei nuovi annunci", html("riepilogo")),
                         messaggio("Nuovo monolocale per la tua ricerca: Monolocali!", html("asta"))])
        cfg = {"ricerca": R_STUDENTI}
        with mock.patch.object(fonti, "_imap", return_value=imap), \
                mock.patch.object(fonti, "geocode_all") as geo, \
                mock.patch.object(fonti, "log") as log:
            out = fonti.idealista_email(cfg)
        self.assertTrue(out)
        self.assertTrue(all(R_STUDENTI["prezzo_min"] <= r["prezzo"] <= R_STUDENTI["prezzo_max"]
                            and int(r["locali"]) <= 2 for r in out))
        self.assertIn("idealista-37349580", {r["id"] for r in out})
        geo.assert_called_once_with(out)
        self.assertIn(f"{len(out)} annunci nel range", log.call_args[0][1])


class Integrazione(unittest.TestCase):
    def test_ricerca_preferisce_annuncio_dal_sito(self):
        dal_sito = fonti.base_record(id="idealista-1", fonte="Idealista", prezzo=150000.0,
                                     descrizione="dal sito", lat=45.478, lon=9.227)
        da_email = [fonti.base_record(id="idealista-1", fonte="Idealista", descrizione="email",
                                      lat=45.478, lon=9.227),
                    fonti.base_record(id="idealista-2", fonte="Idealista", prezzo=120000.0,
                                      lat=45.478, lon=9.227)]
        cfg = {"universita": [{"nome": "Poli", "zona": "Città Studi", "lat": 45.4781, "lon": 9.2272}],
               "ricerca": {"raggio_universita_km": 1.6, "fonti": ["idealista", "idealista_email"]}}
        salvati = {}
        ff = mock.MagicMock()
        with mock.patch.object(ricerca, "load_config", return_value=cfg), \
                mock.patch.object(ricerca, "Firefox", return_value=ff), \
                mock.patch.object(ricerca.fonti, "idealista", return_value=[dal_sito]), \
                mock.patch.object(ricerca.fonti, "idealista_email", return_value=da_email), \
                mock.patch.object(ricerca.fonti, "subito", return_value=[]), \
                mock.patch.object(ricerca, "load_json", return_value={}), \
                mock.patch.object(ricerca, "save_json", side_effect=salvati.__setitem__), \
                mock.patch.object(ricerca, "log"):
            ricerca.run()
        g = salvati["grezzi.json"]
        self.assertEqual(g["per_fonte"], {"Idealista": 1, "Idealista (avvisi)": 1})
        self.assertEqual([(a["id"], a["descrizione"]) for a in g["vendita"]],
                         [("idealista-1", "dal sito"), ("idealista-2", None)])

    def test_famiglia_estratto_non_conta_come_descrizione(self):
        lungo = "Appartamento luminoso con terrazzo, " * 5
        email_ = famiglia.caratteristiche({"fonte": "Idealista", "titolo": "Quadrilocale",
                                           "descrizione": lungo})
        sito = famiglia.caratteristiche({"fonte": "Subito.it", "titolo": "Quadrilocale",
                                         "descrizione": lungo})
        self.assertFalse(email_["testo"])
        self.assertTrue(email_["terrazzo"])  # quello che c'è nell'estratto conta
        self.assertTrue(sito["testo"])
        self.assertIn("Idealista", famiglia.FONTI_EMAIL)

    def test_famiglia_raccoglie_avvisi_idealista(self):
        nomi = []
        f = {"tecnocasa_comuni": []}
        with mock.patch.object(famiglia.fonti, "idealista_email", return_value=[]) as ie, \
                mock.patch.object(famiglia, "log"):
            famiglia._raccogli({}, f, lambda nome, fn: (nomi.append(nome), fn()) if "Idealista" in nome
                               else nomi.append(nome))
        self.assertIn("Idealista (avvisi)", nomi)
        cfg_arg, r_arg, profilo = ie.call_args[0]
        self.assertEqual(profilo, "famiglia")
        self.assertEqual(r_arg["locali_max"], 99)


if __name__ == "__main__":
    unittest.main()
