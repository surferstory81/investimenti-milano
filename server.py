"""Server locale della dashboard: http://localhost:8765
Avvio: python3 server.py"""
import json
import threading
import traceback
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from agents import famiglia, mailer
from agents.common import DATA, ROOT, load_config, load_json, log, save_json
from run import pipeline

STATO = {"in_corso": False, "errore": None}


def _pipeline_bg(solo_valuta, fn=None):
    STATO.update(in_corso=True, errore=None)
    try:
        fn() if fn else pipeline(solo_valuta)
    except Exception as e:
        STATO["errore"] = str(e)
        log("Orchestratore", "ERRORE: " + traceback.format_exc())
    finally:
        STATO["in_corso"] = False


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT / "web"), **kw)

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        if self.path == "/api/dati":
            cfg = load_config()
            return self._json({
                "classifica": load_json("classifica.json"),
                "selezione": load_json("selezione.json", []),
                "email": load_json("email_inviate.json", {}),
                "smtp_attivo": bool(cfg["email"].get("abilitato") and cfg["email"].get("password_app")),
            })
        if self.path == "/api/famiglia":
            return self._json(load_json("famiglia.json"))
        if self.path == "/api/stato":
            log_path = DATA / "agenti.log"
            righe = log_path.read_text().splitlines()[-14:] if log_path.exists() else []
            return self._json({**STATO, "log": righe})
        return super().do_GET()

    def do_POST(self):
        # accetta solo richieste dalla pagina servita da questo stesso server
        origin = self.headers.get("Origin", "")
        if origin and origin != f"http://{self.headers.get('Host', '')}":
            return self._json({"errore": "origine non consentita"}, 403)
        try:
            b = self._body()
            if self.path == "/api/ricerca":
                if STATO["in_corso"]:
                    return self._json({"ok": False, "messaggio": "ricerca già in corso"})
                threading.Thread(target=_pipeline_bg, args=(bool(b.get("solo_valuta")),),
                                 daemon=True).start()
                return self._json({"ok": True})
            if self.path == "/api/famiglia/ricerca":
                if STATO["in_corso"]:
                    return self._json({"ok": False, "messaggio": "ricerca già in corso"})
                solo = bool(b.get("solo_valuta"))
                threading.Thread(target=_pipeline_bg, daemon=True,
                                 args=(False, lambda: famiglia.run(solo_valuta=solo))).start()
                return self._json({"ok": True})
            if self.path == "/api/selezione":
                save_json("selezione.json", list(dict.fromkeys(b.get("ids", []))))
                return self._json({"ok": True})
            if self.path == "/api/anteprima-email":
                return self._json({"bozze": mailer.anteprima(b.get("ids", []))})
            if self.path == "/api/invia-email":
                if b.get("conferma") is not True:
                    return self._json({"errore": "conferma mancante"}, 400)
                return self._json(mailer.invia(b.get("bozze", [])))
        except Exception as e:
            return self._json({"errore": str(e)}, 500)
        return self._json({"errore": "endpoint sconosciuto"}, 404)


if __name__ == "__main__":
    srv = load_config()["server"]
    porta, host = srv["porta"], srv.get("host", "127.0.0.1")
    print(f"Dashboard: http://{host}:{porta}")
    ThreadingHTTPServer((host, porta), Handler).serve_forever()
