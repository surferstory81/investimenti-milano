"""Preferiti e scartati (agents/preferiti.py): API, esclusione dalle classifiche,
aggiornamento a ogni valutazione e sezione nei report."""
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
from agents import famiglia, fonti, preferiti, report, valutatore


class Memoria:
    def __init__(self, dati=None):
        self.dati = dati or {}

    def load(self, nome, default=None):
        return json.loads(json.dumps(self.dati.get(nome, default)))

    def save(self, nome, obj):
        self.dati[nome] = json.loads(json.dumps(obj))


class ConMemoria(unittest.TestCase):
    def setUp(self):
        self.mem = Memoria()
        for nome, f in (("load_json", self.mem.load), ("save_json", self.mem.save)):
            p = mock.patch.object(preferiti, nome, f)
            p.start()
            self.addCleanup(p.stop)


T1, T2, T3 = datetime(2026, 11, 3, 11), datetime(2026, 11, 4, 9), datetime(2026, 11, 5, 9)
ANN = {"titolo": "Bilocale", "url": "u", "prezzo": 150000.0, "fonte": "Subito.it", "descrizione": "lunga"}


class Imposta(ConMemoria):
    def test_mi_piace_e_togli(self):
        p = preferiti.imposta("s-1", "studenti", "mi_piace", ANN, adesso=T1)
        self.assertEqual(p, {"s-1": {"profilo": "studenti", "stato": "mi_piace", "titolo": "Bilocale", "url": "u",
                                     "prezzo": 150000.0, "fonte": "Subito.it", "dal": "2026-11-03T11:00:00",
                                     "prezzo_iniziale": 150000.0}})
        p = preferiti.imposta("s-1", "studenti", "mi_piace", dict(ANN, prezzo=140000.0), adesso=T2)
        self.assertEqual((p["s-1"]["dal"], p["s-1"]["prezzo_iniziale"]), ("2026-11-03T11:00:00", 150000.0))
        self.assertEqual(preferiti.imposta("s-1", "studenti", None), {})
        self.assertEqual(preferiti.imposta("mai-visto", "famiglia", None), {})

    def test_compatibilita_booleani(self):
        self.assertEqual(preferiti.imposta("s-1", "studenti", True, ANN)["s-1"]["stato"], "mi_piace")
        self.assertEqual(preferiti.imposta("s-1", "studenti", False), {})

    def test_scarta_dopo_mi_piace(self):
        preferiti.imposta("s-1", "studenti", "mi_piace", ANN, adesso=T1)
        p = preferiti.imposta("s-1", "studenti", "scartato", ANN, adesso=T2)
        self.assertEqual((p["s-1"]["stato"], p["s-1"]["dal"]), ("scartato", "2026-11-04T09:00:00"))
        self.assertEqual(preferiti.ids("studenti", "scartato"), {"s-1"})
        self.assertEqual(preferiti.ids("studenti", "mi_piace"), set())
        self.assertEqual(preferiti.ids("famiglia", "scartato"), set())

    def test_voci_vecchie_senza_stato(self):
        self.mem.dati[preferiti.FILE] = {"x": {"profilo": "famiglia", "titolo": "t"}}
        self.assertEqual(preferiti.ids("famiglia", "mi_piace"), {"x"})

    def test_valori_non_validi(self):
        for args in (("", "studenti", "mi_piace"), ("x", "altro", "mi_piace"), (None, "famiglia", None),
                     ("x", "studenti", "boh")):
            with self.assertRaises(ValueError):
                preferiti.imposta(*args)
        self.assertEqual(preferiti.tutti(), {})


class AggiornaERiepilogo(ConMemoria):
    def setUp(self):
        super().setUp()
        preferiti.imposta("s-1", "studenti", "mi_piace", ANN, adesso=T1)
        preferiti.imposta("s-2", "studenti", "mi_piace", dict(ANN, titolo="Monolocale", url="u2"), adesso=T1)
        preferiti.imposta("s-3", "studenti", "scartato", ANN, adesso=T1)
        preferiti.imposta("f-1", "famiglia", "mi_piace", ANN, adesso=T1)

    def test_aggiorna_prezzo_posizione_vista(self):
        preferiti.aggiorna("studenti", [{"id": "s-9"}, dict(ANN, id="s-1", prezzo=150000.0)], adesso=T2)
        preferiti.aggiorna("studenti", [dict(ANN, id="s-1", prezzo=140000.0)], adesso=T3)
        v = preferiti.tutti()["s-1"]
        self.assertEqual((v["prezzo"], v["prezzo_precedente"], v["variato_il"]),
                         (140000.0, 150000.0, "2026-11-05T09:00:00"))
        self.assertEqual((v["posizione"], v["ultima_vista"]), (1, "2026-11-05T09:00:00"))
        self.assertNotIn("ultima_vista", preferiti.tutti()["f-1"])  # altro profilo
        self.assertNotIn("ultima_vista", preferiti.tutti()["s-3"])  # scartato

    def test_riepilogo(self):
        preferiti.aggiorna("studenti", [dict(ANN, id="s-1"), dict(ANN, id="s-2")], adesso=T2)
        preferiti.aggiorna("studenti", [dict(ANN, id="s-1", prezzo=140000.0)], adesso=T3)  # s-2 sparito
        r = {x["id"]: x for x in preferiti.riepilogo("studenti", "2026-11-05")}
        self.assertEqual(set(r), {"s-1", "s-2"})
        self.assertEqual(r["s-1"]["note"], ["prezzo sceso oggi di 10.000 €", "−10.000 € da quando l'hai segnato"])
        self.assertTrue(r["s-1"]["novita"])
        self.assertEqual(r["s-1"]["posizione"], 1)
        self.assertEqual(r["s-2"]["note"], ["non più trovato dal 04/11"])
        self.assertTrue(r["s-2"]["novita"])  # sparito da oggi
        self.assertIsNone(r["s-2"]["posizione"])
        # il giorno dopo: s-2 sparito da prima di ieri non è più una novità
        r = {x["id"]: x for x in preferiti.riepilogo("studenti", "2026-11-07")}
        self.assertFalse(r["s-2"]["novita"])

    def test_mai_visto(self):
        (r,) = [x for x in preferiti.riepilogo("famiglia", "2026-11-03")]
        self.assertEqual(r["note"], ["non trovato tra gli annunci di oggi"])
        self.assertFalse(r["novita"])

    def test_ordine_novita_prima(self):
        preferiti.aggiorna("studenti", [dict(ANN, id="s-2"), dict(ANN, id="s-1")], adesso=T2)
        preferiti.aggiorna("studenti", [dict(ANN, id="s-2"), dict(ANN, id="s-1", prezzo=1.0)], adesso=T3)
        self.assertEqual([x["id"] for x in preferiti.riepilogo("studenti", "2026-11-05")], ["s-1", "s-2"])

    def test_sezione_report(self):
        preferiti.aggiorna("studenti", [dict(ANN, id="s-1", prezzo=140000.0)], adesso=T3)
        testo, html, n = preferiti.sezione_report(preferiti.riepilogo("studenti", "2026-11-05"))
        self.assertEqual(n, 1)
        self.assertIn("I TUOI PREFERITI", testo)
        self.assertIn("* Bilocale", testo)
        self.assertIn("#1 in classifica", testo)
        self.assertIn("I tuoi preferiti", html)
        self.assertIn('href="u"', html)
        self.assertEqual(preferiti.sezione_report([]), ("", "", 0))

    def test_html_escape(self):
        preferiti.imposta("s-1", "studenti", "mi_piace", dict(ANN, titolo="<b>x</b>"), adesso=T1)
        _, html, _ = preferiti.sezione_report(preferiti.riepilogo("studenti", "2026-11-03"))
        self.assertNotIn("<b>x</b>", html)


class Classifiche(ConMemoria):
    def test_valutatore_esclude_scartati_e_aggiorna(self):
        preferiti.imposta("a", "studenti", "scartato", ANN)
        preferiti.imposta("b", "studenti", "mi_piace", ANN)
        cat = {"aggiornato": "x", "annunci": [{"id": i, "titolo": i, "prezzo_mq": 3000, "zona_universitaria": "Poli"} for i in "abc"],
               "canoni_eur_mq": {}, "scartati": []}
        mem = Memoria({"catalogo.json": cat})
        punti = {"a": 90, "b": 80, "c": 70}
        with mock.patch.object(valutatore, "load_config", return_value={}), \
                mock.patch.object(valutatore, "valuta", side_effect=lambda a, ctx, cfg: dict(a, valutazione={"punteggio": punti[a["id"]]})), \
                mock.patch.object(valutatore, "load_json", mem.load), \
                mock.patch.object(valutatore, "save_json", mem.save), \
                mock.patch.object(valutatore, "log"):
            valutatore.run()
        c = mem.dati["classifica.json"]
        self.assertEqual([(a["id"], a["posizione_classifica"]) for a in c["top"]], [("b", 1), ("c", 2)])
        self.assertEqual(preferiti.tutti()["b"]["posizione"], 1)

    def test_famiglia_esclude_scartati(self):
        preferiti.imposta("w", "famiglia", "scartato", ANN)
        preferiti.imposta("z", "famiglia", "mi_piace", ANN)
        f = {"prezzo_min": 0, "prezzo_max": 2e6, "mq_min": 50, "mq_ideale": 100, "raggio_km": 12,
             "camere_min": 3, "bagni_min": 2, "top": 10,
             "pesi": {k: 1 for k in ("posizione", "camere", "bagni", "salone", "cucina_abitabile", "prezzo",
                                     "metratura", *[k for k, _, _ in famiglia.PLUS + famiglia.BIMBI])}}
        annunci = [fonti.base_record(id=i, fonte="Subito.it", titolo="Quadrilocale", prezzo=900000.0, mq=120.0 + n,
                                     lat=45.46 + n / 100, lon=9.19, locali="4", bagni="2") for n, i in enumerate("wz")]
        mem = Memoria({"famiglia_grezzi.json": {"annunci": annunci, "per_fonte": {}}})
        with mock.patch.object(famiglia, "load_config", return_value={"famiglia": f}), \
                mock.patch.object(famiglia, "load_json", mem.load), \
                mock.patch.object(famiglia, "save_json", mem.save), \
                mock.patch.object(famiglia, "log"):
            famiglia.run(solo_valuta=True)
        self.assertEqual([a["id"] for a in mem.dati["famiglia.json"]["top"]], ["z"])
        self.assertEqual(preferiti.tutti()["z"]["posizione"], 1)


class Report(ConMemoria):
    def classifica(self):
        a = {"id": "s-1", "titolo": "Bilocale", "prezzo": 140000.0, "mq": 40.0, "prezzo_mq": 3500, "url": "u",
             "fonte": "Subito.it", "distanza_uni_km": 0.5, "zona_universitaria": "Poli", "posizione_classifica": 1,
             "valutazione": {"canone_stimato": 900, "rendimento_netto": 4.2, "punteggio": 70, "giudizio": "Interessante",
                             "pro": [], "contro": []}}
        return {"aggiornato": "2026-11-05T09:00:00", "top": [a], "totale_valutati": 1, "per_fonte": {}}

    def test_studenti_con_preferiti(self):
        preferiti.imposta("s-1", "studenti", "mi_piace", ANN, adesso=T1)
        preferiti.aggiorna("studenti", [dict(ANN, id="s-1")], adesso=T2)
        preferiti.aggiorna("studenti", [dict(ANN, id="s-1", prezzo=140000.0)], adesso=T3)
        oggetto, testo, html = report.componi(self.classifica(), {"server": {"porta": 8765}})
        self.assertTrue(oggetto.endswith("· 1 novità sui preferiti"), oggetto)
        self.assertLess(testo.index("I TUOI PREFERITI"), testo.index(" 1. Bilocale"))
        self.assertIn("prezzo sceso oggi di 10.000 €", html)

    def test_studenti_senza_preferiti(self):
        oggetto, testo, html = report.componi(self.classifica(), {"server": {"porta": 8765}})
        self.assertNotIn("preferiti", oggetto)
        self.assertNotIn("PREFERITI", testo)

    def test_famiglia_con_preferiti(self):
        preferiti.imposta("f-1", "famiglia", "mi_piace", dict(ANN, titolo="Quadrilocale Brera"), adesso=T1)
        a = {"id": "f-2", "titolo": "Trilocale", "prezzo": 900000.0, "mq": 120.0, "url": "u2", "fonte": "Subito.it",
             "comune": "Milano", "punteggio": 70, "plus": [], "mancano": [], "prima_vista": "2026-11-01",
             "caratteristiche": {"camere": 3, "camere_stimate": False, "bagni": 2}}
        mem = Memoria({"famiglia.json": {"aggiornato": "2026-11-03T09:00:00", "top": [a], "per_fonte": {},
                                         "totale_valutati": 1}})
        smtp = mock.MagicMock()
        cfg = {"email": {"mittente_nome": "x", "utente": "x@example.com"}, "report": {"destinatari": ["y@example.com"]},
               "server": {"porta": 8765}, "famiglia": {}}
        with mock.patch.object(famiglia, "load_json", mem.load), \
                mock.patch.object(famiglia, "smtp_connessione", return_value=smtp), \
                mock.patch.object(famiglia, "log"):
            self.assertTrue(famiglia.invia_report(cfg))
        msg = smtp.send_message.call_args[0][0]
        corpo = msg.get_body(("plain",)).get_content()
        self.assertIn("I TUOI PREFERITI", corpo)
        self.assertIn("Quadrilocale Brera", corpo)
        self.assertNotIn("novità", msg["Subject"])  # "non trovato tra gli annunci di oggi" non è una novità


class Endpoint(ConMemoria):
    def setUp(self):
        super().setUp()
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    def chiama(self, metodo, corpo=None):
        req = urllib.request.Request(self.base + "/api/preferiti", method=metodo,
                                     data=json.dumps(corpo).encode() if corpo is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read())

    def aspetta(self, m):
        for _ in range(50):
            if m.called:
                return
            time.sleep(0.02)

    def test_mi_piace_senza_ricalcolo(self):
        self.assertEqual(self.chiama("GET"), (200, {}))
        with mock.patch.object(server, "pipeline") as pip, mock.patch.dict(server.STATO, in_corso=False):
            code, r = self.chiama("POST", {"id": "casa-1", "profilo": "famiglia", "stato": "mi_piace",
                                           "annuncio": {"titolo": "Quadrilocale", "url": "u"}})
        self.assertEqual((code, r["ricalcolo"], r["preferiti"]["casa-1"]["titolo"]), (200, False, "Quadrilocale"))
        pip.assert_not_called()
        self.assertEqual(self.chiama("GET")[1], r["preferiti"])

    def test_vecchio_formato(self):
        code, r = self.chiama("POST", {"id": "s-1", "profilo": "studenti", "mi_piace": True})
        self.assertEqual((code, r["preferiti"]["s-1"]["stato"]), (200, "mi_piace"))

    def test_scarta_e_ripristina_ricalcolano(self):
        with mock.patch.object(server, "pipeline") as pip, mock.patch.object(server.famiglia, "run") as fam, \
                mock.patch.dict(server.STATO, in_corso=False):
            _, r = self.chiama("POST", {"id": "s-1", "profilo": "studenti", "stato": "scartato"})
            self.assertTrue(r["ricalcolo"])
            self.aspetta(pip)
            pip.assert_called_once_with(True)
            _, r = self.chiama("POST", {"id": "f-1", "profilo": "famiglia", "stato": "scartato"})
            self.aspetta(fam)
            fam.assert_called_once_with(solo_valuta=True)
            server.STATO["in_corso"] = False
            _, r = self.chiama("POST", {"id": "s-1", "profilo": "studenti", "stato": None})
            self.assertTrue(r["ricalcolo"])
            self.assertNotIn("s-1", r["preferiti"])

    def test_ricerca_in_corso_niente_ricalcolo(self):
        with mock.patch.object(server, "pipeline") as pip, mock.patch.dict(server.STATO, in_corso=True):
            _, r = self.chiama("POST", {"id": "s-1", "profilo": "studenti", "stato": "scartato"})
        self.assertFalse(r["ricalcolo"])
        pip.assert_not_called()

    def test_non_valido(self):
        self.assertEqual(self.chiama("POST", {"id": "x", "profilo": "boh", "stato": "mi_piace"})[0], 400)


if __name__ == "__main__":
    unittest.main()
