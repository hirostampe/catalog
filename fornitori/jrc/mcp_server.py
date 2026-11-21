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


@mcp.tool()
async def cerca_innovative_wear(richiesta: str, max_articoli: int = 5) -> dict:
    """Cerca nel catalogo Innovative Wear (Gildan, Fruit of the Loom, Russell, Just Hoods,
    Stedman, Premier, Regatta, Atlantis…). Restituisce l'elenco dei risultati (codice, nome,
    marca) e la scheda completa dei primi `max_articoli`: composizione, grammatura, cartone,
    colori, e per ogni colore disponibilità e prezzi per taglia.

    richiesta: parole semplici o un codice articolo, es. "felpa cappuccio", "gildan 18500", "JC052".
    max_articoli: quante schede aprire (1-10, ~3 secondi l'una).
    """
    n = max(1, min(int(max_articoli), 10))
    return await anyio.to_thread.run_sync(_in_coda, _iw.cerca_completo, richiesta, n)


@mcp.tool()
async def articolo_innovative_wear(codice: str) -> dict:
    """Scheda completa di un articolo Innovative Wear dal codice (es. "JC052", "18500"):
    colori, taglie, prezzi e disponibilità in tempo reale."""
    return await anyio.to_thread.run_sync(_in_coda, _iw.articolo, codice.strip())


@mcp.tool()
async def prezzi_quantita_innovative_wear(variante: str) -> str:
    """Scaglioni di prezzo per quantità di una variante Innovative Wear (id 'variante'
    preso dalla scheda articolo)."""
    return await anyio.to_thread.run_sync(_in_coda, _iw.prezzi_quantita, variante.strip())


@mcp.tool()
async def diagnosi_innovative_wear(codice: str) -> dict:
    """Solo per manutenzione: HTML dell'area acquisto di una scheda Innovative Wear (da loggato)."""
    return await anyio.to_thread.run_sync(_in_coda, _iw.diagnosi, codice.strip())


@mcp.tool()
async def diagnosi_james_ross(codice: str) -> dict:
    """Solo per manutenzione: restituisce pezzi dell'HTML della scheda (da loggato) attorno
    a prezzi e peso, per capire perché un dato non viene letto. Non usarlo per le ricerche."""
    return await anyio.to_thread.run_sync(_in_coda, _bot.diagnosi, codice.strip())


if __name__ == "__main__":
    print(f"Connettore attivo su 127.0.0.1:{mcp.settings.port}{mcp.settings.streamable_http_path}")
    mcp.run(transport="streamable-http")
