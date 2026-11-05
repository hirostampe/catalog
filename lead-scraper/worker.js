#!/usr/bin/env node
// Worker per il Mac: ogni minuto chiede al Google Sheet se ci sono richieste dal telefono,
// le esegue (Maps → siti → Instagram) e rimanda i lead nello Sheet.
//
//   node worker.js --url <URL web app> --key <chiave>   (prima volta: salva la configurazione)
//   node worker.js                                      (avvia)
//   node worker.js --test                               (controlla il collegamento e esce)
//   node worker.js --installa / --rimuovi               (avvio automatico all'accensione del Mac)
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn, execFileSync } = require('child_process');
const { runPipeline, summary } = require('./src/pipeline');
const { log, sleep } = require('./src/util');

const CONFIG = path.join(__dirname, 'config.json');
const POLL_MS = 60 * 1000;
const LABEL = 'com.hirostampe.leadworker';
const PLIST = path.join(os.homedir(), 'Library', 'LaunchAgents', `${LABEL}.plist`);

function arg(name) {
  const i = process.argv.indexOf(name);
  return i > 0 ? process.argv[i + 1] : undefined;
}
const flag = (name) => process.argv.includes(name);
const ts = () => new Date().toLocaleString('it-IT', { timeZone: 'Europe/Rome' });

function loadConfig() {
  let cfg = {};
  try { cfg = JSON.parse(fs.readFileSync(CONFIG, 'utf8')); } catch {}
  if (arg('--url') || arg('--key')) {
    cfg.url = (arg('--url') || cfg.url || '').trim();
    cfg.key = (arg('--key') || cfg.key || '').trim();
    fs.writeFileSync(CONFIG, JSON.stringify(cfg, null, 2));
    fs.chmodSync(CONFIG, 0o600);
    log(`Configurazione salvata in ${CONFIG}`);
  }
  if (!cfg.url || !cfg.key) {
    log('Manca la configurazione. Prima volta:\n  node worker.js --url "<URL web app>" --key "<chiave segreta>"');
    process.exit(1);
  }
  return cfg;
}

async function api(cfg, method, payload) {
  const opts = { method, redirect: 'follow' };
  let url = cfg.url;
  if (method === 'GET') {
    url += (url.includes('?') ? '&' : '?') + new URLSearchParams({ k: cfg.key, ...payload });
  } else {
    opts.headers = { 'Content-Type': 'text/plain;charset=utf-8' }; // evita il preflight di Apps Script
    opts.body = JSON.stringify({ k: cfg.key, ...payload });
  }
  const res = await fetch(url, opts);
  const text = await res.text();
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(`Risposta non valida dallo Sheet (HTTP ${res.status}): ${text.slice(0, 120)}`);
  }
}

// Durante un lavoro impedisce al Mac di andare in stop.
function keepAwake() {
  if (process.platform !== 'darwin') return () => {};
  const p = spawn('caffeinate', ['-i', '-w', String(process.pid)], { stdio: 'ignore' });
  return () => p.kill();
}

async function runJob(cfg, job) {
  const titolo = job.handles.length ? `${job.handles.length} profili Instagram` : `${job.cerca.join(', ')} · ${job.citta.join(', ')}`;
  log(`\n[${ts()}] Richiesta ${job.id}: ${titolo}`);
  const release = keepAwake();
  try {
    await api(cfg, 'POST', { api: 'progress', id: job.id, note: 'Mac al lavoro…' }).catch(() => {});
    const rows = await runPipeline(job);
    const s = summary(rows);
    const r = await api(cfg, 'POST', { api: 'result', id: job.id, rows, summary: s });
    if (!r.ok) throw new Error(r.error || 'invio non riuscito');
    log(`[${ts()}] Fatto: ${r.nuovi} nuovi, ${r.aggiornati} aggiornati → Sheet`);
  } catch (e) {
    log(`[${ts()}] Errore: ${e.message}`);
    await api(cfg, 'POST', { api: 'result', id: job.id, error: e.message }).catch(() => {});
  } finally {
    release();
  }
}

async function loop(cfg) {
  log(`[${ts()}] Worker avviato. Controllo lo Sheet ogni ${POLL_MS / 1000}s. Ctrl+C per fermare.`);
  for (;;) {
    try {
      const r = await api(cfg, 'GET', { api: 'next' });
      if (!r.ok) log(`[${ts()}] Sheet: ${r.error || 'errore'}`);
      if (r.job) {
        await runJob(cfg, r.job);
        continue; // subito la prossima, se c'è
      }
    } catch (e) {
      log(`[${ts()}] Sheet non raggiungibile: ${e.message}`);
    }
    await sleep(POLL_MS);
  }
}

function installService() {
  if (process.platform !== 'darwin') {
    log('L\'avvio automatico è previsto per Mac. Su altri sistemi avvia "node worker.js" a mano.');
    process.exit(1);
  }
  const logFile = path.join(__dirname, 'output', 'worker.log');
  fs.mkdirSync(path.dirname(logFile), { recursive: true });
  fs.mkdirSync(path.dirname(PLIST), { recursive: true });
  const plist = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>${LABEL}</string>
  <key>ProgramArguments</key><array><string>${process.execPath}</string><string>${path.join(__dirname, 'worker.js')}</string></array>
  <key>WorkingDirectory</key><string>${__dirname}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${logFile}</string>
  <key>StandardErrorPath</key><string>${logFile}</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string></dict>
</dict></plist>
`;
  try { execFileSync('launchctl', ['unload', PLIST], { stdio: 'ignore' }); } catch {}
  fs.writeFileSync(PLIST, plist);
  execFileSync('launchctl', ['load', PLIST]);
  log(`Avvio automatico attivo: il worker parte da solo a ogni accensione del Mac.\nLog: ${logFile}`);
}

function removeService() {
  try { execFileSync('launchctl', ['unload', PLIST], { stdio: 'ignore' }); } catch {}
  if (fs.existsSync(PLIST)) fs.unlinkSync(PLIST);
  log('Avvio automatico rimosso.');
}

async function main() {
  if (flag('--rimuovi')) return removeService();
  const cfg = loadConfig();
  if (flag('--installa')) return installService();
  if (flag('--test')) {
    const r = await api(cfg, 'GET', { api: 'next' });
    if (!r.ok) throw new Error(r.error || 'risposta non valida');
    log(r.job ? `Collegamento OK. C'è una richiesta in coda (${r.job.id}): la eseguo.` : 'Collegamento OK. Nessuna richiesta in coda.');
    if (r.job) await runJob(cfg, r.job);
    return;
  }
  if (arg('--url') && !flag('--avvia')) {
    log('Ora prova il collegamento con: node worker.js --test');
    return;
  }
  await loop(cfg);
}

main().catch((e) => {
  log('Errore:', e.message);
  process.exit(1);
});
