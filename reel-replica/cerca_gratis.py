"""
Ricerca dei video top SENZA servizi a pagamento.

- Instagram (hashtag e profili): usa il login di Instagram del tuo browser.
- TikTok (profili): legge i video pubblici del profilo con yt-dlp.
- TikTok per hashtag non è possibile gratis: per quello serve Apify.

Fa poche richieste, con una pausa tra l'una e l'altra, per non insospettire
Instagram. Non usarlo per migliaia di video al giorno.
"""
import json
import re
import time
from datetime import datetime, timezone

import yt_dlp
from yt_dlp.networking import Request

from cerca_nicchia import _data, _hashtag, _num, finalizza

IG_APP_ID = "936619743392459"   # id pubblico usato dal sito web di Instagram
PAUSA = 1.5                      # secondi tra una richiesta e l'altra


def _nome_profilo(t):
    t = t.strip()
    m = re.search(r"(?:instagram|tiktok)\.com/@?([\w.]+)", t)
    return (m.group(1) if m else t.lstrip("@")).strip("/").lower()


# ---------- Instagram ----------

class Instagram:
    def __init__(self, browser):
        opz = {"quiet": True, "no_warnings": True}
        if browser:
            opz["cookiesfrombrowser"] = (browser,)
        self.ydl = yt_dlp.YoutubeDL(opz)
        cookie = {c.name: c.value for c in self.ydl.cookiejar if "instagram.com" in c.domain}
        self.loggato = "sessionid" in cookie
        self.csrf = cookie.get("csrftoken", "")

    def get(self, url):
        time.sleep(PAUSA)
        req = Request(url, headers={
            "X-IG-App-ID": IG_APP_ID,
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRFToken": self.csrf,
            "Referer": "https://www.instagram.com/",
            "Accept": "application/json",
        })
        try:
            with self.ydl.urlopen(req) as r:
                testo = r.read().decode("utf-8", "ignore")
        except Exception as e:
            msg = str(e)
            if "401" in msg or "403" in msg or "login" in msg.lower():
                raise RuntimeError("Instagram chiede il login: accedi a instagram.com nel browser scelto.")
            if "429" in msg:
                raise RuntimeError("Instagram ha limitato le richieste: riprova tra qualche ora.")
            raise
        if testo.lstrip().startswith("<"):
            raise RuntimeError("Instagram ha risposto con una pagina di login: accedi nel browser scelto.")
        return json.loads(testo)

    def hashtag(self, tag, quanti):
        dati = self.get(f"https://www.instagram.com/api/v1/tags/web_info/?tag_name={tag}")
        return [media_instagram(m, tag) for m in _trova_media(dati)][:quanti]

    def profilo(self, nome, quanti):
        info = self.get(f"https://www.instagram.com/api/v1/users/web_profile_info/?username={nome}")
        utente = (info.get("data") or {}).get("user") or {}
        if not utente:
            raise RuntimeError(f"profilo Instagram @{nome} non trovato")
        follower = (utente.get("edge_followed_by") or {}).get("count")
        risultati = []
        # con il login: feed completo (più video, con le views dei reel)
        if self.loggato and utente.get("id"):
            max_id = ""
            while len(risultati) < quanti:
                url = f"https://www.instagram.com/api/v1/feed/user/{utente['id']}/?count=33"
                pagina = self.get(url + (f"&max_id={max_id}" if max_id else ""))
                risultati += [media_instagram(m, "@" + nome) for m in pagina.get("items") or []]
                max_id = pagina.get("next_max_id")
                if not pagina.get("more_available") or not max_id:
                    break
        # senza login: solo gli ultimi 12 post pubblici
        if not risultati:
            for e in (utente.get("edge_owner_to_timeline_media") or {}).get("edges") or []:
                risultati.append(nodo_instagram(e.get("node") or {}, nome, "@" + nome))
        for r in risultati:
            r["follower"] = follower
        return risultati[:quanti]


def _trova_media(obj, visti=None):
    """Cerca ricorsivamente gli oggetti 'post' nella risposta di Instagram."""
    visti = set() if visti is None else visti
    if isinstance(obj, dict):
        if isinstance(obj.get("code"), str) and "media_type" in obj and obj["code"] not in visti:
            visti.add(obj["code"])
            yield obj
            return
        for v in obj.values():
            yield from _trova_media(v, visti)
    elif isinstance(obj, list):
        for v in obj:
            yield from _trova_media(v, visti)


def media_instagram(m, termine):
    immagini = ((m.get("image_versions2") or {}).get("candidates") or [{}])
    return {
        "piattaforma": "Instagram",
        "url": f"https://www.instagram.com/reel/{m['code']}/",
        "autore": (m.get("user") or {}).get("username"),
        "views": _num(m.get("play_count"), m.get("ig_play_count"), m.get("view_count")),
        "like": _num(m.get("like_count")),
        "commenti": _num(m.get("comment_count")),
        "condivisioni": None,
        "follower": None,
        "durata": m.get("video_duration"),
        "data": _data(m.get("taken_at")),
        "didascalia": ((m.get("caption") or {}).get("text") or "")[:500],
        "anteprima": immagini[0].get("url"),
        "audio": "",
        "termine": termine,
        "is_video": m.get("media_type") == 2,
    }


def nodo_instagram(n, nome, termine):
    didascalia = ((n.get("edge_media_to_caption") or {}).get("edges") or [{}])[0]
    return {
        "piattaforma": "Instagram",
        "url": f"https://www.instagram.com/reel/{n.get('shortcode')}/" if n.get("shortcode") else None,
        "autore": nome,
        "views": _num(n.get("video_view_count"), n.get("video_play_count")),
        "like": _num((n.get("edge_liked_by") or n.get("edge_media_preview_like") or {}).get("count")),
        "commenti": _num((n.get("edge_media_to_comment") or {}).get("count")),
        "condivisioni": None,
        "follower": None,
        "durata": n.get("video_duration"),
        "data": _data(n.get("taken_at_timestamp")),
        "didascalia": ((didascalia.get("node") or {}).get("text") or "")[:500],
        "anteprima": n.get("display_url") or n.get("thumbnail_src"),
        "audio": "",
        "termine": termine,
        "is_video": bool(n.get("is_video")),
    }


# ---------- TikTok ----------

def profilo_tiktok(nome, quanti, browser=None):
    opz = {"quiet": True, "no_warnings": True, "extract_flat": "in_playlist",
           "playlistend": quanti}
    if browser:
        opz["cookiesfrombrowser"] = (browser,)
    with yt_dlp.YoutubeDL(opz) as ydl:
        info = ydl.extract_info(f"https://www.tiktok.com/@{nome}", download=False)
    risultati = []
    for e in (info or {}).get("entries") or []:
        miniature = e.get("thumbnails") or [{}]
        risultati.append({
            "piattaforma": "TikTok",
            "url": e.get("webpage_url") or e.get("url"),
            "autore": e.get("uploader") or nome,
            "views": _num(e.get("view_count")),
            "like": _num(e.get("like_count")),
            "commenti": _num(e.get("comment_count")),
            "condivisioni": _num(e.get("repost_count")),
            "follower": _num(e.get("channel_follower_count")),
            "durata": e.get("duration"),
            "data": _data(e.get("timestamp")),
            "didascalia": (e.get("description") or e.get("title") or "")[:500],
            "anteprima": e.get("thumbnail") or miniature[-1].get("url"),
            "audio": e.get("track") or "",
            "termine": "@" + nome,
            "is_video": True,
        })
    return risultati


# ---------- ricerca ----------

def cerca(hashtag_ig=(), profili_ig=(), profili_tt=(), per_fonte=30, giorni=0,
          min_views=0, browser="chrome", avanzamento=None):
    passo = avanzamento or (lambda m: None)
    tags = [h for h in dict.fromkeys(_hashtag(t) for t in hashtag_ig) if h]
    p_ig = [p for p in dict.fromkeys(_nome_profilo(t) for t in profili_ig) if p]
    p_tt = [p for p in dict.fromkeys(_nome_profilo(t) for t in profili_tt) if p]
    if not (tags or p_ig or p_tt):
        raise RuntimeError("Scrivi almeno un hashtag o un profilo.")

    avvio, risultati, avvisi = time.time(), [], []
    ig = None
    if tags or p_ig:
        passo(f"Leggo il login di Instagram da {browser}…")
        ig = Instagram(browser)
        if not ig.loggato:
            msg = (f"Non risulti collegato a Instagram su {browser}: "
                   "apri instagram.com in quel browser e accedi.")
            if tags:
                avvisi.append(msg + " (gli hashtag Instagram richiedono il login)")
                tags = []
            else:
                avvisi.append(msg + " Leggo solo gli ultimi 12 post dei profili.")

    fonti = ([("Instagram #" + t, lambda t=t: ig.hashtag(t, per_fonte)) for t in tags]
             + [("Instagram @" + p, lambda p=p: ig.profilo(p, per_fonte)) for p in p_ig]
             + [("TikTok @" + p, lambda p=p: profilo_tiktok(p, per_fonte, browser)) for p in p_tt])

    for i, (nome, fn) in enumerate(fonti, 1):
        passo(f"{i}/{len(fonti)} · {nome}…")
        try:
            risultati += fn()
        except Exception as e:
            avvisi.append(f"{nome}: {str(e)[:160]}")

    if not risultati and avvisi:
        raise RuntimeError(" | ".join(avvisi))

    piattaforme = sorted({r["piattaforma"] for r in risultati}) or ["Instagram", "TikTok"]
    termini = tags + ["@" + p for p in p_ig + p_tt]
    return finalizza(risultati, termini, piattaforme, giorni, min_views, avvisi, avvio)
