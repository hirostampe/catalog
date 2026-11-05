"""
Trova i reel/TikTok con più visualizzazioni per una nicchia, usando Apify.

Serve un token Apify (gratis su apify.com → Settings → Integrations).
Costo indicativo: circa 0,3 centesimi di dollaro per video trovato.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

QUI = Path(__file__).resolve().parent
FILE_IMPOSTAZIONI = QUI / "impostazioni.json"
FILE_ULTIMA = QUI / "ultima_ricerca.json"

ATTORE_INSTAGRAM = "apify~instagram-hashtag-scraper"
ATTORE_TIKTOK = "clockworks~tiktok-scraper"
COSTO_PER_VIDEO_USD = 0.003

# Hashtag pronti per le nicchie Hirostampe (modificabili dall'interfaccia)
NICCHIE = {
    "CrossFit": ["crossfit", "crossfititalia", "wod", "crossfitbox"],
    "Palestra": ["palestra", "gymitalia", "fitnessitalia", "personaltrainer"],
    "Danza": ["danza", "scuoladidanza", "ballerina", "hiphopdance"],
    "Padel": ["padel", "padelitalia", "padellife"],
    "Bar e locali": ["cocktailbar", "bartender", "aperitivo", "bacaro"],
    "Merch e stampa": ["tshirtpersonalizzate", "serigrafia", "ricamo", "merchandising"],
    "Ristoranti": ["ristorante", "pizzeria", "foodporn", "chef"],
    "Squadre e sport": ["calcio", "squadra", "volley", "basket"],
}


# ---------- impostazioni ----------

def leggi_impostazioni():
    try:
        return json.loads(FILE_IMPOSTAZIONI.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def salva_token(token):
    dati = leggi_impostazioni()
    dati["apify_token"] = token.strip()
    FILE_IMPOSTAZIONI.write_text(json.dumps(dati, indent=2), encoding="utf-8")
    try:
        os.chmod(FILE_IMPOSTAZIONI, 0o600)
    except OSError:
        pass


def token_apify():
    return os.environ.get("APIFY_TOKEN") or leggi_impostazioni().get("apify_token", "")


# ---------- chiamata Apify ----------

def esegui_attore(attore, input_, token, timeout=300):
    url = (f"https://api.apify.com/v2/acts/{attore}/run-sync-get-dataset-items"
           f"?timeout={timeout}&clean=true")
    req = urllib.request.Request(
        url, data=json.dumps(input_).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout + 30) as r:
            return json.loads(r.read() or b"[]")
    except urllib.error.HTTPError as e:
        corpo = e.read().decode(errors="ignore")[:300]
        if e.code == 401:
            raise RuntimeError("Token Apify non valido: controllalo nelle impostazioni.")
        if e.code == 402 or "credit" in corpo.lower() or "limit" in corpo.lower():
            raise RuntimeError("Credito Apify esaurito o limite del piano raggiunto.")
        raise RuntimeError(f"Errore Apify {e.code}: {corpo}")


# ---------- normalizzazione ----------

def _data(v):
    if not v:
        return None
    try:
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(v, tz=timezone.utc)
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def _num(*valori):
    for v in valori:
        if isinstance(v, (int, float)) and v >= 0:
            return int(v)
    return None


def da_instagram(x, termine):
    url = x.get("url") or (f"https://www.instagram.com/reel/{x['shortCode']}/" if x.get("shortCode") else None)
    return {
        "piattaforma": "Instagram",
        "url": url,
        "autore": x.get("ownerUsername") or x.get("ownerFullName"),
        "views": _num(x.get("videoPlayCount"), x.get("igPlayCount"), x.get("videoViewCount")),
        "like": _num(x.get("likesCount")),
        "commenti": _num(x.get("commentsCount")),
        "condivisioni": _num(x.get("sharesCount")),
        "follower": None,
        "durata": x.get("videoDuration"),
        "data": _data(x.get("timestamp")),
        "didascalia": (x.get("caption") or "")[:500],
        "anteprima": x.get("displayUrl"),
        "audio": ((x.get("musicInfo") or {}).get("song_name") or ""),
        "termine": termine,
        "is_video": x.get("type") == "Video" or x.get("productType") == "clips" or bool(x.get("videoUrl")),
    }


def da_tiktok(x, termine):
    autore = x.get("authorMeta") or {}
    video = x.get("videoMeta") or {}
    musica = x.get("musicMeta") or {}
    return {
        "piattaforma": "TikTok",
        "url": x.get("webVideoUrl") or x.get("submittedVideoUrl"),
        "autore": autore.get("name") or autore.get("nickName"),
        "views": _num(x.get("playCount")),
        "like": _num(x.get("diggCount")),
        "commenti": _num(x.get("commentCount")),
        "condivisioni": _num(x.get("shareCount")),
        "follower": _num(autore.get("fans")),
        "durata": video.get("duration"),
        "data": _data(x.get("createTimeISO") or x.get("createTime")),
        "didascalia": (x.get("text") or "")[:500],
        "anteprima": video.get("coverUrl") or video.get("originalCoverUrl"),
        "audio": musica.get("musicName") or "",
        "termine": termine,
        "is_video": not x.get("isSlideshow"),
    }


def _hashtag(t):
    return re.sub(r"[^\w]", "", t.lower().lstrip("#"))


# ---------- ricerca ----------

def cerca(termini, piattaforme=("Instagram", "TikTok"), per_termine=30, giorni=0,
          min_views=0, avanzamento=None):
    token = token_apify()
    if not token:
        raise RuntimeError("Manca il token Apify: inseriscilo nelle impostazioni (⚙︎).")
    passo = avanzamento or (lambda m: None)
    tags = [h for h in dict.fromkeys(_hashtag(t) for t in termini) if h]
    if not tags:
        raise RuntimeError("Scrivi almeno un hashtag o una nicchia.")

    lavori = []
    if "Instagram" in piattaforme:
        lavori.append(("Instagram", ATTORE_INSTAGRAM,
                       {"hashtags": tags, "resultsType": "reels", "resultsLimit": per_termine},
                       da_instagram, lambda x: x.get("inputUrl") or x.get("hashtag") or ""))
    if "TikTok" in piattaforme:
        lavori.append(("TikTok", ATTORE_TIKTOK,
                       {"hashtags": tags, "resultsPerPage": per_termine,
                        "shouldDownloadCovers": False, "shouldDownloadVideos": False},
                       da_tiktok, lambda x: x.get("input") or x.get("searchQuery") or ""))

    passo(f"Cerco su {' e '.join(l[0] for l in lavori)}… (1-3 minuti)")
    avvio = time.time()
    errori, risultati = [], []

    def esegui(lavoro):
        nome, attore, input_, normalizza, termine_di = lavoro
        try:
            grezzi = esegui_attore(attore, input_, token)
            return [normalizza(x, _hashtag(str(termine_di(x)).rstrip("/").split("/")[-1]))
                    for x in grezzi if isinstance(x, dict) and not x.get("error")]
        except Exception as e:
            errori.append(f"{nome}: {e}")
            return []

    with ThreadPoolExecutor(max_workers=2) as ex:
        for parte in ex.map(esegui, lavori):
            risultati.extend(parte)

    if not risultati and errori:
        raise RuntimeError(" | ".join(errori))

    return finalizza(risultati, tags, piattaforme, giorni, min_views, errori, avvio,
                     costo=round(len(risultati) * COSTO_PER_VIDEO_USD, 2))


def _mediana(valori):
    v = sorted(valori)
    return (v[len(v) // 2] + v[(len(v) - 1) // 2]) / 2 if v else 0


def finalizza(risultati, termini, piattaforme, giorni, min_views, avvisi, avvio, costo=0.0):
    """Filtra, calcola le metriche, ordina e salva l'ultima ricerca."""
    # media views per profilo, per trovare i video "fuori scala"
    per_autore = {}
    for r in risultati:
        if r.get("views") and r.get("autore"):
            per_autore.setdefault((r["piattaforma"], r["autore"]), []).append(r["views"])

    limite = datetime.now(timezone.utc).timestamp() - giorni * 86400 if giorni else None
    visti, puliti = set(), []
    for r in risultati:
        if not r["url"] or r["url"] in visti or not r["is_video"]:
            continue
        if limite and r["data"] and r["data"].timestamp() < limite:
            continue
        if min_views and (r["views"] or 0) < min_views:
            continue
        visti.add(r["url"])
        v, l, c = r["views"], r["like"] or 0, r["commenti"] or 0
        r["engagement"] = round((l + c) / v * 100, 2) if v else None
        r["moltiplicatore"] = round(v / r["follower"], 1) if v and r.get("follower") else None
        serie = per_autore.get((r["piattaforma"], r["autore"]), [])
        med = _mediana(serie)
        r["vs_media"] = round(v / med, 1) if v and med and len(serie) >= 4 else None
        r["data"] = r["data"].isoformat() if r["data"] else None
        puliti.append(r)

    puliti.sort(key=lambda r: r["views"] or 0, reverse=True)
    esito = {
        "termini": termini,
        "piattaforme": list(piattaforme),
        "quando": datetime.now().isoformat(timespec="minutes"),
        "secondi": round(time.time() - avvio),
        "trovati": len(risultati),
        "costo_stimato_usd": costo,
        "avvisi": avvisi,
        "risultati": puliti,
    }
    FILE_ULTIMA.write_text(json.dumps(esito, ensure_ascii=False), encoding="utf-8")
    return esito


def ultima_ricerca():
    try:
        return json.loads(FILE_ULTIMA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
