#!/usr/bin/env python3
"""Bot James Ross (jamesross.it) per Hirostampe.

Entra nel sito col tuo account, cerca articoli e legge varianti, prezzi e giacenze.

Uso:
  python3 jrc.py cerca "felpa navy"          # cerca e mostra i primi 5 articoli
  python3 jrc.py cerca "polo" --max 10 --json
  python3 jrc.py articolo 987690             # un codice preciso
  python3 jrc.py serve                       # mini API per Claude (porta 8765)

Credenziali nel file .env accanto a questo script (vedi .env.example).
"""
import argparse
import json
import os
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

BASE = "https://www.jamesross.it"
HERE = Path(__file__).resolve().parent
COOKIE_FILE = HERE / ".sessione.json"
DEBUG_DIR = HERE / "debug"
PAUSA = 2.5  # secondi tra una richiesta e l'altra: il sito non ama la fretta
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


def carica_env():
    env = HERE / ".env"
    if env.exists():
        for riga in env.read_text().splitlines():
            riga = riga.strip()
            if riga and not riga.startswith("#") and "=" in riga:
                k, v = riga.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def numero(testo):
    """'24,60 €' -> 24.6 ; '1.234' -> 1234"""
    t = re.sub(r"[^\d,.\-]", "", testo or "")
    if not t:
        return None
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    try:
        return float(t) if "." in t else int(t)
    except ValueError:
        return None


class JRC:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9"})
        self._ultima = 0.0
        if COOKIE_FILE.exists():
            try:
                self.s.cookies.update(json.loads(COOKIE_FILE.read_text()))
            except Exception:
                pass

    # ---- rete ----
    def _get(self, path, **kw):
        return self._req("GET", path, **kw)

    def _req(self, metodo, path, **kw):
        url = path if path.startswith("http") else BASE + path
        for tentativo in range(4):
            attesa = PAUSA - (time.time() - self._ultima)
            if attesa > 0:
                time.sleep(attesa)
            try:
                r = self.s.request(metodo, url, timeout=30, **kw)
                self._ultima = time.time()
                r.raise_for_status()
                r.encoding = r.encoding or "utf-8"
                return r
            except (requests.ConnectionError, requests.Timeout):
                self._ultima = time.time()
                time.sleep(5 * (tentativo + 1))
        raise RuntimeError(f"Il sito non risponde: {url}")

    def _salva_sessione(self):
        COOKIE_FILE.write_text(json.dumps(self.s.cookies.get_dict()))
        os.chmod(COOKIE_FILE, 0o600)

    # ---- login ----
    def login(self):
        user, pwd = os.environ.get("JRC_USER"), os.environ.get("JRC_PASS")
        if not user or not pwd:
            raise RuntimeError("Mancano JRC_USER e JRC_PASS nel file .env")
        self.s.cookies.clear()
        self._get("/login.html")  # prende il cookie di sessione
        self._req("POST", "/autentica.html",
                  data={"txt_login": user, "txt_password": pwd, "staylogged": "1"},
                  headers={"Referer": BASE + "/login.html"})
        self._salva_sessione()

    @staticmethod
    def _loggato(html):
        return bool(re.search(r"Prezzo\s+(Scatola|Sfuso|1 Pezzo)", html, re.I))

    def _pagina_prodotto(self, pid, cod=None):
        path = f"/scheda-prodotto.html?id={pid}" + (f"&cod={cod}" if cod else "")
        html = self._get(path).text
        if not self._loggato(html):
            self.login()
            html = self._get(path).text
            if not self._loggato(html):
                DEBUG_DIR.mkdir(exist_ok=True)
                (DEBUG_DIR / f"non-loggato-{pid}.html").write_text(html)
                raise RuntimeError("Login non riuscito: controlla JRC_USER/JRC_PASS nel .env")
        return html

    # ---- ricerca ----
    def cerca(self, q):
        html = self._get("/search.html", params={"q": q}).text
        soup = BeautifulSoup(html, "html.parser")
        risultati = []
        for box in soup.select("div.single-product-box"):
            titolo = box.select_one("h3 a")
            if not titolo:
                continue
            pid = re.search(r"id=(\d+)", titolo.get("href", ""))
            colori = []
            for a in box.select("a[title][href*='cod=']"):
                m = re.search(r"cod=([\w-]+)", a["href"])
                if m:
                    colori.append({"colore": a["title"].strip(), "cod": m.group(1)})
            img = box.select_one("img")
            risultati.append({
                "id": pid.group(1) if pid else None,
                "nome": titolo.get_text(strip=True),
                "colori": colori,
                "foto": BASE + img["src"] if img and img.get("src", "").startswith("/") else None,
            })
        return risultati

    # ---- scheda prodotto ----
    def articolo(self, pid, cod=None):
        html = self._pagina_prodotto(pid, cod)
        return self._leggi_scheda(html, pid, cod)

    def articolo_da_codice(self, cod):
        for r in self.cerca(cod):
            for c in r["colori"]:
                if c["cod"].split("-")[0] == cod.split("-")[0]:
                    return self.articolo(r["id"], c["cod"])
        raise RuntimeError(f"Codice {cod} non trovato su James Ross")

    def _leggi_scheda(self, html, pid, cod):
        soup = BeautifulSoup(html, "html.parser")
        out = {"fornitore": "James Ross", "id": str(pid), "cod": cod,
               "url": f"{BASE}/scheda-prodotto.html?id={pid}" + (f"&cod={cod}" if cod else "")}
        h1 = soup.find("h1")
        out["nome"] = h1.get_text(strip=True) if h1 else None
        for li in soup.find_all("li"):
            t = li.get_text(" ", strip=True)
            for etichetta, chiave in (("Codice:", "codice"), ("Colore:", "colore"), ("Taglie:", "taglie")):
                if t.startswith(etichetta) and chiave not in out:
                    val = t[len(etichetta):].strip()
                    out[chiave] = [x.strip() for x in val.split(",")] if chiave == "taglie" else val
        # colori disponibili (blocco SCEGLI COLORE, prima dei correlati)
        principale = html.split("Prodotti Correlati")[0]
        out["colori"] = []
        for a in BeautifulSoup(principale, "html.parser").select(f"a[title][href*='id={pid}&cod=']"):
            m = re.search(r"cod=([\w-]+)", a["href"])
            if m and not any(c["cod"] == m.group(1) for c in out["colori"]):
                out["colori"].append({"colore": a["title"].strip(), "cod": m.group(1)})
        testo = BeautifulSoup(principale, "html.parser").get_text("\n", strip=True)
        piatto = re.sub(r"\s+", " ", testo)
        intero = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        # prezzi: "Prezzo Scatola: 24,60 €" (cerca prima nella scheda, poi in tutta la pagina,
        # poi nell'HTML grezzo nel caso il valore stia in uno script o attributo)
        out["prezzi"] = {}
        crudo = re.sub(r"<[^>]+>", " ", html).replace("&euro;", "€").replace("&nbsp;", " ")
        crudo = re.sub(r"\s+", " ", crudo)
        for fonte in (piatto, intero, crudo):
            for m in re.finditer(r"Prezzo\s*(Scatola|Sfuso|1\s*Pezzo|Cartone|Unitario)\s*:?\s*(?:€\s*)?(\d{1,4}[.,]\d{2})",
                                 fonte, re.I):
                out["prezzi"].setdefault(re.sub(r"\s+", " ", m.group(1)).lower(), numero(m.group(2)))
            if out["prezzi"]:
                break
        m = re.search(r"CARTONE\s*:?\s*(\d+)\s*pezzi", intero, re.I)
        out["cartone_pezzi"] = int(m.group(1)) if m else None
        m = re.search(r"PESO\s*:?\s*(\d[\d.,]*\s*(?:g/m\S*|gr\S*)(?:\s*\+\s*[\d.,]+\s*(?:g/m\S*|gr\S*))?)", intero, re.I)
        out["peso"] = m.group(1).strip() if m else None
        out["giacenze"] = self._leggi_giacenze(soup)
        if not out["prezzi"]:
            DEBUG_DIR.mkdir(exist_ok=True)
            (DEBUG_DIR / f"scheda-{pid}-{cod}.html").write_text(html)
        return out

    def diagnosi(self, cod):
        """Estratti di testo della scheda (da loggato) attorno a prezzi e peso, per correggere il bot."""
        pid = None
        for r in self.cerca(cod):
            if any(c["cod"].split("-")[0] == cod.split("-")[0] for c in r["colori"]):
                pid = r["id"]
                break
        if not pid:
            raise RuntimeError(f"Codice {cod} non trovato")
        html = self._pagina_prodotto(pid, cod)
        out = {"id": pid, "lunghezza_html": len(html), "estratti_html": []}
        for parola in ("Prezzo", "PESO", "Prodotti Correlati"):
            for m in list(re.finditer(parola, html))[:4]:
                pezzo = html[max(0, m.start() - 150): m.start() + 450]
                pezzo = re.sub(r'(name|value)="[^"]*(pass|token|session)[^"]*"', r'\1="***"', pezzo, flags=re.I)
                out["estratti_html"].append(pezzo)
        return out

    @staticmethod
    def _leggi_giacenze(soup):
        """Tabella 'GIACENZE INDICATIVE': taglie in intestazione, una riga per variante."""
        for tab in soup.find_all("table"):
            righe = tab.find_all("tr")
            if not righe or "GIACENZ" not in righe[0].get_text().upper():
                continue
            intest = [c.get_text(" ", strip=True) for c in righe[0].find_all(["th", "td"])]
            taglie = intest[1:]
            blocchi = []
            for tr in righe[1:]:
                celle = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
                if len(celle) < 2 or not celle[0] or tr.find("input"):
                    continue
                valori = {t: numero(v) for t, v in zip(taglie, celle[1:]) if t}
                if any(v is not None for v in valori.values()):
                    blocchi.append({"riga": celle[0], "per_taglia": valori})
            return blocchi
        return []

    # ---- ricerca completa ----
    def cerca_completo(self, q, massimo=5):
        parole = [p.lower() for p in q.split()]
        risultati = self.cerca(q)
        if not risultati and len(parole) > 1:
            # il sito cerca la frase intera: riprova senza le parole-colore
            risultati = self.cerca(parole[0])
        schede = []
        for r in risultati[:massimo]:
            # se nella richiesta c'è un colore, apri quella variante
            scelta = next((c for c in r["colori"] if c["colore"].lower() in q.lower()), None)
            scelta = scelta or (r["colori"][0] if r["colori"] else {"cod": None})
            schede.append(self.articolo(r["id"], scelta["cod"]))
        return {"richiesta": q, "trovati": len(risultati), "articoli": schede}


def stampa(scheda):
    p = scheda.get("prezzi", {})
    prezzi = " | ".join(f"{k}: {v:.2f}€" for k, v in p.items() if isinstance(v, (int, float))) or "prezzi non letti"
    print(f"\n■ {scheda.get('nome')}  —  cod {scheda.get('codice')}  ({scheda.get('colore')})")
    print(f"  {prezzi}  | cartone {scheda.get('cartone_pezzi')} pz | {scheda.get('peso') or ''}")
    print(f"  Colori: {', '.join(c['colore'] for c in scheda.get('colori', []))}")
    for g in scheda.get("giacenze", []):
        tot = g["per_taglia"].get("TOTALE")
        taglie = ", ".join(f"{t} {v}" for t, v in g["per_taglia"].items() if t != "TOTALE")
        print(f"  Stock: {taglie}  → totale {tot}")
    print(f"  {scheda.get('url')}")


def serve(bot, porta):
    token = os.environ.get("JRC_API_TOKEN")
    if not token:
        raise SystemExit("Manca JRC_API_TOKEN nel .env")

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.headers.get("Authorization") != f"Bearer {token}":
                return self._json(401, {"errore": "non autorizzato"})
            u = urlparse(self.path)
            qs = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path == "/cerca" and qs.get("q"):
                    return self._json(200, bot.cerca_completo(qs["q"], int(qs.get("max", 5))))
                if u.path == "/articolo" and qs.get("cod"):
                    return self._json(200, bot.articolo_da_codice(qs["cod"]))
                return self._json(404, {"uso": "/cerca?q=felpa navy  |  /articolo?cod=987690"})
            except Exception as e:  # noqa
                return self._json(500, {"errore": str(e)})

        def _json(self, code, data):
            body = json.dumps(data, ensure_ascii=False, indent=1).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    print(f"API James Ross attiva sulla porta {porta}")
    ThreadingHTTPServer(("0.0.0.0", porta), H).serve_forever()


def main():
    carica_env()
    ap = argparse.ArgumentParser(description="Bot James Ross per Hirostampe")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cerca"); c.add_argument("q"); c.add_argument("--max", type=int, default=5); c.add_argument("--json", action="store_true")
    a = sub.add_parser("articolo"); a.add_argument("cod"); a.add_argument("--json", action="store_true")
    s = sub.add_parser("serve"); s.add_argument("--porta", type=int, default=8765)
    sub.add_parser("login")
    args = ap.parse_args()
    bot = JRC()
    if args.cmd == "login":
        bot.login(); print("Sessione salvata.")
    elif args.cmd == "cerca":
        res = bot.cerca_completo(args.q, args.max)
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=1))
        else:
            print(f"Trovati {res['trovati']} articoli per «{args.q}» (mostro {len(res['articoli'])})")
            for s_ in res["articoli"]:
                stampa(s_)
    elif args.cmd == "articolo":
        res = bot.articolo_da_codice(args.cod)
        print(json.dumps(res, ensure_ascii=False, indent=1)) if args.json else stampa(res)
    elif args.cmd == "serve":
        serve(bot, args.porta)


if __name__ == "__main__":
    main()
