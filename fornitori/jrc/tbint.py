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
    _dialetti.clear()
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
        dispo = [p for p in tutti if "avai" in p.name.lower()]
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


def cerca(q, massimo=20):
    """Cerca le parole nei file scaricati; ritorna le righe che le contengono tutte."""
    scarica()
    parole = [w.lower() for w in q.split() if w.strip()]
    out = _scorri(lambda r: all(w in " ".join(r).lower() for w in parole), massimo)
    return {"fornitore": "TB International (Urban Classics / Build Your Brand)", "richiesta": q,
            "risultati_per_file": out,
            "nota": "Dati dai file ufficiali FTP TB International (aggiornati ogni 6 ore)."}


def cerca_completo(q, massimo=5):
    return cerca(q, massimo * 6)


def scheda(codice):
    """Tutte le righe (listino + disponibilità) del codice articolo."""
    scarica()
    cod = codice.strip().lower()

    def ok(r):
        for c in r:
            c = c.strip().lower()
            if c == cod or c.startswith(cod + "-") or c.startswith(cod + " ") or c.startswith(cod + "_"):
                return True
        return False
    out = _scorri(ok, 200)
    if not out:
        raise RuntimeError(f"Codice {codice} non trovato nei file TB International")
    return {"fornitore": "TB International", "codice": codice, "righe_per_file": out}


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
