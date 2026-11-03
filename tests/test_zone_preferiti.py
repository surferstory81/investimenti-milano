"""Zone (NIL di Milano), area di ricerca studenti, zone famiglia, canoni e
mediane per quartiere, preferiti."""
import json
import threading
import unittest
import urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import server
from agents import famiglia, fonti, preferiti, ricerca, valutatore, zone

ESEMPIO = json.loads((Path(__file__).parent.parent / "config.example.json").read_text(encoding="utf-8"))
ZONE = ESEMPIO["famiglia"]["zone"]

DUOMO = (45.4641, 9.1919)
CITTA_STUDI = (45.4781, 9.2272)
WASHINGTON = (45.4625, 9.1597)
QUARTO_OGGIARO = (45.5150, 9.1370)
SESTO = (45.5350, 9.2330)


class Memoria:
    def __init__(self, dati=None):
        self.dati = dati or {}

    def load(self, nome, default=None):
        return json.loads(json.dumps(self.dati.get(nome, default)))

    def save(self, nome, obj):
        self.dati[nome] = obj


class Nil(unittest.TestCase):
    def test_punti_noti(self):
        self.assertEqual(zone.nil_di(*DUOMO), "DUOMO")
        self.assertEqual(zone.nil_di(*CITTA_STUDI), "CITTA' STUDI")
        self.assertEqual(zone.nil_di(*QUARTO_OGGIARO), "QUARTO OGGIARO - VIALBA - MUSOCCO")

    def test_fuori_milano_o_senza_coordinate(self):
        self.assertIsNone(zone.nil_di(*SESTO))
        self.assertIsNone(zone.nil_di(None, None))
        self.assertIsNone(zone.nil_di(41.9, 12.5))  # Roma

    def test_88_quartieri(self):
        self.assertEqual(len(zone.nomi()), 88)

    def test_zona_scelta(self):
        self.assertEqual(zone.zona_scelta(*WASHINGTON, ZONE), "Solari, Washington")
        self.assertEqual(zone.zona_scelta(*DUOMO, ZONE), "Centro storico")
        self.assertIsNone(zone.zona_scelta(*QUARTO_OGGIARO, ZONE))
        self.assertIsNone(zone.zona_scelta(*SESTO, ZONE))
        self.assertIsNone(zone.zona_scelta(*DUOMO, {}))

    def test_config_di_esempio_valido(self):
        self.assertEqual(zone.verifica_config(ZONE), [])
        tutti = [n for v in ZONE.values() if isinstance(v, list) for n in v]
        self.assertEqual(len(tutti), len(set(tutti)), "un NIL in due zone")
        self.assertEqual(len(ZONE), 15)

    def test_san_felice_cerchio(self):
        self.assertEqual(zone.zona_scelta(45.4740, 9.3080, ZONE), "San Felice (Segrate)")   # dentro San Felice
        self.assertIsNone(zone.zona_scelta(45.4900, 9.2950, ZONE))                          # Segrate centro
        self.assertIsNone(zone.zona_scelta(None, 9.3, ZONE))
        self.assertEqual(ZONE["San Felice (Segrate)"], {"centro": [45.4732, 9.3075], "raggio_km": 0.9})

    def test_cerchi_malformati(self):
        self.assertEqual(zone.verifica_config({"a": {"centro": [45.4]}, "b": {"centro": [45.4, 9.3], "raggio_km": 0},
                                               "c": {"centro": [45.4, 9.3]}}),
                         ["a: cerchio non valido", "b: cerchio non valido"])

    def test_errori_di_battitura(self):
        self.assertEqual(zone.verifica_config({"x": ["DUOMO", "BRERRA"]}), ["BRERRA"])


class AreaStudenti(unittest.TestCase):
    def esegui(self, area):
        cfg = {"universita": [{"nome": "Poli", "zona": "Città Studi", "lat": CITTA_STUDI[0], "lon": CITTA_STUDI[1]}],
               "ricerca": {"raggio_universita_km": 1.6, "fonti": ["subito"], **({"area": area} if area else {})}}
        vendita = [fonti.base_record(id="vicino", fonte="Subito.it", lat=CITTA_STUDI[0], lon=CITTA_STUDI[1]),
                   fonti.base_record(id="lontano", fonte="Subito.it", lat=QUARTO_OGGIARO[0], lon=QUARTO_OGGIARO[1]),
                   fonti.base_record(id="sesto", fonte="Subito.it", lat=SESTO[0], lon=SESTO[1]),
                   fonti.base_record(id="senza_coordinate", fonte="Subito.it")]
        affitto = [fonti.base_record(id="aff", fonte="Subito.it", lat=DUOMO[0], lon=DUOMO[1])]
        mem = Memoria()
        with mock.patch.object(ricerca, "load_config", return_value=cfg), \
                mock.patch.object(ricerca.fonti, "subito", side_effect=lambda tipo, c: vendita if tipo == "vendita" else affitto), \
                mock.patch.object(ricerca, "load_json", mem.load), \
                mock.patch.object(ricerca, "save_json", mem.save), \
                mock.patch.object(ricerca, "log") as log:
            ricerca.run()
        return mem.dati["grezzi.json"], log

    def test_tutta_milano(self):
        g, log = self.esegui("milano")
        self.assertEqual([a["id"] for a in g["vendita"]], ["vicino", "lontano"])
        self.assertEqual(g["vendita"][1]["nil"], "QUARTO OGGIARO - VIALBA - MUSOCCO")
        self.assertEqual(g["affitto"][0]["nil"], "DUOMO")
        self.assertIn("2 nel Comune di Milano", log.call_args[0][1])

    def test_raggio_universita_se_non_configurato(self):
        g, log = self.esegui(None)
        self.assertEqual([a["id"] for a in g["vendita"]], ["vicino"])
        self.assertIn("entro 1.6 km", log.call_args[0][1])


class CanoniEMediane(unittest.TestCase):
    C = {"affitto_eur_mq_default": 20}

    def a(self, **kw):
        return {"mq": 30, "nil": "DUOMO", "zona_universitaria": "Poli", "distanza_uni_km": 0.5, **kw}

    def test_canone_dal_quartiere(self):
        nil = {"DUOMO": [[900, 30]] * 6}
        canone, _, metodo = valutatore.canone_stimato(self.a(), {"Poli": [[600, 30]] * 6}, self.C, nil)
        self.assertEqual(canone, round(900 * valutatore.PRUDENZA / 10) * 10)
        self.assertIn("nel quartiere", metodo)

    def test_quartiere_scarso_poi_zona_universitaria(self):
        canone, _, metodo = valutatore.canone_stimato(self.a(), {"Poli": [[600, 30]] * 6}, self.C, {"DUOMO": [[900, 30]]})
        self.assertEqual(canone, round(600 * valutatore.PRUDENZA / 10) * 10)
        self.assertIn("in zona universitaria", metodo)

    def test_lontano_dall_ateneo_niente_canoni_universitari(self):
        canone, _, metodo = valutatore.canone_stimato(self.a(distanza_uni_km=4.0), {"Poli": [[600, 30]] * 6},
                                                      self.C, {})
        self.assertEqual(canone, round(20 * 30 * valutatore.PRUDENZA / 10) * 10)
        self.assertIn("default", metodo)

    def test_eur_mq_di_quartiere(self):
        serie = [[1000, 50]] * 8  # taglio diverso: €/mq
        canone, eur_mq, metodo = valutatore.canone_stimato(self.a(), {}, self.C, {"DUOMO": serie})
        self.assertEqual(canone, round(20 * 30 * valutatore.PRUDENZA / 10) * 10)
        self.assertIn("€/mq mediano di 8 affitti nel quartiere", metodo)

    def test_compatibile_senza_canoni_nil(self):
        canone, _, _ = valutatore.canone_stimato(self.a(), {"Poli": [[600, 30]] * 6}, self.C)
        self.assertEqual(canone, round(600 * valutatore.PRUDENZA / 10) * 10)

    def test_mediana_zona(self):
        ctx = {"mediana_nil": {"DUOMO": 9000}, "mediana_eur_mq": {"Poli": 5000}, "mediana_globale": 4000}
        self.assertEqual(valutatore.mediana_zona(self.a(), ctx), 9000)
        self.assertEqual(valutatore.mediana_zona(self.a(nil="BRERA"), ctx), 5000)
        self.assertEqual(valutatore.mediana_zona(self.a(nil=None, distanza_uni_km=3), ctx), 4000)
        self.assertEqual(valutatore.mediana_zona(self.a(nil=None), {"mediana_eur_mq": {}, "mediana_globale": 4000}), 4000)


class ZoneFamiglia(unittest.TestCase):
    F = {"prezzo_min": 0, "prezzo_max": 2e6, "mq_min": 50, "mq_ideale": 100, "raggio_km": 12,
         "camere_min": 3, "bagni_min": 2, "top": 10,
         "pesi": {k: 1 for k in ("posizione", "camere", "bagni", "salone", "cucina_abitabile", "prezzo",
                                 "metratura", *[k for k, _, _ in famiglia.PLUS + famiglia.BIMBI])}}

    def esegui(self, f):
        annunci = [fonti.base_record(id=i, fonte="Subito.it", titolo="Quadrilocale", prezzo=900000.0, mq=120.0,
                                     lat=lat, lon=lon, locali="4", bagni="2")
                   for i, (lat, lon) in (("washington", WASHINGTON), ("quarto", QUARTO_OGGIARO), ("sesto", SESTO))]
        mem = Memoria({"famiglia_grezzi.json": {"annunci": annunci, "per_fonte": {}}})
        with mock.patch.object(famiglia, "load_config", return_value={"famiglia": f}), \
                mock.patch.object(famiglia, "load_json", mem.load), \
                mock.patch.object(famiglia, "save_json", mem.save), \
                mock.patch.object(famiglia, "log") as log:
            famiglia.run(solo_valuta=True)
        return mem.dati["famiglia.json"], log

    def test_solo_le_zone_scelte(self):
        d, _ = self.esegui(dict(self.F, zone=ZONE))
        self.assertEqual([(a["id"], a["zona_scelta"]) for a in d["top"]], [("washington", "Solari, Washington")])

    def test_senza_zone_vale_il_raggio(self):
        d, _ = self.esegui(self.F)
        self.assertEqual({a["id"] for a in d["top"]}, {"washington", "quarto", "sesto"})
        self.assertNotIn("zona_scelta", d["top"][0])

    def test_nil_sbagliato_segnalato(self):
        _, log = self.esegui(dict(self.F, zone={"Brera": ["BRERRA"]}))
        self.assertTrue(any("BRERRA" in c[0][1] for c in log.call_args_list))


if __name__ == "__main__":
    unittest.main()
