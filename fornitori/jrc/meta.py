#!/usr/bin/env python3
"""Meta (Facebook/Instagram) per Hirostampe tramite le API ufficiali Graph/Marketing (gratuite).

Nel .env:
  META_TOKEN=...            token di un "utente di sistema" del Business Manager
  META_AD_ACCOUNT=900229774963446
  IG_USER_ID=17841405512136152
  META_API_VERSION=v23.0    (facoltativo)

Uso:
  python3 meta.py campagne last_30d
  python3 meta.py post 30
  python3 meta.py competitor nomeprofilo
  python3 meta.py verifica
"""
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

from jrc import carica_env

AZIONI = {  # tipi di azione Meta -> nome leggibile
    "lead": "lead",
    "onsite_conversion.lead_grouped": "lead_modulo",
    "onsite_conversion.messaging_conversation_started_7d": "conversazioni_avviate",
    "onsite_conversion.total_messaging_connection": "nuovi_contatti_messaggi",
    "link_click": "clic_link",
    "landing_page_view": "visite_pagina",
    "offsite_conversion.fb_pixel_purchase": "acquisti",
    "offsite_conversion.fb_pixel_lead": "lead_sito",
    "post_engagement": "interazioni",
    "video_view": "visualizzazioni_video_3s",
}


def _cfg():
    tok = os.environ.get("META_TOKEN")
    if not tok:
        raise RuntimeError("Manca META_TOKEN nel file .env (vedi guida Meta)")
    return tok, os.environ.get("META_API_VERSION", "v23.0")


def _get(percorso, **params):
    tok, ver = _cfg()
    params["access_token"] = tok
    url = percorso if percorso.startswith("http") else f"https://graph.facebook.com/{ver}/{percorso.lstrip('/')}"
    for tentativo in range(3):
        r = requests.get(url, params=params, timeout=60)
        dati = r.json() if r.headers.get("content-type", "").startswith(("application/json", "text/javascript")) else {}
        if r.status_code == 200:
            return dati
        err = dati.get("error", {})
        if err.get("code") in (4, 17, 32, 613) and tentativo < 2:  # limiti di frequenza
            time.sleep(20)
            continue
        raise RuntimeError(f"Meta API: {err.get('message', r.text[:300])} (codice {err.get('code')})")


def _tutte(percorso, massimo=500, **params):
    out, dati = [], _get(percorso, **params)
    while True:
        out += dati.get("data", [])
        nxt = dati.get("paging", {}).get("next")
        if not nxt or len(out) >= massimo:
            return out[:massimo]
        dati = requests.get(nxt, timeout=60).json()


def _azioni(lista):
    out = {}
    for a in lista or []:
        nome = AZIONI.get(a.get("action_type"))
        if nome:
            out[nome] = float(a.get("value", 0))
    return out


# ---------------- Meta Ads ----------------
def campagne(periodo="last_30d", livello="campaign"):
    """Rendimento per campagna (o 'adset' / 'ad'). periodo: today, yesterday, last_7d, last_14d,
    last_30d, last_90d, this_month, last_month, maximum."""
    acc = os.environ.get("META_AD_ACCOUNT", "").replace("act_", "")
    if not acc:
        raise RuntimeError("Manca META_AD_ACCOUNT nel .env")
    livello = livello if livello in ("campaign", "adset", "ad") else "campaign"
    campi = ["campaign_name", "objective", "spend", "impressions", "reach", "frequency", "inline_link_clicks",
             "ctr", "cpm", "actions", "cost_per_action_type"]
    if livello in ("adset", "ad"):
        campi.insert(1, "adset_name")
    if livello == "ad":
        campi.insert(2, "ad_name")
    righe = _tutte(f"act_{acc}/insights", level=livello, date_preset=periodo, fields=",".join(campi), limit=200)
    out = []
    for r in righe:
        risultati = _azioni(r.get("actions"))
        costi = {f"costo_per_{k}": v for k, v in _azioni(r.get("cost_per_action_type")).items()}
        voce = {k: r.get(k) for k in ("campaign_name", "adset_name", "ad_name", "objective") if r.get(k)}
        voce.update({
            "spesa_eur": float(r.get("spend", 0)), "impression": int(r.get("impressions", 0)),
            "copertura": int(r.get("reach", 0)), "frequenza": round(float(r.get("frequency", 0)), 2),
            "clic_link": int(r.get("inline_link_clicks", 0)), "ctr_%": round(float(r.get("ctr", 0)), 2),
            "cpm_eur": round(float(r.get("cpm", 0)), 2), "risultati": risultati,
            "costi": {k: round(v, 2) for k, v in costi.items()},
        })
        out.append(voce)
    out.sort(key=lambda x: x["spesa_eur"], reverse=True)
    tot = sum(x["spesa_eur"] for x in out)
    return {"periodo": periodo, "livello": livello, "spesa_totale_eur": round(tot, 2), "righe": out}


# ---------------- Instagram: i tuoi contenuti ----------------
METRICHE_REEL = ["reach", "views", "saved", "shares", "total_interactions", "ig_reels_avg_watch_time"]
METRICHE_POST = ["reach", "views", "saved", "shares", "total_interactions"]


def _insights_media(mid, tipo):
    metriche = METRICHE_REEL if tipo == "REELS" else METRICHE_POST
    while metriche:
        try:
            dati = _get(f"{mid}/insights", metric=",".join(metriche))
            return {d["name"]: (d.get("values") or [{}])[0].get("value") for d in dati.get("data", [])}
        except RuntimeError as e:
            # se una metrica non è supportata la tolgo e riprovo
            tolta = next((m for m in metriche if m in str(e)), metriche[-1])
            metriche = [m for m in metriche if m != tolta]
    return {}


def post(giorni=30, massimo=40):
    """I tuoi post e reel degli ultimi `giorni` con copertura, views, salvataggi, condivisioni."""
    ig = os.environ.get("IG_USER_ID")
    if not ig:
        raise RuntimeError("Manca IG_USER_ID nel .env")
    limite = datetime.now(timezone.utc) - timedelta(days=int(giorni))
    media = _tutte(f"{ig}/media", massimo=massimo, limit=50,
                   fields="id,caption,media_type,media_product_type,permalink,timestamp,like_count,comments_count")
    out = []
    for m in media:
        quando = datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
        if quando < limite:
            break
        voce = {"data": m["timestamp"][:10], "tipo": m.get("media_product_type") or m.get("media_type"),
                "link": m.get("permalink"), "testo": (m.get("caption") or "")[:150],
                "like": m.get("like_count"), "commenti": m.get("comments_count")}
        voce.update(_insights_media(m["id"], m.get("media_product_type")))
        if voce.get("ig_reels_avg_watch_time"):
            voce["durata_media_visione_s"] = round(voce.pop("ig_reels_avg_watch_time") / 1000, 1)
        out.append(voce)
    out.sort(key=lambda x: x.get("views") or x.get("reach") or 0, reverse=True)
    return {"profilo": ig, "giorni": giorni, "contenuti": out}


# ---------------- Instagram: competitor ----------------
def competitor(username, quanti=25):
    """Profilo e ultimi contenuti di un account Instagram business/creator (Business Discovery)."""
    ig = os.environ.get("IG_USER_ID")
    u = username.strip().lstrip("@").split("/")[-1] or username
    campi_media = "caption,media_type,media_product_type,permalink,timestamp,like_count,comments_count"
    for extra in (",view_count", ""):
        try:
            dati = _get(ig, fields=(f"business_discovery.username({u}){{username,name,biography,website,"
                                    f"followers_count,follows_count,media_count,"
                                    f"media.limit({int(quanti)}){{{campi_media}{extra}}}}}"))
            break
        except RuntimeError as e:
            if extra and "view_count" in str(e):
                continue
            if "business" in str(e).lower() or "110" in str(e):
                raise RuntimeError(f"@{u}: profilo non trovato o non è un account business/creator "
                                   "(Meta mostra solo quelli)") from e
            raise
    bd = dati["business_discovery"]
    media = bd.get("media", {}).get("data", [])
    follower = bd.get("followers_count") or 1
    contenuti = []
    for m in media:
        inter = (m.get("like_count") or 0) + (m.get("comments_count") or 0)
        contenuti.append({"data": m["timestamp"][:10], "tipo": m.get("media_product_type") or m.get("media_type"),
                          "link": m.get("permalink"), "testo": (m.get("caption") or "")[:200],
                          "like": m.get("like_count"), "commenti": m.get("comments_count"),
                          "views": m.get("view_count"),
                          "engagement_%": round(100 * inter / follower, 2)})
    date = sorted(datetime.strptime(c["data"], "%Y-%m-%d") for c in contenuti)
    freq = None
    if len(date) > 1:
        freq = round(len(date) / max(1, (date[-1] - date[0]).days / 7), 1)
    return {"profilo": bd.get("username"), "nome": bd.get("name"), "bio": bd.get("biography"),
            "sito": bd.get("website"), "follower": bd.get("followers_count"), "post_totali": bd.get("media_count"),
            "post_a_settimana": freq,
            "migliori": sorted(contenuti, key=lambda c: c["engagement_%"], reverse=True)[:8],
            "tutti": contenuti}


def verifica():
    """Controlla token e permessi."""
    tok, ver = _cfg()
    io_ = _get("me", fields="id,name")
    out = {"token_di": io_.get("name"), "versione_api": ver}
    try:
        perms = _get("me/permissions").get("data", [])
        out["permessi"] = sorted(p["permission"] for p in perms if p.get("status") == "granted")
    except RuntimeError as e:
        out["permessi"] = str(e)
    for nome, fn in (("ads", lambda: campagne("last_7d")), ("instagram", lambda: post(7, 3))):
        try:
            r = fn()
            out[nome] = "OK"
        except Exception as e:  # noqa
            out[nome] = f"ERRORE: {e}"
    return out


if __name__ == "__main__":
    carica_env()
    a = sys.argv[1:] or [""]
    if a[0] == "campagne":
        print(json.dumps(campagne(*(a[1:3] or ["last_30d"])), ensure_ascii=False, indent=1))
    elif a[0] == "post":
        print(json.dumps(post(int(a[1]) if len(a) > 1 else 30), ensure_ascii=False, indent=1))
    elif a[0] == "competitor" and len(a) > 1:
        print(json.dumps(competitor(a[1]), ensure_ascii=False, indent=1))
    elif a[0] == "verifica":
        print(json.dumps(verifica(), ensure_ascii=False, indent=1))
    else:
        print(__doc__)
