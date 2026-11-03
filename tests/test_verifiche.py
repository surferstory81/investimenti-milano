"""Import manuale degli annunci (agents/verifiche.py, /api/importa) e scelta del
doppione più completo (catalogatore.duplicati)."""
import json
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer
from unittest import mock

import server
from agents import catalogatore, famiglia, fonti, verifiche

PAGINA = ("Quadrilocale in vendita in Via Plinio, 5, Milano\n980.000 €\n"
          "Caratteristiche\nLocali\n4\nCamere da letto\n3\nBagni\n2\nPiano 3\n"
          "Descrizione\nIngresso, ampio salone doppio con accesso al terrazzo, cucina abitabile, "
          "tre camere, doppi servizi, cantina e box auto. Riscaldamento centralizzato. "
          "Stabile signorile con portineria e giardino condominiale.")


class Memoria:
    """Sostituisce data/verifiche.json."""

    def __init__(self):
        self.dati = {}

    def load(self, nome, default=None):
        return json.loads(json.dumps(self.dati.get(nome, default)))

    def save(self, nome, obj):
        self.dati[nome] = obj


class IdDaUrl(unittest.TestCase):
    def test_portali(self):
        self.assertEqual(verifiche.id_da_url("https://www.casa.it/immobili/53829066/?x=1"), "casa-53829066")
        self.assertEqual(verifiche.id_da_url("https://www.idealista.it/immobile/35519054/"), "idealista-35519054")
        self.assertEqual(verifiche.id_da_url("https://www.immobiliare.it/annunci/133831846/"),
                         "immobiliare-133831846")
        self.assertIsNone(verifiche.id_da_url("https://www.subito.it/appartamenti/x-123.htm"))
        self.assertIsNone(verifiche.id_da_url(None))

    def test_stessi_id_delle_fonti_email(self):
        (r,) = fonti.idealista_email_filtra(
            [dict(id="35519054", titolo="t", indirizzo="i", prezzo=1.0, prezzo_precedente=None, mq=1,
                  locali=None, bagni=None, piano=None, ascensore=False, box=False, asta=False,
                  descrizione="", ricerca="")],
            {"prezzo_min": 0, "prezzo_max": 10, "locali_min": 1, "locali_max": 9})
        self.assertEqual(verifiche.id_da_url(r["url"]), r["id"])


class Estrai(unittest.TestCase):
    def test_etichetta_e_valore_su_righe_separate(self):
        self.assertEqual(verifiche.estrai(PAGINA), {"camere": 3, "bagni": 2, "locali": 4})

    def test_valore_prima_dell_etichetta_e_numeri_in_parole(self):
        t = "Trilocale, due camere da letto, 1 bagno, 3 locali"
        self.assertEqual(verifiche.estrai(t), {"camere": 2, "bagni": 1, "locali": 3})

    def test_due_punti(self):
        self.assertEqual(verifiche.estrai("Camere da letto: 4\nBagni: 3\nLocali: 6"),
                         {"camere": 4, "bagni": 3, "locali": 6})

    def test_jsonld_ha_la_precedenza(self):
        j = json.dumps({"@type": "Apartment", "numberOfBedrooms": 4,
                        "numberOfBathroomsTotal": {"value": "3"}, "numberOfRooms": 5})
        self.assertEqual(verifiche.estrai("2 camere da letto, 1 bagno", "[]\n" + j),
                         {"camere": 4, "bagni": 3, "locali": 5})

    def test_jsonld_annidato_e_non_valido(self):
        j = json.dumps({"@graph": [{"offers": {"itemOffered": {"numberOfBedrooms": 2}}}]})
        self.assertEqual(verifiche.estrai("", "non json\n" + j)["camere"], 2)

    def test_niente(self):
        self.assertEqual(verifiche.estrai("Bellissimo appartamento"),
                         {"camere": None, "bagni": None, "locali": None})

    def test_valori_assurdi_ignorati(self):
        self.assertIsNone(verifiche.estrai("Bagni\n0")["bagni"])
        self.assertIsNone(verifiche.estrai("Camere da letto: 45")["camere"])


class Importa(unittest.TestCase):
    def setUp(self):
        self.mem = Memoria()
        p1 = mock.patch.object(verifiche, "load_json", self.mem.load)
        p2 = mock.patch.object(verifiche, "save_json", self.mem.save)
        p1.start(), p2.start()
        self.addCleanup(mock.patch.stopall)

    def test_salva_e_sovrascrive(self):
        quando = datetime(2026, 11, 3, 10, 0)
        v = verifiche.importa({"u": "https://www.casa.it/immobili/1/", "t": "Quadrilocale", "x": PAGINA},
                              adesso=quando)
        self.assertEqual((v["id"], v["camere"], v["bagni"]), ("casa-1", 3, 2))
        self.assertEqual(v["importato"], "2026-11-03T10:00:00")
        verifiche.importa({"u": "https://www.casa.it/immobili/1/", "x": PAGINA.replace("Bagni\n2", "Bagni\n3")})
        salvate = self.mem.dati[verifiche.FILE]
        self.assertEqual(list(salvate), ["casa-1"])
        self.assertEqual(salvate["casa-1"]["bagni"], 3)

    def test_testo_troncato(self):
        v = verifiche.importa({"u": "https://www.casa.it/immobili/1/", "x": "x" * 50000})
        self.assertEqual(len(v["testo"]), verifiche.MAX_TESTO)

    def test_rifiuta_pagine_non_valide(self):
        for payload in ({"u": "https://www.subito.it/a.htm", "x": PAGINA},
                        {"u": "https://www.casa.it/immobili/1/", "x": "breve"},
                        {"u": "https://www.casa.it/immobili/1/", "x": "Verifica di sicurezza captcha " * 20}):
            with self.assertRaises(ValueError):
                verifiche.importa(payload)
        self.assertNotIn(verifiche.FILE, self.mem.dati)


class Applica(unittest.TestCase):
    V = {"casa-1": {"testo": PAGINA, "camere": 3, "bagni": None, "locali": 4, "importato": "2026-11-03T10:00:00"}}

    def test_completa_l_annuncio(self):
        a = verifiche.applica({"id": "casa-1", "descrizione": None, "bagni": "2", "locali": "3"}, self.V)
        self.assertEqual(a["descrizione"], PAGINA)
        self.assertEqual((a["camere"], a["bagni"], a["locali"]), (3, "2", 4))  # bagni non trovato: resta
        self.assertEqual(a["verificato"], "2026-11-03T10:00:00")

    def test_annuncio_senza_verifica_invariato(self):
        a = {"id": "casa-2", "descrizione": None}
        self.assertEqual(verifiche.applica(dict(a), self.V), a)

    def test_famiglia_niente_piu_da_verificare(self):
        a = verifiche.applica(fonti.base_record(id="casa-1", fonte="Casa.it", titolo="Quadrilocale",
                                                avviso_email=True, locali="4"), self.V)
        c = famiglia.caratteristiche(a)
        self.assertTrue(c["testo"])
        self.assertEqual(c["camere"], 3)
        self.assertFalse(c["camere_stimate"])
        self.assertTrue(c["salone"] and c["cucina_abitabile"] and c["terrazzo"] and c["box"])
        self.assertEqual(c["bagni"], 2)  # "doppi servizi" nel testo

    def test_famiglia_run_applica_le_verifiche(self):
        f = {"prezzo_min": 0, "prezzo_max": 2e6, "mq_min": 50, "mq_ideale": 100, "raggio_km": 12,
             "camere_min": 3, "bagni_min": 2, "top": 10,
             "pesi": {k: 1 for k in ("posizione", "camere", "bagni", "salone", "cucina_abitabile", "prezzo",
                                     "metratura", *[k for k, _, _ in famiglia.PLUS + famiglia.BIMBI])}}
        a = fonti.base_record(id="casa-1", fonte="Casa.it", titolo="Quadrilocale", prezzo=980000.0, mq=140.0,
                              lat=45.47, lon=9.20, avviso_email=True, locali="4")
        mem = Memoria()
        mem.dati = {"famiglia_grezzi.json": {"annunci": [a], "per_fonte": {"Casa.it (avvisi)": 1}},
                    verifiche.FILE: self.V}
        with mock.patch.object(famiglia, "load_config", return_value={"famiglia": f}), \
                mock.patch.object(famiglia, "load_json", mem.load), \
                mock.patch.object(famiglia, "save_json", mem.save), \
                mock.patch.object(famiglia, "log"):
            famiglia.run(solo_valuta=True)
        (r,) = mem.dati["famiglia.json"]["top"]
        self.assertEqual(r["verificato"], "2026-11-03T10:00:00")
        self.assertEqual(r["da_verificare"], [])
        self.assertEqual(r["mancano"], [])


class Doppioni(unittest.TestCase):
    def rec(self, fonte, **kw):
        return fonti.base_record(**{"fonte": fonte, "prezzo": 500000.0, "mq": 100.0, "lat": 45.47,
                                    "lon": 9.20, **kw})

    def test_preferisce_la_versione_dal_sito(self):
        email_casa = self.rec("Casa.it", id="casa-1", avviso_email=True, url="c")
        subito = self.rec("Subito.it", id="subito-1", descrizione="completa", url="s")
        (k,) = catalogatore.duplicati([email_casa, subito])
        self.assertEqual(k["id"], "subito-1")
        self.assertEqual(k["altre_fonti"], [{"fonte": "Casa.it", "url": "c"}])

    def test_tra_siti_resta_la_priorita_tecnocasa_casa(self):
        (k,) = catalogatore.duplicati([self.rec("Subito.it", id="s", url="s"),
                                       self.rec("Casa.it", id="c", url="c"),
                                       self.rec("Tecnocasa", id="t", url="t")])
        self.assertEqual(k["id"], "t")
        (k,) = catalogatore.duplicati([self.rec("Subito.it", id="s", url="s"), self.rec("Casa.it", id="c", url="c")])
        self.assertEqual(k["id"], "c")

    def test_dati_vecchi_senza_campo(self):
        imm = self.rec("Immobiliare.it", id="i", url="i")
        imm.pop("avviso_email", None)
        self.assertTrue(catalogatore.da_avviso_email(imm))
        (k,) = catalogatore.duplicati([imm, self.rec("Gabetti", id="g", url="g")])
        self.assertEqual(k["id"], "g")

    def test_immobili_diversi_restano(self):
        self.assertEqual(len(catalogatore.duplicati([self.rec("Subito.it", id="a", url="a"),
                                                     self.rec("Casa.it", id="b", url="b", mq=60.0)])), 2)

    def test_fonti_email_marcate(self):
        r = fonti.idealista_email_filtra(
            [dict(id="1", titolo="t", indirizzo="i", prezzo=1.0, prezzo_precedente=None, mq=1, locali=None,
                  bagni=None, piano=None, ascensore=False, box=False, asta=False, descrizione="", ricerca="")],
            {"prezzo_min": 0, "prezzo_max": 10, "locali_min": 1, "locali_max": 9})
        self.assertTrue(r[0]["avviso_email"])
        self.assertFalse(catalogatore.da_avviso_email(fonti.base_record(fonte="Subito.it")))


class Endpoint(unittest.TestCase):
    def setUp(self):
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def post(self, path, obj, origin=None):
        req = urllib.request.Request(self.base + path, data=json.dumps(obj).encode(), method="POST",
                                     headers={"Content-Type": "application/json", **({"Origin": origin} if origin else {})})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read())

    def test_importa_e_ricalcola(self):
        v = {"id": "casa-1", "camere": 3, "bagni": 2, "locali": 4, "testo": PAGINA}
        with mock.patch.object(server.verifiche, "importa", return_value=v) as imp, \
                mock.patch.object(server.famiglia, "run") as run, \
                mock.patch.dict(server.STATO, in_corso=False):
            code, r = self.post("/api/importa", {"u": "https://www.casa.it/immobili/1/", "x": PAGINA},
                                origin=self.base)
            for _ in range(50):
                if run.called:
                    break
                time.sleep(0.02)
        self.assertEqual(code, 200)
        self.assertEqual(r, {"ok": True, "id": "casa-1", "camere": 3, "bagni": 2, "locali": 4,
                             "caratteri": len(PAGINA), "ricalcolo": True})
        imp.assert_called_once()
        run.assert_called_once_with(solo_valuta=True)

    def test_ricerca_in_corso_niente_ricalcolo(self):
        v = {"id": "casa-1", "camere": None, "bagni": None, "locali": None, "testo": PAGINA}
        with mock.patch.object(server.verifiche, "importa", return_value=v), \
                mock.patch.object(server.famiglia, "run") as run, \
                mock.patch.dict(server.STATO, in_corso=True):
            code, r = self.post("/api/importa", {})
        self.assertEqual((code, r["ricalcolo"]), (200, False))
        run.assert_not_called()

    def test_pagina_non_valida_400(self):
        with mock.patch.object(server.verifiche, "importa", side_effect=ValueError("pagina non riconosciuta")):
            code, r = self.post("/api/importa", {})
        self.assertEqual((code, r), (400, {"errore": "pagina non riconosciuta"}))

    def test_altra_origine_rifiutata(self):
        with mock.patch.object(server.verifiche, "importa") as imp:
            code, _ = self.post("/api/importa", {}, origin="https://www.casa.it")
        self.assertEqual(code, 403)
        imp.assert_not_called()

    def test_pagine_servite(self):
        for p in ("/importa.html", "/famiglia.html"):
            with urllib.request.urlopen(self.base + p, timeout=5) as r:
                self.assertEqual(r.status, 200)


if __name__ == "__main__":
    unittest.main()
