#!/usr/bin/env python3
"""
Scarica un reel Instagram o un video TikTok e prepara un "pacchetto analisi"
da caricare su Claude, per rifare la stessa struttura con le tue clip.

Uso:
    python scarica_reel.py URL [URL ...]
    python scarica_reel.py --file lista_link.txt
    python scarica_reel.py URL --cookies-from-browser chrome   # se Instagram chiede il login

Per ogni video crea una cartella in riferimenti/ con:
    video.mp4           il video originale (solo come riferimento)
    frame_XX.jpg        un fotogramma per ogni inquadratura
    provino.jpg         tutti i fotogrammi in un'unica immagine
    analisi.json        dati grezzi (durata, tagli, didascalia, numeri)
    brief.md            scaletta inquadratura per inquadratura + prompt per Claude
    pacchetto.zip       tutto quello che serve da caricare su Claude (senza il video)
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

try:
    import yt_dlp
except ImportError:
    sys.exit("Manca yt-dlp. Installa con:  pip install -r requirements.txt")

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None

CARTELLA_BASE = Path(__file__).resolve().parent / "riferimenti"
SOGLIA_TAGLIO = 0.30   # sensibilità rilevamento tagli (più bassa = più tagli)
DURATA_MIN_SCENA = 0.4  # secondi: tagli più vicini vengono uniti


def controlla_ffmpeg():
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"Manca {tool}. Installalo (Mac: brew install ffmpeg | Windows: winget install ffmpeg).")


def nome_cartella(info):
    piattaforma = (info.get("extractor_key") or "video").lower()
    autore = info.get("uploader_id") or info.get("uploader") or "autore"
    vid = info.get("id") or "x"
    pulito = re.sub(r"[^a-zA-Z0-9_.-]+", "_", f"{piattaforma}_{autore}_{vid}")
    return pulito[:80]


def scarica(url, cookies_browser=None, cookies_file=None, avanzamento=None):
    def hook(d):
        if avanzamento and d.get("status") == "downloading":
            tot = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if tot:
                avanzamento(f"Download {d.get('downloaded_bytes', 0) * 100 // tot}%")

    opzioni = {
        "progress_hooks": [hook],
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "outtmpl": str(CARTELLA_BASE / "_tmp" / "%(id)s.%(ext)s"),
    }
    if cookies_browser:
        opzioni["cookiesfrombrowser"] = (cookies_browser,)
    if cookies_file:
        opzioni["cookiefile"] = cookies_file

    with yt_dlp.YoutubeDL(opzioni) as ydl:
        info = ydl.extract_info(url, download=True)
        if info.get("_type") == "playlist" and info.get("entries"):
            info = info["entries"][0]
        file_scaricato = Path(ydl.prepare_filename(info)).with_suffix(".mp4")

    cartella = CARTELLA_BASE / nome_cartella(info)
    cartella.mkdir(parents=True, exist_ok=True)
    destinazione = cartella / "video.mp4"
    shutil.move(str(file_scaricato), destinazione)
    return info, cartella, destinazione


def durata_video(video):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(video)],
        capture_output=True, text=True).stdout.strip()
    return float(out or 0)


def trova_tagli(video, durata):
    """Usa il filtro scene di ffmpeg per trovare i cambi di inquadratura."""
    cmd = ["ffmpeg", "-hide_banner", "-i", str(video),
           "-vf", f"select='gt(scene,{SOGLIA_TAGLIO})',showinfo",
           "-an", "-f", "null", "-"]
    log = subprocess.run(cmd, capture_output=True, text=True).stderr
    tempi = [float(t) for t in re.findall(r"pts_time:([0-9.]+)", log)]

    tagli = [0.0]
    for t in tempi:
        if t - tagli[-1] >= DURATA_MIN_SCENA and durata - t >= DURATA_MIN_SCENA:
            tagli.append(t)
    tagli.append(durata)
    return [(round(a, 2), round(b, 2)) for a, b in zip(tagli, tagli[1:])]


def estrai_frame(video, scene, cartella):
    frames = []
    for i, (inizio, fine) in enumerate(scene, 1):
        t = inizio + (fine - inizio) / 2
        out = cartella / f"frame_{i:02d}.jpg"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}",
                        "-i", str(video), "-frames:v", "1", "-vf", "scale=360:-2",
                        "-q:v", "3", str(out)], check=False)
        if out.exists():
            frames.append(out)
    return frames


def crea_provino(frames, scene, cartella):
    if not Image or not frames:
        return None
    imgs = [Image.open(f) for f in frames]
    w, h = imgs[0].size
    colonne = min(5, len(imgs))
    righe = (len(imgs) + colonne - 1) // colonne
    foglio = Image.new("RGB", (colonne * w, righe * (h + 28)), "white")
    disegno = ImageDraw.Draw(foglio)
    for i, (img, (a, b)) in enumerate(zip(imgs, scene)):
        x, y = (i % colonne) * w, (i // colonne) * (h + 28)
        foglio.paste(img.resize((w, h)), (x, y + 28))
        disegno.text((x + 6, y + 7), f"#{i+1}  {a:.1f}s - {b:.1f}s  ({b-a:.1f}s)", fill="black")
    out = cartella / "provino.jpg"
    foglio.save(out, quality=85)
    return out


def ha_audio(video):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a",
                          "-show_entries", "stream=index", "-of", "csv=p=0", str(video)],
                         capture_output=True, text=True).stdout.strip()
    return bool(out)


def scrivi_brief(info, scene, durata, cartella, audio):
    didascalia = (info.get("description") or "").strip()
    numeri = {k: info.get(k) for k in ("view_count", "like_count", "comment_count", "repost_count")
              if info.get(k) is not None}
    media = sum(b - a for a, b in scene) / len(scene) if scene else 0

    righe_scene = "\n".join(
        f"| {i} | {a:.1f}s | {b:.1f}s | {b-a:.1f}s | frame_{i:02d}.jpg | |"
        for i, (a, b) in enumerate(scene, 1))

    brief = f"""# Brief reel di riferimento

- **Fonte:** {info.get('webpage_url', '')}
- **Autore:** {info.get('uploader') or info.get('uploader_id') or '-'}
- **Durata:** {durata:.1f}s  |  **Inquadrature:** {len(scene)}  |  **Durata media inquadratura:** {media:.1f}s
- **Audio presente:** {'sì' if audio else 'no'}
- **Numeri:** {', '.join(f'{k.replace("_count","")}: {v:,}' for k, v in numeri.items()) or '-'}

## Didascalia originale
{didascalia or '-'}

## Scaletta inquadrature
| # | Inizio | Fine | Durata | Frame | Cosa succede (da compilare da Claude) |
|---|---|---|---|---|---|
{righe_scene}

---

## Prompt da incollare su Claude

Ti allego il pacchetto di un reel che funziona (provino.jpg, frame_XX.jpg, brief.md)
e le mie clip grezze. Voglio un reel Hirostampe con la **stessa struttura**, fatto
con le mie clip e i miei contenuti (non copiare testi, grafiche o audio originali).

1. Analizza il riferimento: hook dei primi 2 secondi, ritmo dei tagli, tipo di
   inquadrature, testi a schermo, call to action finale. Compila la colonna
   "Cosa succede" della scaletta.
2. Spiegami in 3 righe perché secondo te funziona.
3. Abbina a ogni inquadratura una delle mie clip (indica nome file e secondo
   di inizio/fine da usare) mantenendo le stesse durate.
4. Scrivimi i testi a schermo e la didascalia adattati a Hirostampe.
5. Poi monta il reel nel mio stile (skill montaggio reel Hirostampe).
"""
    (cartella / "brief.md").write_text(brief, encoding="utf-8")

    dati = {
        "url": info.get("webpage_url"),
        "piattaforma": info.get("extractor_key"),
        "autore": info.get("uploader") or info.get("uploader_id"),
        "durata_s": round(durata, 2),
        "inquadrature": [{"n": i, "inizio": a, "fine": b, "durata": round(b - a, 2)}
                         for i, (a, b) in enumerate(scene, 1)],
        "didascalia": didascalia,
        "numeri": numeri,
    }
    (cartella / "analisi.json").write_text(json.dumps(dati, ensure_ascii=False, indent=2),
                                           encoding="utf-8")


def crea_zip(cartella, includi_video):
    out = cartella / "pacchetto.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(cartella.iterdir()):
            if f.name == out.name or (f.name == "video.mp4" and not includi_video):
                continue
            z.write(f, f.name)
    return out


def elabora(url, cookies_browser=None, cookies=None, con_video=False, avanzamento=None):
    """Scarica e analizza un video. Restituisce la cartella del pacchetto."""
    passo = avanzamento or (lambda m: None)
    passo("Download in corso…")
    info, cartella, video = scarica(url, cookies_browser, cookies, avanzamento)
    passo("Cerco i tagli…")
    durata = durata_video(video)
    scene = trova_tagli(video, durata)
    passo("Estraggo i fotogrammi…")
    frames = estrai_frame(video, scene, cartella)
    crea_provino(frames, scene, cartella)
    passo("Preparo il pacchetto…")
    scrivi_brief(info, scene, durata, cartella, ha_audio(video))
    crea_zip(cartella, con_video)
    return cartella


def suggerimento_errore(url, msg):
    m = msg.lower()
    if "instagram" in url and ("login" in m or "cookie" in m or "rate" in m):
        return "Instagram chiede il login: attiva 'Usa il login del browser'."
    if "private" in m or "privat" in m:
        return "Il video è privato o non accessibile."
    if "unsupported url" in m:
        return "Link non riconosciuto: copia il link del singolo reel/video."
    return "Prova ad aggiornare yt-dlp (pip install -U yt-dlp) o riprova più tardi."


def main():
    p = argparse.ArgumentParser(description="Scarica reel/TikTok e prepara il pacchetto per Claude.")
    p.add_argument("url", nargs="*", help="link Instagram o TikTok")
    p.add_argument("--file", help="file di testo con un link per riga")
    p.add_argument("--cookies-from-browser", metavar="BROWSER",
                   help="usa il login del browser (chrome, safari, firefox, edge) se Instagram lo richiede")
    p.add_argument("--cookies", metavar="FILE", help="file cookies.txt alternativo")
    p.add_argument("--con-video", action="store_true",
                   help="includi anche video.mp4 nello zip (più pesante)")
    args = p.parse_args()

    urls = list(args.url)
    if args.file:
        urls += [r.strip() for r in Path(args.file).read_text().splitlines()
                 if r.strip() and not r.startswith("#")]
    if not urls:
        p.error("serve almeno un link (o --file)")

    controlla_ffmpeg()
    CARTELLA_BASE.mkdir(exist_ok=True)
    errori = 0
    for u in urls:
        print(f"\n▶ {u}")
        try:
            cartella = elabora(u, args.cookies_from_browser, args.cookies, args.con_video)
            print(f"  ✓ da caricare su Claude: {cartella / 'pacchetto.zip'}")
        except Exception as e:  # continua con gli altri link
            errori += 1
            print(f"  ✗ errore: {str(e)[:300]}")
            print(f"    → {suggerimento_errore(u, str(e))}")
    shutil.rmtree(CARTELLA_BASE / "_tmp", ignore_errors=True)
    print(f"\nFatto: {len(urls) - errori}/{len(urls)} video pronti in {CARTELLA_BASE}")


if __name__ == "__main__":
    main()
