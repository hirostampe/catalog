#!/usr/bin/env python3
"""Bot Innovative Wear (innovativewear.com) per Hirostampe.

Entra col tuo account, cerca nel catalogo e legge colori, taglie, prezzi e disponibilità.

Uso:
  python3 iwear.py cerca "felpa"
  python3 iwear.py articolo JC052
Credenziali nel .env: IWEAR_USER (email o codice utente) e IWEAR_PASS.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from jrc import UA, carica_env, numero

BASE = "https://www.innovativewear.com"
HERE = Path(__file__).resolve().parent
COOKIE_FILE = HERE / ".sessione-iwear.json"
PAUSA = 2.0


def _pulisci(testo):
    return re.sub(r"\s+", " ", testo or "").strip()


class IWear:
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
                r.encoding = "utf-8"
                return r
            except (requests.ConnectionError, requests.Timeout):
                self._ultima = time.time()
                time.sleep(5 * (tentativo + 1))
        raise RuntimeError(f"Innovative Wear non risponde: {url}")

    def _get(self, path, **kw):
        return self._req("GET", path, **kw)

    # ---- login ----
    @staticmethod
    def _loggato(html):
        return "sign_out" in html or "js_popupLogin colorSwitch" not in html and "js_buyingArea" in html

    def login(self):
        user, pwd = os.environ.get("IWEAR_USER"), os.environ.get("IWEAR_PASS")
        if not user or not pwd:
            raise RuntimeError("Mancano IWEAR_USER e IWEAR_PASS nel file .env")
        self.s.cookies.clear()
        html = self._get("/users/sign_in").text
        m = re.search(r'name="authenticity_token" value="([^"]+)"', html)
        if not m:
            raise RuntimeError("Pagina di login Innovative Wear cambiata: avvisa Claude")
        self._req("POST", "/users/sign_in", data={
            "utf8": "✓", "authenticity_token": m.group(1),
            "user[email]": user, "user[password]": pwd,
            "user[remember_me]": "1", "commit": "Accedi",
        }, headers={"Referer": BASE + "/users/sign_in"})
        COOKIE_FILE.write_text(json.dumps(self.s.cookies.get_dict()))
        os.chmod(COOKIE_FILE, 0o600)

    def _pagina(self, path):
        html = self._get(path).text
        if not self._loggato(html):
            self.login()
            html = self._get(path).text
            if not self._loggato(html):
                raise RuntimeError("Login Innovative Wear non riuscito: controlla IWEAR_USER/IWEAR_PASS nel .env")
        return html

    # ---- ricerca ----
    def cerca(self, q, pagina=1):
        html = self._get("/cerca", params={"t": q, "per_page": 24, "page": pagina}).text
        soup = BeautifulSoup(html, "html.parser")
        out = []
        for box in soup.select("div.productGridView"):
            cod = box.select_one(".productCode a")
            if not cod:
                continue
            titolo = box.select_one(".productTitle a")
            marca = box.select_one(".productBrand")
            out.append({
                "codice": cod.get_text(strip=True),
                "nome": titolo.get_text(strip=True) if titolo else None,
                "marca": _pulisci(marca.get_text()) if marca else None,
                "url": BASE + cod["href"].split("?")[0],
            })
        m = re.search(r"(\d+)\s+prodotti", html)
        return {"totale": int(m.group(1)) if m else len(out), "risultati": out}

    # ---- scheda ----
    def articolo(self, codice):
        path = f"/vendita/{codice.strip().lower()}"
        html = self._pagina(path)
        soup = BeautifulSoup(html, "html.parser")
        out = {"fornitore": "Innovative Wear", "codice": codice.upper(), "url": BASE + path}
        h1 = soup.find("h1")
        out["nome"] = _pulisci(h1.get_text()) if h1 else None
        testo = soup.get_text("\n", strip=True)
        for campo in ("Composizione", "Grammatura", "Modello", "Marchio", "Origine", "Tessuto"):
            m = re.search(rf"\n{campo}\n([^\n]+)", testo)
            if m:
                out[campo.lower()] = m.group(1).strip()
        m = re.search(r"Cartone da (\d+) pezzi", testo)
        out["cartone_pezzi"] = int(m.group(1)) if m else None
        # colori (codice + nome)
        out["colori"] = []
        for a in soup.select("a.colorSwitch, a.js_colorswitch"):
            c = {"codice": a.get("data-color"), "nome": re.sub(r"\s*\([^)]*\)$", "", a.get("title", "")),
                 "id_colore": a.get("data-fid1")}
            if c["codice"] and c not in out["colori"]:
                out["colori"].append(c)
        # disponibilità e prezzi: una riga per colore dentro #js_buyingArea
        area = soup.select_one("#js_buyingArea")
        out["disponibilita"] = self._leggi_area(area) if area else []
        return out

    @staticmethod
    def _leggi_area(area):
        """Legge la tabella acquisto. Per ogni colore: taglie con stock e prezzo se riconoscibili,
        più il testo della riga (così i dati restano leggibili anche se il layout cambia)."""
        righe = []
        blocchi = area.select("div.js_variationRow") or [area]
        for b in blocchi:
            r = {"colore": b.get("id")}
            taglie = []
            for inp in b.select("input.js_quantity, input.js_changeQuantity"):
                var = inp.get("data-variation")
                cella = inp.find_parent(["td", "div"])
                riga = inp.find_parent("tr") or cella
                t = {"variante": var}
                prezzo = b.select_one(f"#price_for{var}") if var else None
                if prezzo:
                    t["prezzo"] = numero(prezzo.get_text())
                for k in ("data-size", "data-taglia", "data-stock", "data-availability", "max"):
                    if inp.get(k):
                        t[k.replace("data-", "")] = inp.get(k)
                if riga is not None and riga is not cella:
                    t["testo_riga"] = _pulisci(riga.get_text(" | "))[:200]
                taglie.append(t)
            if taglie:
                r["taglie"] = taglie
            r["testo"] = _pulisci(b.get_text(" | "))[:1500]
            righe.append(r)
        return righe

    def prezzi_quantita(self, variante):
        """Scaglioni di prezzo per quantità di una variante (popup 'Prezzi per quantità')."""
        r = self._req("GET", "/product/get_variation_prices", params={"variation": variante},
                      headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"})
        try:
            return _pulisci(BeautifulSoup(r.json().get("html", ""), "html.parser").get_text(" | "))
        except ValueError:
            return None

    def cerca_completo(self, q, massimo=5):
        res = self.cerca(q)
        schede = [self.articolo(r["codice"]) for r in res["risultati"][:massimo]]
        return {"richiesta": q, "trovati": res["totale"], "elenco": res["risultati"][:24], "articoli": schede}

    def diagnosi(self, codice):
        html = self._pagina(f"/vendita/{codice.strip().lower()}")
        soup = BeautifulSoup(html, "html.parser")
        area = soup.select_one("#js_buyingArea")
        for tag in soup.select("input[name=authenticity_token], meta[name=csrf-token]"):
            tag.decompose()
        return {
            "loggato": self._loggato(html),
            "html_area_acquisto": str(area)[:12000] if area else None,
            "html_colori": str(soup.select_one(".js_colorswitches"))[:4000],
        }


if __name__ == "__main__":
    carica_env()
    bot = IWear()
    if len(sys.argv) >= 3 and sys.argv[1] == "cerca":
        print(json.dumps(bot.cerca_completo(" ".join(sys.argv[2:]), 3), ensure_ascii=False, indent=1))
    elif len(sys.argv) >= 3 and sys.argv[1] == "articolo":
        print(json.dumps(bot.articolo(sys.argv[2]), ensure_ascii=False, indent=1))
    else:
        print(__doc__)
