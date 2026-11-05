# Lead scraper Hirostampe (alternativa ad Apify)

Fa in automatico quello che con Apify fai con 2-3 attori diversi:

1. **Google Maps** → cerca la nicchia nella zona (es. "box crossfit Milano") e prende nome, categoria, indirizzo, telefono, sito, rating, link Maps, coordinate.
2. **Sito web** → apre home + pagina contatti e trova email, Instagram, Facebook, TikTok, link WhatsApp.
3. **Instagram** → dalla pagina pubblica del profilo legge follower, seguiti e numero di post.
4. **CSV** pronto da importare in Google Sheets, con colonna `cellulare` (si/no) e `whatsapp_link` cliccabile per l'outreach.

Costo: zero. Gira sul tuo Mac.

## Installazione (una volta sola)

Serve [Node.js](https://nodejs.org) (versione 18 o superiore). Poi, nel Terminale:

```bash
cd lead-scraper
npm run setup
```

## Come si usa

```bash
# Una nicchia, più città (le combina tutte e toglie i doppioni)
node scrape.js --cerca "box crossfit" --citta "Milano,Venezia,Padova" --max 40

# Più parole chiave insieme
node scrape.js --cerca "bacaro,osteria,wine bar" --citta "Venezia" --max 20

# Solo Google Maps + siti, senza Instagram (più veloce)
node scrape.js --cerca "scuola di danza" --citta "Treviso" --no-instagram

# Solo Instagram: file di testo con un profilo per riga (@nome o link)
node scrape.js --instagram lista.txt

# Vedere il browser mentre lavora (utile se qualcosa non va)
node scrape.js --cerca "padel" --citta "Mestre" --visibile
```

Opzioni:

| Opzione | Cosa fa |
| --- | --- |
| `--cerca` / `-q` | parole chiave, separate da virgola |
| `--citta` / `-c` | città o quartieri, separati da virgola |
| `--max` / `-n` | massimo schede per ogni ricerca (default 30) |
| `--no-sito` | non visita i siti web |
| `--no-instagram` | non legge Instagram |
| `--instagram file.txt` | modalità solo profili Instagram |
| `--out file.csv` | nome del file di uscita |
| `--visibile` | mostra il browser |

Il CSV finisce in `lead-scraper/output/`. Per Google Sheets: *File → Importa → Carica*.

## Limiti da sapere

- **Google Maps senza login mostra circa 20 risultati per ricerca.** Per averne di più dividi la zona:
  invece di `--citta "Milano"` usa `--citta "Milano Navigli,Milano Isola,Milano Città Studi,Sesto San Giovanni"`
  oppure più parole chiave (`"crossfit,box crossfit,functional training"`). I doppioni vengono tolti in automatico.
- **Instagram** mostra i dati pubblici solo per un numero limitato di profili all'ora senza login. Se inizia a chiedere
  il login, lo script fa una pausa, riprova una volta e poi salta i profili rimanenti: handle e link restano comunque nel CSV.
  Lo script non usa account né API interne: non rischi ban sul tuo profilo.
- Le email si trovano solo se sono scritte sul sito. Molti locali piccoli non le hanno: lì vale telefono/WhatsApp/DM.
- Se Google cambia la pagina di Maps, qualche campo può risultare vuoto: va aggiornato `src/maps.js`.

## Privacy

Il repo `catalog` è **pubblico**: la cartella `output/` e tutti i `.csv` sono esclusi da git, non caricarli mai su GitHub.
Usa i contatti nel rispetto del GDPR (contatti aziendali, messaggio pertinente, possibilità di non essere più contattati).

## File

- `scrape.js` → comando principale
- `src/maps.js` → Google Maps
- `src/website.js` → siti web
- `src/instagram.js` → Instagram
- `src/csv.js`, `src/util.js` → supporto
