"""
Funzioni comuni della ricerca "Top del settore": categorie di hashtag,
normalizzazione dei dati, metriche e classifica.
"""
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

QUI = Path(__file__).resolve().parent
FILE_ULTIMA = QUI / "ultima_ricerca.json"

# Hashtag del settore Hirostampe (italiani + internazionali, per avere più esempi)
CATEGORIE = {
    "Stampa t-shirt": ["tshirtpersonalizzate", "magliettepersonalizzate", "stampamagliette", "tshirtprinting", "customtshirts"],
    "Serigrafia": ["serigrafia", "screenprinting", "screenprint", "screenprintinglife"],
    "DTF e transfer": ["dtf", "dtfprinting", "dtftransfers", "stampadtf"],
    "Ricamo": ["ricamo", "ricamopersonalizzato", "embroidery", "embroiderybusiness", "customembroidery"],
    "Merch aziendale": ["merchandising", "merchaziendale", "custommerch", "brandedmerch", "gadgetpersonalizzati"],
    "Patch": ["patchpersonalizzate", "custompatches", "embroideredpatches", "patch"],
    "Felpe e hoodie": ["felpepersonalizzate", "customhoodies", "hoodieprinting"],
    "Dietro le quinte": ["printshop", "printshoplife", "laboratoriodistampa", "smallbusinessitalia"],
    "Lancio brand": ["clothingbrand", "streetwearbrand", "brandabbigliamento", "startingaclothingbrand"],
}


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
