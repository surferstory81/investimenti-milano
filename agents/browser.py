"""Firefox headless pilotato via Marionette (protocollo integrato in Firefox,
nessuna dipendenza esterna). Usato per i portali che bloccano le richieste HTTP
semplici (Immobiliare.it, Idealista, Casa.it)."""
import json
import random
import shutil
import socket
import subprocess
import tempfile
import time


class Firefox:
    def __init__(self, port=None, headless=True):
        self.port = port or random.randint(28000, 28999)
        self.profile = tempfile.mkdtemp(prefix="ff-agent-")
        with open(f"{self.profile}/user.js", "w") as f:
            f.write(f'user_pref("marionette.port", {self.port});\n'
                    'user_pref("intl.accept_languages", "it-IT, it");\n'
                    'user_pref("browser.shell.checkDefaultBrowser", false);\n'
                    'user_pref("datareporting.policy.dataSubmissionEnabled", false);\n')
        args = ["firefox", "--marionette", "--no-remote", "--profile", self.profile]
        if headless:
            args.insert(1, "--headless")
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        self.msg_id = 0
        self._connect()
        self._cmd("WebDriver:NewSession", {"capabilities": {}})

    def _connect(self):
        for _ in range(60):
            try:
                self.sock = socket.create_connection(("127.0.0.1", self.port), 2)
                self._read()  # handshake
                return
            except OSError:
                time.sleep(0.5)
        raise RuntimeError("impossibile connettersi a Firefox/Marionette")

    def _read(self):
        buf = b""
        while b":" not in buf:
            buf += self.sock.recv(1)
        n, rest = buf.split(b":", 1)
        n = int(n)
        while len(rest) < n:
            rest += self.sock.recv(n - len(rest))
        return json.loads(rest)

    def _cmd(self, name, params=None):
        self.msg_id += 1
        data = json.dumps([0, self.msg_id, name, params or {}]).encode()
        self.sock.sendall(str(len(data)).encode() + b":" + data)
        self.sock.settimeout(90)
        while True:
            resp = self._read()
            if resp[0] == 1 and resp[1] == self.msg_id:
                if resp[2]:
                    raise RuntimeError(f"{name}: {resp[2]}")
                return resp[3]

    def get(self, url, wait=3.0):
        self._cmd("WebDriver:Navigate", {"url": url})
        time.sleep(wait)
        return self.source()

    def source(self):
        return self._cmd("WebDriver:GetPageSource")["value"]

    def js(self, script):
        return self._cmd("WebDriver:ExecuteScript",
                         {"script": script, "args": []}).get("value")

    def close(self):
        try:
            self._cmd("WebDriver:DeleteSession")
        except Exception:
            pass
        self.proc.terminate()
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
