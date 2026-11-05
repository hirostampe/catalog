#!/usr/bin/env python3
"""
Reel Replica — app locale.

Avvio:  python app.py   (oppure doppio clic su "Avvia Mac.command" / "Avvia Windows.bat")
Si apre il browser su http://localhost:8765 con l'interfaccia.
"""
import json
import mimetypes
import platform
import subprocess
import sys
import threading
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import scarica_reel as motore

PORTA = 8765
QUI = Path(__file__).resolve().parent
PAGINA = QUI / "interfaccia.html"

lavori = {}          # id -> stato del lavoro
lucchetto = threading.Lock()
coda = threading.Semaphore(2)  # massimo 2 download insieme


def aggiorna(id_, **campi):
    with lucchetto:
        lavori[id_].update(campi)


def esegui(id_, url, opzioni):
    with coda:
        aggiorna(id_, stato="in_corso", messaggio="Avvio…")
        try:
            cartella = motore.elabora(
                url,
                cookies_browser=opzioni.get("cookies_browser") or None,
                con_video=bool(opzioni.get("con_video")),
                avanzamento=lambda m: aggiorna(id_, messaggio=m),
            )
            aggiorna(id_, stato="fatto", messaggio="Pronto", cartella=cartella.name)
        except Exception as e:
            aggiorna(id_, stato="errore", messaggio=motore.suggerimento_errore(url, str(e)),
                     dettaglio=str(e)[:400])


def libreria():
    elementi = []
    if not motore.CARTELLA_BASE.exists():
        return elementi
    for c in motore.CARTELLA_BASE.iterdir():
        f = c / "analisi.json"
        if not f.exists():
            continue
        try:
            dati = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        dati["cartella"] = c.name
        dati["frames"] = sorted(p.name for p in c.glob("frame_*.jpg"))
        dati["data"] = f.stat().st_mtime
        brief = c / "brief.md"
        testo = brief.read_text(encoding="utf-8") if brief.exists() else ""
        dati["prompt"] = testo.split("## Prompt da incollare su Claude", 1)[-1].strip() if testo else ""
        elementi.append(dati)
    return sorted(elementi, key=lambda d: d["data"], reverse=True)


def apri_cartella(percorso):
    sistema = platform.system()
    if sistema == "Darwin":
        subprocess.Popen(["open", str(percorso)])
    elif sistema == "Windows":
        subprocess.Popen(["explorer", str(percorso)])
    else:
        subprocess.Popen(["xdg-open", str(percorso)])


def cartella_sicura(nome):
    """Evita che la richiesta esca dalla cartella riferimenti/."""
    base = motore.CARTELLA_BASE.resolve()
    p = (base / nome).resolve()
    if base not in p.parents:
        raise ValueError("percorso non valido")
    return p


class Gestore(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def rispondi(self, codice, corpo, tipo="application/json; charset=utf-8", extra=None):
        if isinstance(corpo, (dict, list)):
            corpo = json.dumps(corpo, ensure_ascii=False).encode()
        elif isinstance(corpo, str):
            corpo = corpo.encode()
        self.send_response(codice)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(corpo)

    def leggi_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        percorso = unquote(urlparse(self.path).path)
        if percorso == "/":
            return self.rispondi(200, PAGINA.read_bytes(), "text/html; charset=utf-8")
        if percorso == "/api/stato":
            with lucchetto:
                return self.rispondi(200, list(lavori.values()))
        if percorso == "/api/libreria":
            return self.rispondi(200, libreria())
        if percorso.startswith("/file/"):
            try:
                file = cartella_sicura(percorso[len("/file/"):])
            except ValueError:
                return self.rispondi(403, {"errore": "vietato"})
            if not file.is_file():
                return self.rispondi(404, {"errore": "non trovato"})
            tipo = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            extra = {}
            if file.suffix == ".zip":
                extra["Content-Disposition"] = f'attachment; filename="{file.parent.name}.zip"'
            return self.rispondi(200, file.read_bytes(), tipo, extra)
        self.rispondi(404, {"errore": "non trovato"})

    def do_POST(self):
        percorso = urlparse(self.path).path
        try:
            dati = self.leggi_json()
        except ValueError:
            return self.rispondi(400, {"errore": "json non valido"})

        if percorso == "/api/scarica":
            urls = [u.strip() for u in dati.get("urls", []) if u.strip().startswith("http")]
            if not urls:
                return self.rispondi(400, {"errore": "Nessun link valido"})
            for url in urls:
                id_ = uuid.uuid4().hex[:8]
                with lucchetto:
                    lavori[id_] = {"id": id_, "url": url, "stato": "in_coda",
                                   "messaggio": "In coda…"}
                threading.Thread(target=esegui, args=(id_, url, dati), daemon=True).start()
            return self.rispondi(200, {"ok": True, "n": len(urls)})

        if percorso == "/api/apri":
            try:
                apri_cartella(cartella_sicura(dati.get("cartella", "")))
            except Exception as e:
                return self.rispondi(400, {"errore": str(e)})
            return self.rispondi(200, {"ok": True})

        if percorso == "/api/pulisci":
            with lucchetto:
                for k in [k for k, v in lavori.items() if v["stato"] in ("fatto", "errore")]:
                    del lavori[k]
            return self.rispondi(200, {"ok": True})

        self.rispondi(404, {"errore": "non trovato"})


def main():
    motore.controlla_ffmpeg()
    motore.CARTELLA_BASE.mkdir(exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", PORTA), Gestore)
    indirizzo = f"http://localhost:{PORTA}"
    print(f"Reel Replica è aperta su {indirizzo}  (chiudi questa finestra per uscire)")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(indirizzo)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
