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
    def articolo(self, codice, filtro_colore=None):
        codice = codice.strip()
        if " " in codice and not filtro_colore:  # es. "JC052 navy"
            codice, filtro_colore = codice.split(" ", 1)
        path = f"/vendita/{codice.lower()}"
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
        disp = self._leggi_area(area) if area else []
        if filtro_colore:
            parole = [w for w in filtro_colore.lower().split() if len(w) > 1]
            scelti = [c for c in disp if any(w in c["colore"].lower() for w in parole)]
            disp = scelti or disp
        if len(disp) > 8:
            out["nota"] = (f"Mostro 8 colori su {len(disp)}. Per un colore preciso chiedi la scheda con "
                           f"codice '{codice.upper()} <colore>', es. '{codice.upper()} navy'.")
            disp = disp[:8]
        out["disponibilita"] = disp
        out["legenda"] = "prezzo = € unitario IVA esclusa; 'disp. 1/2 gg' e 'disp. 5/6 gg' = pezzi disponibili con quei tempi di consegna"
        return out

    @staticmethod
    def _leggi_area(area):
        """Tabella acquisto: un blocco per colore; per ogni taglia prezzo unitario,
        disponibilità per tempi di consegna (1/2 gg, 5/6 gg…), arrivi, outlet."""
        colori = []
        for b in area.select("div.js_variationRow"):
            lab = b.select_one("p.colorLabel")
            col = {"colore": _pulisci(lab.get_text(" ")) if lab else b.get("id"), "codice_colore": b.get("id"),
                   "taglie": {}}
            tabella = None
            for t in b.select("table"):
                if t.select("td"):
                    tabella = t
                    break
            if not tabella:
                continue
            taglie = [_pulisci(th.get_text()) for th in tabella.select("tr.tableHeader th")][1:]
            celle = tabella.select("tr:not(.tableHeader) > td")
            if not celle:
                continue
            # prima colonna = etichette (Prezzo unit., Quantità, Consegna 1/2 gg, Consegna 5/6 gg, Arrivi)
            etichette = []
            for p_ in celle[0].find_all("p"):
                cls = " ".join(p_.get("class", []))
                testo = _pulisci(p_.get_text())
                if "pPrice" in cls or "qty" in cls:
                    continue
                etichette.append((p_.get("class", [""])[0], testo.lower()))
            for taglia, td in zip(taglie, celle[1:]):
                d = {}
                prezzo = td.select_one("p.pPrice")
                if prezzo:
                    d["prezzo"] = numero(prezzo.get_text())
                for classe, nome in etichette:
                    p_ = td.find("p", class_=classe)
                    if p_ is None:
                        continue
                    v = _pulisci(p_.get_text())
                    n = numero(v) if re.fullmatch(r"[\d.]+", v) else None
                    d[nome.replace("consegna ", "disp. ")] = n if n is not None else v
                inp = td.select_one("input[data-variation]")
                if inp:
                    d["variante"] = inp["data-variation"]
                if td.select_one(".ribbonOutlet"):
                    d["outlet"] = True
                col["taglie"][taglia] = d
            colori.append(col)
        return colori

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
        if not res["risultati"] and len(q.split()) > 1:
            res = self.cerca(q.split()[0])
        colori_noti = ("navy", "blu", "nero", "black", "bianco", "white", "rosso", "red", "grigio", "grey",
                       "gray", "verde", "green", "royal", "giallo", "yellow", "arancio", "orange", "rosa", "pink",
                       "bordeaux", "burgundy", "maroon", "azzurro", "sky", "beige", "sand", "kaki", "khaki", "viola", "purple")
        filtro = " ".join(w for w in q.lower().split() if w in colori_noti) or None
        schede = [self.articolo(r["codice"], filtro) for r in res["risultati"][:massimo]]
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
