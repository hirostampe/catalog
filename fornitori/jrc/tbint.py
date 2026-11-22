#!/usr/bin/env python3
"""TB International (Urban Classics, Build Your Brand, Flexfit…) per Hirostampe.

Fonte ufficiale: il server FTP ftp.tbint.de con listino prodotti e file disponibilità
(credenziali dal foglio di benvenuto TB International, nel .env).
I file vengono scaricati sul server e aggiornati ogni 6 ore al massimo, poi si cerca in locale.

Uso:
  python3 tbint.py scarica
  python3 tbint.py cerca "hoodie navy"
  python3 tbint.py diagnosi
"""
import csv
import ftplib
import io
import json
import os
import re
import sys
import time
import zipfile
from pathlib import Path

from jrc import carica_env

HERE = Path(__file__).resolve().parent
DATI = HERE / "dati" / "tbint"
HOST = "ftp.tbint.de"
VALIDITA = 26 * 3600  # in ricerca riscarica solo se i file hanno più di 26 ore (il cron li aggiorna ogni 6)
ESTENSIONI = (".csv", ".txt", ".xlsx", ".xls", ".zip", ".json", ".xml")
MAX_FILE = 300 * 1024 * 1024


def _account():
    acc = []
    if os.environ.get("TBINT_FTP_USER"):
        acc.append(("urban", os.environ["TBINT_FTP_USER"], os.environ.get("TBINT_FTP_PASS", "")))
    if os.environ.get("BYB_FTP_USER"):
        acc.append(("byb", os.environ["BYB_FTP_USER"], os.environ.get("BYB_FTP_PASS", "")))
    if not acc:
        raise RuntimeError("Mancano TBINT_FTP_USER/TBINT_FTP_PASS nel file .env")
    return acc


def _elenca(ftp, cartella="", profondita=2):
    """Elenca i file (percorso, dimensione) fino a 2 livelli di cartelle."""
    out = []
    try:
        voci = list(ftp.mlsd(cartella or "."))
        for nome, info in voci:
            if nome in (".", ".."):
                continue
            percorso = f"{cartella}/{nome}" if cartella else nome
            if info.get("type") == "dir" and profondita > 0:
                out += _elenca(ftp, percorso, profondita - 1)
            elif info.get("type") == "file":
                out.append((percorso, int(info.get("size", 0))))
    except ftplib.error_perm:
        # server senza MLSD: uso NLST
        for percorso in ftp.nlst(cartella or "."):
            try:
                out.append((percorso, ftp.size(percorso) or 0))
            except ftplib.error_perm:
                if profondita > 0:
                    out += _elenca(ftp, percorso, profondita - 1)
    return out


def scarica(forza=False):
    """Scarica (se vecchi) i file dall'FTP. Ritorna l'elenco dei file locali."""
    DATI.mkdir(parents=True, exist_ok=True)
    stato_f = DATI / "_stato.json"
    stato = json.loads(stato_f.read_text()) if stato_f.exists() else {}
    if not forza and time.time() - stato.get("ultimo", 0) < VALIDITA:
        return stato.get("file", [])
    locali = []
    for sigla, user, pwd in _account():
        ftp = ftplib.FTP(HOST, timeout=60)
        ftp.login(user, pwd)
        ftp.set_pasv(True)
        for percorso, dim in _elenca(ftp):
            if not percorso.lower().endswith(ESTENSIONI) or dim > MAX_FILE:
                continue
            dest = DATI / sigla / percorso.lstrip("./")
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not (dest.exists() and dest.stat().st_size == dim and not forza and
                    time.time() - dest.stat().st_mtime < VALIDITA):
                with open(dest, "wb") as fh:
                    ftp.retrbinary(f"RETR {percorso}", fh.write)
            if dest.suffix.lower() == ".zip":
                with zipfile.ZipFile(dest) as z:
                    z.extractall(dest.parent / (dest.stem + "_zip"))
            locali.append(str(dest.relative_to(DATI)))
        ftp.quit()
    stato = {"ultimo": time.time(), "file": locali}
    stato_f.write_text(json.dumps(stato, indent=1))
    _dialetti.clear()
    costruisci_indice()
    return locali


# ---------- lettura tabelle (a flusso: i file sono centinaia di MB) ----------
_dialetti = {}


def _encoding(p):
    with open(p, "rb") as fh:
        campione = fh.read(200000)
    try:
        campione.decode("utf-8")
        return "utf-8-sig"
    except UnicodeDecodeError:
        return "cp1252"


def _righe(p):
    """Generatore: prima riga = intestazioni, poi le righe (senza caricare tutto in memoria)."""
    if p.suffix.lower() == ".xlsx":
        import openpyxl
        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
        for r in wb.worksheets[0].iter_rows(values_only=True):
            yield ["" if v is None else str(v) for v in r]
        return
    if p not in _dialetti:
        enc = _encoding(p)
        with open(p, encoding=enc, errors="replace", newline="") as fh:
            campione = fh.read(20000)
        delim = max(";,\t|", key=campione.count)
        _dialetti[p] = (enc, delim)
    enc, delim = _dialetti[p]
    with open(p, encoding=enc, errors="replace", newline="") as fh:
        for r in csv.reader(fh, delimiter=delim):
            if any(c.strip() for c in r):
                yield r


def _file_tabellari():
    """Per ogni account: un solo listino (preferenza inglese) + tutti i file disponibilità."""
    scelti = []
    for cartella in sorted(p for p in DATI.iterdir() if p.is_dir()):
        tutti = [p for p in cartella.rglob("*") if p.is_file() and p.suffix.lower() in (".csv", ".txt", ".xlsx")]
        listini = [p for p in tutti if "product" in p.name.lower()]
        dispo = [p for p in tutti if p.name.lower().startswith("ava")]
        for pref in ("_en.", "_v2.", ""):
            m = [p for p in listini if pref in p.name.lower()]
            if m:
                scelti.append(m[0])
                break
        scelti += dispo
        scelti += [p for p in tutti if p not in listini and p not in dispo]
    return scelti


def _riga_dict(intest, r):
    return {(intest[i] if i < len(intest) and intest[i] else f"col{i}"): v.strip()
            for i, v in enumerate(r) if v.strip()}


def _scorri(filtro, massimo):
    out = {}
    for p in _file_tabellari():
        it = _righe(p)
        intest = [c.strip() for c in next(it, [])]
        trovate = []
        for r in it:
            if filtro(r):
                trovate.append(_riga_dict(intest, r))
                if len(trovate) >= massimo:
                    break
        if trovate:
            out[str(p.relative_to(DATI))] = trovate
    return out


# ---------- indice SQLite (listino v2 + disponibilità unite per EAN) ----------
import sqlite3

DB = DATI / "indice.sqlite"

SINONIMI = {  # parole italiane -> come compaiono nei listini TB (inglese)
    "felpa": ["hoody", "hoodie", "sweat", "crew", "zip"], "felpe": ["hoody", "hoodie", "sweat", "crew", "zip"],
    "cappuccio": ["hoody", "hoodie"], "girocollo": ["crew"], "zip": ["zip"],
    "maglietta": ["tee", "t-shirt", "shirt"], "tshirt": ["tee", "t-shirt"], "t-shirt": ["tee", "t-shirt"],
    "canotta": ["tank"], "polo": ["polo"], "pantaloni": ["pants", "trousers", "jogger"], "pantaloncini": ["shorts"],
    "cappello": ["cap", "hat", "beanie"], "cappellino": ["cap"], "berretto": ["beanie"], "giacca": ["jacket"],
    "giubbotto": ["jacket"], "smanicato": ["vest", "bodywarmer"], "borsa": ["bag"], "zaino": ["backpack"],
    "donna": ["ladies", "women", "female"], "uomo": ["men", "male"], "bambino": ["kids"], "bimbo": ["kids"],
    "nero": ["black"], "bianco": ["white"], "blu": ["navy", "blue"], "grigio": ["grey", "gray"],
    "rosso": ["red"], "verde": ["green", "olive"], "giallo": ["yellow"], "rosa": ["pink"],
    "beige": ["sand", "beige"], "marrone": ["brown"], "viola": ["purple", "violet", "lilac"],
}
COLORI = {"black", "white", "navy", "blue", "grey", "gray", "red", "green", "olive", "yellow", "pink", "sand",
          "beige", "brown", "purple", "violet", "lilac", "orange", "royal", "charcoal", "khaki", "burgundy"}


def _num(v):
    v = (v or "").strip().replace(",", ".")
    try:
        return float(v)
    except ValueError:
        return None


def _data_valida(v):
    v = (v or "").strip()
    return "" if not v or v.startswith("1900") else v


def costruisci_indice():
    """Crea indice.sqlite dai listini v2 e dai file disponibilità (circa 1 minuto)."""
    tmp = DB.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    con.execute("""CREATE TABLE art(ean TEXT PRIMARY KEY, codice TEXT, stile TEXT, nome TEXT, descr TEXT,
                   marca TEXT, categoria TEXT, colore TEXT, taglia TEXT, prezzo REAL, prezzo_pubblico REAL,
                   composizione TEXT, genere TEXT, foto TEXT, testo TEXT)""")
    con.execute("CREATE TABLE disp(ean TEXT PRIMARY KEY, stock INTEGER, prossimo_arrivo TEXT, qta_in_arrivo INTEGER)")
    for p in sorted(DATI.glob("*/Product_List_v2.csv")):
        it = _righe(p)
        h = {n.strip(): k for k, n in enumerate(next(it, []))}
        g = lambda r, n: r[h[n]].strip() if n in h and h[n] < len(r) else ""
        lotto = []
        for r in it:
            ean = g(r, "EAN")
            if not ean:
                continue
            rec = (ean, g(r, "ItemCode"), g(r, "StyleCode"), g(r, "StyleName"), g(r, "ItemDescription"),
                   g(r, "Brand"), g(r, "ItemMainCategory"), g(r, "Color"), g(r, "Size"),
                   _num(g(r, "Wholesale_Price_Euro")), _num(g(r, "Retail_Price_Euro")),
                   g(r, "ProductsComposition"), g(r, "Gender"),
                   g(r, "ImageModelMW1") or g(r, "ImageProductP1"))
            testo = " ".join([rec[1], rec[2], rec[3], rec[4], rec[5], rec[6], rec[7], rec[12]]).lower()
            lotto.append(rec + (testo,))
            if len(lotto) >= 5000:
                con.executemany("INSERT OR IGNORE INTO art VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", lotto)
                lotto = []
        con.executemany("INSERT OR IGNORE INTO art VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", lotto)
    # disponibilità: formati diversi a seconda del file
    for p in sorted(DATI.glob("*/*")):
        if not p.is_file() or not p.name.lower().startswith("ava"):
            continue
        it = _righe(p)
        h = {n.strip().lower(): k for k, n in enumerate(next(it, []))}
        col = lambda *nomi: next((h[n] for n in nomi if n in h), None)
        c_ean = col("ean", "products_ean")
        c_qta = col("quantity", "stock", "current_stock")
        c_data = col("nextdeliverydate", "next expected delivery date", "next_delivery_date", "future_stock_date")
        c_arr = col("nextdeliverystock", "future_stock")
        if c_ean is None or c_qta is None:
            continue
        lotto = []
        for r in it:
            try:
                ean = r[c_ean].strip()
                qta = int(_num(r[c_qta]) or 0)
            except (IndexError, TypeError):
                continue
            data = _data_valida(r[c_data]) if c_data is not None and c_data < len(r) else ""
            arr = int(_num(r[c_arr]) or 0) if c_arr is not None and c_arr < len(r) else None
            lotto.append((ean, qta, data, arr))
        con.executemany("""INSERT INTO disp VALUES (?,?,?,?) ON CONFLICT(ean) DO UPDATE SET
                           stock=max(stock, excluded.stock),
                           prossimo_arrivo=coalesce(nullif(excluded.prossimo_arrivo,''), prossimo_arrivo),
                           qta_in_arrivo=coalesce(excluded.qta_in_arrivo, qta_in_arrivo)""", lotto)
    con.execute("CREATE INDEX i_stile ON art(stile)")
    con.execute("CREATE INDEX i_codice ON art(codice)")
    con.commit()
    con.close()
    tmp.replace(DB)


def _db():
    scarica()
    sorgenti = list(DATI.glob("*/Product_List_v2.csv")) + [p for p in DATI.glob("*/*") if p.name.lower().startswith("ava")]
    if not DB.exists() or any(p.stat().st_mtime > DB.stat().st_mtime for p in sorgenti):
        costruisci_indice()
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def _stile(con, stile, colori_filtro=None):
    righe = con.execute("""SELECT a.*, d.stock, d.prossimo_arrivo, d.qta_in_arrivo FROM art a
                           LEFT JOIN disp d ON d.ean = a.ean WHERE a.stile = ?""", (stile,)).fetchall()
    if not righe:
        return None
    r0 = righe[0]
    out = {"fornitore": "TB International", "stile": stile, "nome": r0["nome"], "marca": r0["marca"],
           "categoria": r0["categoria"], "genere": r0["genere"], "composizione": r0["composizione"],
           "foto": r0["foto"], "colori_disponibili": sorted({r["colore"] for r in righe}), "per_colore": {}}
    prezzi = [r["prezzo"] for r in righe if r["prezzo"]]
    out["prezzo_ingrosso"] = {"min": min(prezzi), "max": max(prezzi)} if prezzi else None
    pp = [r["prezzo_pubblico"] for r in righe if r["prezzo_pubblico"]]
    out["prezzo_pubblico"] = max(pp) if pp else None
    for r in righe:
        if colori_filtro and not any(c in r["colore"].lower() for c in colori_filtro):
            continue
        t = {"stock": r["stock"] if r["stock"] is not None else "n.d.", "prezzo": r["prezzo"], "codice": r["codice"]}
        if r["prossimo_arrivo"]:
            t["arrivo"] = r["prossimo_arrivo"] + (f" ({r['qta_in_arrivo']} pz)" if r["qta_in_arrivo"] else "")
        out["per_colore"].setdefault(r["colore"], {})[r["taglia"]] = t
    ordine = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "2XL", "3XL", "4XL", "5XL", "6XL", "7XL"]
    pos = lambda t: ordine.index(t.upper()) if t.upper() in ordine else 100
    out["per_colore"] = {c: dict(sorted(d.items(), key=lambda kv: (pos(kv[0]), kv[0])))
                         for c, d in out["per_colore"].items()}
    if not colori_filtro and len(out["per_colore"]) > 6:
        tot = {c: sum(v["stock"] for v in d.values() if isinstance(v["stock"], int)) for c, d in out["per_colore"].items()}
        tenuti = sorted(tot, key=tot.get, reverse=True)[:6]
        out["per_colore"] = {c: out["per_colore"][c] for c in tenuti}
        out["nota"] = "Mostro i 6 colori con più stock: per gli altri cerca con il colore nella richiesta."
    out["stock_totale"] = sum(v["stock"] for d in out["per_colore"].values() for v in d.values()
                              if isinstance(v["stock"], int))
    return out


def cerca(q, massimo=5):
    con = _db()
    parole = [w.lower() for w in q.split() if w.strip()]
    condizioni, parametri, colori = [], [], []
    for w in parole:
        varianti = SINONIMI.get(w, [w])
        if any(v in COLORI for v in varianti):
            colori += [v for v in varianti if v in COLORI]
        condizioni.append("(" + " OR ".join("testo LIKE ?" for _ in varianti) + ")")
        parametri += [f"%{v}%" for v in varianti]
    sql = f"""SELECT a.stile, sum(coalesce(d.stock,0)) tot FROM art a LEFT JOIN disp d ON d.ean=a.ean
              WHERE {' AND '.join(condizioni) or '1'} GROUP BY a.stile ORDER BY tot DESC LIMIT ?"""
    stili = [r["stile"] for r in con.execute(sql, parametri + [max(massimo, 1)])]
    if not stili and len(parole) > 1:  # riprova senza i colori
        return cerca(" ".join(w for w in parole if not any(v in COLORI for v in SINONIMI.get(w, [w]))), massimo)
    articoli = [_stile(con, s, colori or None) for s in stili]
    return {"fornitore": "TB International (Urban Classics, Build Your Brand, Flexfit, Mister Tee…)",
            "richiesta": q, "articoli": [a for a in articoli if a],
            "legenda": "prezzo = prezzo all'ingrosso € (listino TB); stock = pezzi a magazzino ora; "
                       "dati dai file ufficiali FTP (aggiornati ogni 6 ore); verifica lo stock prima di confermare ordini grandi."}


def cerca_completo(q, massimo=5):
    return cerca(q, massimo)


def scheda(codice):
    """Scheda di uno stile (es. 'TB014', 'BY011') o di un codice completo (es. 'BY011-00007-0037')."""
    con = _db()
    cod = codice.strip().split()[0].upper()
    filtro = [w.lower() for w in codice.split()[1:]] or None
    r = con.execute("SELECT stile FROM art WHERE upper(stile)=? OR upper(codice)=? OR ean=? LIMIT 1",
                    (cod, cod, cod)).fetchone()
    if not r:
        r = con.execute("SELECT stile FROM art WHERE upper(codice) LIKE ? LIMIT 1", (cod + "-%",)).fetchone()
    if not r:
        raise RuntimeError(f"Codice {codice} non trovato nei file TB International")
    return _stile(con, r["stile"], filtro)


def diagnosi(_codice=""):
    """Elenco file con dimensione, intestazioni e prime 3 righe (letti a flusso)."""
    scarica()
    out = {"file_usati_per_le_ricerche": [str(p.relative_to(DATI)) for p in _file_tabellari()], "tabelle": {}}
    for p in sorted(x for x in DATI.rglob("*") if x.is_file() and x.suffix.lower() in (".csv", ".txt", ".xlsx")):
        it = _righe(p)
        intest = next(it, [])
        esempio = [next(it, []) for _ in range(3)]
        out["tabelle"][str(p.relative_to(DATI))] = {
            "dimensione_mb": round(p.stat().st_size / 1e6, 1), "codifica_separatore": _dialetti.get(p),
            "intestazioni": intest[:80], "esempio": [r[:80] for r in esempio],
        }
    return out


if __name__ == "__main__":
    carica_env()
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "scarica":
        print("\n".join(scarica(forza=True)))
    elif cmd == "cerca":
        print(json.dumps(cerca(" ".join(sys.argv[2:])), ensure_ascii=False, indent=1))
    elif cmd == "diagnosi":
        print(json.dumps(diagnosi(), ensure_ascii=False, indent=1)[:20000])
    else:
        print(__doc__)
