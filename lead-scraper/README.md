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

## Dal telefono (Google Sheet + Mac a casa)

Come funziona:

```
Telefono (pagina web) → Google Sheet "Richieste" → Mac a casa esegue → Google Sheet "Lead"
```

- Dal telefono scrivi nicchia + città (o tocchi i bottoni rapidi) e premi **Cerca lead**.
- Il Mac controlla il foglio ogni minuto, esegue la ricerca e scrive i lead nella scheda **Lead**.
- I doppioni non entrano: se un locale c'è già, i suoi dati vengono aggiornati.
  Le colonne `stato_contatto` e `note_contatto` sono tue: il Mac non le tocca mai.
- La pagina mostra se il Mac è acceso e lo stato di ogni richiesta (In coda / In corso / Fatto).

### Installazione (una volta sola, dal PC, circa 10 minuti)

**1. Google Sheet**
1. Crea un nuovo Google Sheet, per esempio "Hirostampe Lead".
2. Menu **Estensioni → Apps Script**.
3. Nel file `Codice.gs` cancella tutto e incolla il contenuto di `google-sheet/Codice.gs`.
4. Clicca **+ → HTML**, chiamalo `Pagina` e incolla il contenuto di `google-sheet/Pagina.html`.
5. In alto scegli la funzione `setup` e premi **Esegui**. Autorizza il tuo account Google.
   In fondo, nel registro, compare la **CHIAVE SEGRETA**: copiala.
6. **Esegui il deployment → Nuovo deployment → tipo: App web**
   - Esegui come: **Me**
   - Chi ha accesso: **Chiunque**
   - Premi **Esegui il deployment** e copia l'**URL dell'app web** (finisce con `/exec`).

**2. Mac**
```bash
cd lead-scraper
npm run setup                                   # se non l'hai già fatto
node worker.js --url "URL_APP_WEB" --key "CHIAVE_SEGRETA"
npm run test-collegamento                        # deve dire "Collegamento OK"
npm run servizio:installa                        # parte da solo a ogni accensione del Mac
```

**3. Telefono**
Apri `URL_APP_WEB?k=CHIAVE_SEGRETA` e poi **Condividi → Aggiungi a Home**: diventa un'icona come un'app.

Note:
- Il Mac deve essere acceso e non in stop. In *Impostazioni → Batteria/Risparmio energia* attiva
  "Impedisci lo stop automatico quando lo schermo è spento" (con il Mac collegato alla corrente).
  Durante una ricerca il worker tiene già sveglio il Mac da solo.
- Se il Mac è spento, le richieste restano in coda e partono appena lo riaccendi.
- La chiave segreta è come una password: senza chiave la pagina risponde "Accesso negato".
  Non condividere il link con la chiave.
- Log del worker: `lead-scraper/output/worker.log`. Per togliere l'avvio automatico: `npm run servizio:rimuovi`.
- Se modifichi `Codice.gs` o `Pagina.html`: **Esegui il deployment → Gestisci deployment → modifica → Nuova versione**
  (l'URL resta lo stesso).

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

- `scrape.js` → comando da Terminale (CSV)
- `worker.js` → servizio per il Mac che esegue le richieste dal telefono
- `google-sheet/Codice.gs`, `google-sheet/Pagina.html` → da incollare in Apps Script
- `src/pipeline.js` → motore comune (Maps → siti → Instagram)
- `src/maps.js` → Google Maps
- `src/website.js` → siti web
- `src/instagram.js` → Instagram
- `src/csv.js`, `src/util.js` → supporto
