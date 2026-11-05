# Reel Replica — da reel di riferimento a reel Hirostampe

Scarica un reel Instagram o un video TikTok che funziona e prepara un **pacchetto
analisi** da caricare su Claude, che poi rifà la **stessa struttura** (hook, ritmo
dei tagli, testi, CTA) con le tue clip.

## Installazione (una volta sola)

1. Python 3.10+ e ffmpeg
   - Mac: `brew install python ffmpeg`
   - Windows: `winget install Python.Python.3.12 Gyan.FFmpeg`
2. Nella cartella `reel-replica`:
   ```
   pip install -r requirements.txt
   ```

## Come si apre l'app

- **Mac:** doppio clic su `Avvia Mac.command` (la prima volta: tasto destro → Apri).
- **Windows:** doppio clic su `Avvia Windows.bat`.

Al primo avvio installa da solo quello che serve, poi apre il browser su
`http://localhost:8765`. Da lì:

1. incolli uno o più link e premi **Analizza**;
2. segui l'avanzamento in "In lavorazione";
3. nella **Libreria** trovi una scheda per ogni reel con fotogrammi, durata, tagli,
   views e like. Hai tre pulsanti: **Copia prompt**, **Pacchetto** (scarica lo zip) e
   **Cartella**. Se clicchi sui fotogrammi vedi tutte le inquadrature con i tempi.

Se Instagram chiede il login, spunta **Usa il login del browser** e scegli il
browser in cui sei collegato a Instagram.

Per chiudere l'app chiudi la finestra del terminale.

## Top per nicchia: trovare i video con più views

Scheda **🔥 Top per nicchia**. Ci sono due fonti:

### Gratis · il tuo login (predefinita)
- **Hashtag Instagram**: scegli una nicchia pronta o scrivi i tuoi hashtag. Serve
  essere collegati a instagram.com nel browser scelto (Chrome, Safari…).
- **Profili TikTok e Instagram**: inserisci gli account della nicchia (box,
  palestre, concorrenti). L'app legge i loro ultimi video e segnala quelli
  **🚀 fuori scala**, cioè con molte più views della media di quel profilo:
  il segnale migliore di un formato che funziona.
- Gli hashtag TikTok gratis non sono possibili: per quelli usa la fonte Apify.
- L'app fa poche richieste con delle pause. Usala per decine di video, non
  migliaia, per non far insospettire Instagram.
- Su Mac la prima volta può chiedere la password del portachiavi per leggere il
  login di Chrome: clicca **Consenti sempre**. Con Safari serve dare al Terminale
  "Accesso completo al disco" (Impostazioni → Privacy e sicurezza).

### Apify · a pagamento (opzionale)
Cerca per hashtag sia su Instagram sia su TikTok, senza usare il tuo account.
Circa 0,3 centesimi di dollaro per video. Token da inserire in ⚙︎ Impostazioni
(apify.com → Settings → API & Integrations); resta salvato solo sul tuo computer.

### Classifica
Ordinabile per **più visualizzazioni**, **più coinvolgimento**, **fuori scala**
(vs media del profilo) e **views rispetto ai follower**. Spunta i video e premi
**Analizza selezionati**: finiscono in Libreria con il pacchetto per Claude.

## Uso da riga di comando (alternativa)

```
python scarica_reel.py https://www.instagram.com/reel/XXXX/
python scarica_reel.py https://www.tiktok.com/@utente/video/123 https://www.instagram.com/reel/YYYY/
python scarica_reel.py --file link.txt          # un link per riga
```

Se Instagram chiede il login, usa la sessione del tuo browser:
```
python scarica_reel.py URL --cookies-from-browser chrome
```

## Cosa ottieni

In `riferimenti/<piattaforma_autore_id>/`:

| File | A cosa serve |
|---|---|
| `video.mp4` | video originale, solo come riferimento |
| `provino.jpg` | tutte le inquadrature in un colpo d'occhio, con tempi |
| `frame_XX.jpg` | un fotogramma per inquadratura |
| `brief.md` | scaletta inquadrature + didascalia + numeri + **prompt per Claude** |
| `analisi.json` | stessi dati in formato macchina |
| `pacchetto.zip` | tutto quanto sopra (senza video) → **da caricare su Claude** |

Con `--con-video` lo zip include anche il video.

## Flusso con Claude

1. Lanci lo script sui reel che ti piacciono.
2. Su Claude carichi `pacchetto.zip` + le tue clip grezze.
3. Incolli il prompt che trovi in fondo a `brief.md`.
4. Claude analizza il riferimento, abbina le tue clip a ogni inquadratura, scrive
   testi e didascalia per Hirostampe e monta il reel.

## Note

- Usa i video di altri solo come **riferimento di formato**: rifai la struttura con
  contenuti tuoi, senza ripubblicare clip, grafiche o audio originali.
- Se trova troppi/pochi tagli, cambia `SOGLIA_TAGLIO` in cima allo script
  (più bassa = più tagli).
- Se un download smette di funzionare: `pip install -U yt-dlp`.
