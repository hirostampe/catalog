#!/usr/bin/env python3
"""Connettore Claude (MCP) per il bot James Ross.

Gira sul server, in ascolto solo in locale (127.0.0.1:8765).
Caddy lo pubblica in HTTPS all'indirizzo segreto:
    https://<dominio>/<JRC_MCP_SEGRETO>/mcp
Quell'indirizzo si aggiunge in Claude: Impostazioni > Connettori > Aggiungi connettore personalizzato.
"""
import os
import threading

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

import iwear
import meta
import tbint
import jrc

jrc.carica_env()
SEGRETO = os.environ.get("JRC_MCP_SEGRETO", "").strip("/")
if len(SEGRETO) < 20:
    raise SystemExit("Manca JRC_MCP_SEGRETO nel .env (almeno 20 caratteri casuali)")

mcp = FastMCP(
    "Fornitori Hirostampe",
    instructions=(
        "Cerca articoli, varianti, prezzi rivenditore e giacenze sui siti dei fornitori di Hirostampe: "
        "James Ross (JRC) e Innovative Wear, col login di Hirostampe. Prezzi James Ross in euro IVA esclusa: "
        "'scatola' = cartone intero, 'sfuso' = quantità sciolte, '1 pezzo' = singolo capo."
    ),
    host="127.0.0.1",
    port=int(os.environ.get("JRC_MCP_PORTA", "8765")),
    streamable_http_path=f"/{SEGRETO}/mcp",
    stateless_http=True,
    json_response=True,
    # dietro Caddy l'Host è il dominio pubblico: il controllo lo fa il percorso segreto
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

_bot = jrc.JRC()
_lock = threading.Lock()  # una richiesta alla volta verso il sito


def _in_coda(fn, *args):
    with _lock:
        return fn(*args)


@mcp.tool()
async def cerca_james_ross(richiesta: str, max_articoli: int = 5) -> dict:
    """Cerca articoli sul sito James Ross e restituisce per ciascuno: nome, codice, colori
    disponibili (con codice variante), taglie, prezzi (scatola/sfuso/1 pezzo), pezzi per
    cartone, grammatura e giacenze per taglia.

    richiesta: parole chiave come le scriveresti nella ricerca del sito, es. "felpa",
    "polo", "giubbotto monaco", "felpa navy" (se c'è un colore apre quella variante).
    Il sito cerca per nome articolo: usa parole semplici (tipo di capo o nome modello).
    max_articoli: quante schede aprire (1-10). Ogni scheda richiede ~3 secondi.
    """
    n = max(1, min(int(max_articoli), 10))
    return await anyio.to_thread.run_sync(_in_coda, _bot.cerca_completo, richiesta, n)


@mcp.tool()
async def articolo_james_ross(codice: str) -> dict:
    """Scheda completa di un articolo James Ross dal codice variante (es. "987690"):
    prezzi, colori, taglie e giacenze per taglia aggiornate in tempo reale.
    Per un altro colore usa il codice di quella variante (lista 'colori' della scheda).
    """
    return await anyio.to_thread.run_sync(_in_coda, _bot.articolo_da_codice, codice.strip())


_iw = iwear.IWear()

# Fornitori disponibili: per aggiungerne uno basta registrarlo qui (i comandi restano gli stessi)
FORNITORI = {
    "james_ross": {"nome": "James Ross (JRC)", "cerca": _bot.cerca_completo,
                   "scheda": _bot.articolo_da_codice, "diagnosi": _bot.diagnosi},
    "innovative_wear": {"nome": "Innovative Wear (Gildan, Fruit, Russell, Just Hoods, Stedman, Premier…)",
                        "cerca": _iw.cerca_completo, "scheda": _iw.articolo, "diagnosi": _iw.diagnosi},
    "urban_classics": {"nome": "TB International: Urban Classics, Build Your Brand, Flexfit (file ufficiali FTP)",
                       "cerca": tbint.cerca_completo, "scheda": tbint.scheda, "diagnosi": tbint.diagnosi},
}


def _scegli(fornitore):
    f = (fornitore or "").strip().lower().replace(" ", "_")
    if f not in FORNITORI:
        raise ValueError(f"Fornitore '{fornitore}' sconosciuto. Disponibili: {', '.join(FORNITORI)}")
    return FORNITORI[f]


@mcp.tool()
async def elenco_fornitori() -> dict:
    """Elenco dei fornitori collegati (chiave da usare negli altri comandi + descrizione)."""
    return {k: v["nome"] for k, v in FORNITORI.items()}


@mcp.tool()
async def cerca_articoli(richiesta: str, fornitore: str = "tutti", max_articoli: int = 3) -> dict:
    """Cerca articoli sui siti dei fornitori di Hirostampe col login rivenditore e restituisce
    per ogni articolo: nome, codice, colori, taglie, prezzi e disponibilità/giacenze.

    richiesta: parole semplici come nella ricerca del sito ("felpa", "polo navy", "gildan 18500")
               o un codice articolo.
    fornitore: "tutti" (default) oppure una chiave di elenco_fornitori, es. "james_ross",
               "innovative_wear".
    max_articoli: schede da aprire PER fornitore (1-10, ~3 secondi l'una).
    """
    n = max(1, min(int(max_articoli), 10))
    scelti = FORNITORI if (fornitore or "tutti").lower() == "tutti" else {fornitore: _scegli(fornitore)}
    out = {}
    for chiave, f in scelti.items():
        try:
            out[chiave] = await anyio.to_thread.run_sync(_in_coda, f["cerca"], richiesta, n)
        except Exception as e:  # un fornitore in errore non blocca gli altri
            out[chiave] = {"errore": str(e)}
    return out


@mcp.tool()
async def scheda_articolo(fornitore: str, codice: str) -> dict:
    """Scheda completa e aggiornata di un articolo (prezzi, colori, taglie, disponibilità).
    fornitore: chiave di elenco_fornitori ("james_ross", "innovative_wear"); codice: es. "987690", "JC052"."""
    f = _scegli(fornitore)
    return await anyio.to_thread.run_sync(_in_coda, f["scheda"], codice.strip())


@mcp.tool()
async def prezzi_quantita_innovative_wear(variante: str) -> str:
    """Scaglioni di prezzo per quantità di una variante Innovative Wear (id 'variante' della scheda)."""
    return await anyio.to_thread.run_sync(_in_coda, _iw.prezzi_quantita, variante.strip())


@mcp.tool()
async def diagnosi_fornitore(fornitore: str, codice: str) -> dict:
    """Solo per manutenzione: HTML della scheda (da loggato) per correggere la lettura dei dati.
    Non usarlo per le ricerche."""
    f = _scegli(fornitore)
    return await anyio.to_thread.run_sync(_in_coda, f["diagnosi"], codice.strip())


@mcp.tool()
async def meta_ads_campagne(periodo: str = "last_30d", livello: str = "campaign") -> dict:
    """Rendimento delle campagne Meta Ads (Facebook/Instagram) di Hirostampe dalle API ufficiali:
    spesa, copertura, frequenza, clic, CTR, CPM, risultati (lead, conversazioni avviate, acquisti…)
    e costo per risultato.
    periodo: today, yesterday, last_7d, last_14d, last_30d, last_90d, this_month, last_month, maximum.
    livello: "campaign" (default), "adset" o "ad" (per vedere i singoli annunci migliori/peggiori)."""
    return await anyio.to_thread.run_sync(meta.campagne, periodo, livello)


@mcp.tool()
async def instagram_miei_contenuti(giorni: int = 30) -> dict:
    """Post e reel di @hirostampe_venezia degli ultimi `giorni`, ordinati per views: copertura,
    views, like, commenti, salvataggi, condivisioni, durata media di visione dei reel."""
    return await anyio.to_thread.run_sync(meta.post, int(giorni))


@mcp.tool()
async def instagram_competitor(profilo: str, quanti: int = 25) -> dict:
    """Analisi di un profilo Instagram concorrente (solo account business/creator): follower,
    frequenza di pubblicazione, ultimi `quanti` contenuti con like, commenti, views (se disponibili)
    ed engagement %, più i migliori 8. profilo: nome utente, es. "nomeprofilo" o "@nomeprofilo"."""
    return await anyio.to_thread.run_sync(meta.competitor, profilo, int(quanti))


@mcp.tool()
async def meta_verifica() -> dict:
    """Solo manutenzione: controlla che il token Meta funzioni e quali permessi ha."""
    return await anyio.to_thread.run_sync(meta.verifica)


if __name__ == "__main__":
    print(f"Connettore attivo su 127.0.0.1:{mcp.settings.port}{mcp.settings.streamable_http_path}")
    mcp.run(transport="streamable-http")
