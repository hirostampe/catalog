# Bot James Ross — installazione sul server Hetzner

Tempo: circa 10 minuti. Copia e incolla i comandi uno alla volta.

## 1. Entra nel server
Dal Mac apri **Terminale** e scrivi (metti l'IP del tuo server Hetzner):
```
ssh root@IP-DEL-SERVER
```

## 2. Installa il bot
```
apt update && apt install -y python3-venv git
git clone -b claude/epic-lamport-bo4crp https://github.com/hirostampe/catalog.git /opt/hirostampe
cd /opt/hirostampe/fornitori/jrc
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

## 3. Metti le credenziali James Ross (solo sul server)
```
cp .env.example .env
nano .env
```
Scrivi utente e password al posto degli esempi, poi salva: `Ctrl+O`, `Invio`, `Ctrl+X`.
```
chmod 600 .env
```

## 4. Prova
```
.venv/bin/python jrc.py login
.venv/bin/python jrc.py cerca "felpa navy"
.venv/bin/python jrc.py articolo 987690
```
Devi vedere prezzi (scatola / sfuso / 1 pezzo) e giacenze per taglia.

Se scrive «prezzi non letti», nella cartella `debug/` c'è la pagina salvata: avvisa Claude.

## Aggiornare il bot in futuro
```
cd /opt/hirostampe && git pull
```
