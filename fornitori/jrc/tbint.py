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
VALIDITA = 6 * 3600  # secondi prima di riscaricare
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
    _cache.clear()
    return locali


# ---------- lettura tabelle ----------
_cache = {}


def _leggi_testo(p):
    raw = p.read_bytes()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", "replace")


def _tabella(p):
    """Ritorna (intestazioni, righe) per csv/txt/xlsx."""
    if p in _cache:
        return _cache[p]
    suf = p.suffix.lower()
    if suf in (".csv", ".txt"):
        testo = _leggi_testo(p)
        campione = testo[:20000]
        try:
            dialetto = csv.Sniffer().sniff(campione, delimiters=";,\t|")
        except csv.Error:
            dialetto = csv.excel
            dialetto.delimiter = ";" if campione.count(";") > campione.count(",") else ","
        righe = list(csv.reader(io.StringIO(testo), dialetto))
    elif suf in (".xlsx",):
        import openpyxl
        wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
        ws = wb.worksheets[0]
        righe = [["" if v is None else str(v) for v in r] for r in ws.iter_rows(values_only=True)]
    else:
        righe = []
    righe = [r for r in righe if any(c.strip() for c in r)]
    if not righe:
        _cache[p] = ([], [])
    else:
        _cache[p] = ([c.strip() for c in righe[0]], righe[1:])
    return _cache[p]


def _file_tabellari():
    return sorted(p for p in DATI.rglob("*") if p.suffix.lower() in (".csv", ".txt", ".xlsx") and p.is_file())


def _riga_dict(intest, r):
    return {(intest[i] or f"col{i}"): v.strip() for i, v in enumerate(r) if i < len(intest) and v.strip()}


def cerca(q, massimo=20):
    """Cerca le parole in tutte le tabelle scaricate; ritorna le righe che le contengono tutte."""
    scarica()
    parole = [w.lower() for w in q.split() if w.strip()]
    out = {}
    for p in _file_tabellari():
        intest, righe = _tabella(p)
        trovate = []
        for r in righe:
            testo = " ".join(r).lower()
            if all(w in testo for w in parole):
                trovate.append(_riga_dict(intest, r))
                if len(trovate) >= massimo:
                    break
        if trovate:
            out[str(p.relative_to(DATI))] = trovate
    return {"fornitore": "TB International (Urban Classics / Build Your Brand)", "richiesta": q,
            "risultati_per_file": out,
            "nota": "Dati dai file ufficiali FTP TB International (aggiornati ogni 6 ore)."}


def cerca_completo(q, massimo=5):
    return cerca(q, massimo * 6)


def scheda(codice):
    """Tutte le righe (listino + disponibilità) che contengono il codice articolo."""
    scarica()
    cod = codice.strip().lower()
    out = {}
    for p in _file_tabellari():
        intest, righe = _tabella(p)
        trovate = [_riga_dict(intest, r) for r in righe
                   if any(c.strip().lower() == cod or c.strip().lower().startswith(cod + "-")
                          or c.strip().lower().startswith(cod + " ") for c in r)]
        if trovate:
            out[str(p.relative_to(DATI))] = trovate[:200]
    if not out:
        raise RuntimeError(f"Codice {codice} non trovato nei file TB International")
    return {"fornitore": "TB International", "codice": codice, "righe_per_file": out}


def diagnosi(_codice=""):
    """Elenco file scaricati con intestazioni e prime righe: serve a rifinire la lettura."""
    file = scarica()
    out = {"file_scaricati": file, "tabelle": {}}
    for p in _file_tabellari():
        intest, righe = _tabella(p)
        out["tabelle"][str(p.relative_to(DATI))] = {
            "dimensione_kb": p.stat().st_size // 1024, "righe": len(righe),
            "intestazioni": intest[:60], "esempio": [r[:60] for r in righe[:3]],
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
