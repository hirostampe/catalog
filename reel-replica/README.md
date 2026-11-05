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

## Uso

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
