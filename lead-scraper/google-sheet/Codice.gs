/**
 * Hirostampe Lead – centralino su Google Sheet.
 * - Pagina per il telefono: si scrive nicchia + città → finisce in "Richieste".
 * - Il Mac (worker.js) chiede la prossima richiesta, la esegue e rimanda i lead → finiscono in "Lead".
 *
 * Installazione: vedi lead-scraper/README.md, sezione "Dal telefono".
 */

const TAB_RICHIESTE = 'Richieste';
const TAB_LEAD = 'Lead';
const RICHIESTE_HEADER = ['id', 'data', 'nicchia', 'citta', 'max', 'siti', 'instagram', 'profili_ig',
  'stato', 'inizio', 'fine', 'lead_nuovi', 'lead_aggiornati', 'note'];
const LEAD_FIXED_START = ['data_aggiunta', 'richiesta'];
const LEAD_FIXED_END = ['stato_contatto', 'note_contatto'];
const LEAD_DEFAULT = ['nome', 'categoria', 'indirizzo', 'telefono', 'cellulare', 'whatsapp_link', 'email', 'sito',
  'sito_ok', 'instagram', 'instagram_url', 'ig_follower', 'ig_seguiti', 'ig_post', 'ig_stato', 'facebook', 'tiktok',
  'rating', 'recensioni', 'ricerca', 'maps_url', 'lat', 'lng'];
// Campi che il Mac non sovrascrive mai (li gestisci tu).
const PROTETTI = ['data_aggiunta', 'richiesta', 'stato_contatto', 'note_contatto'];
const ORE_BLOCCO = 3; // una richiesta "in corso" da più di 3 ore torna in coda

/* ---------- Primo avvio: esegui questa funzione una volta dall'editor ---------- */
function setup() {
  const ss = SpreadsheetApp.getActive();
  ensureTab_(ss, TAB_RICHIESTE, RICHIESTE_HEADER);
  ensureTab_(ss, TAB_LEAD, LEAD_FIXED_START.concat(LEAD_DEFAULT, LEAD_FIXED_END));
  const props = PropertiesService.getScriptProperties();
  if (!props.getProperty('KEY')) props.setProperty('KEY', Utilities.getUuid().replace(/-/g, ''));
  const key = props.getProperty('KEY');
  Logger.log('CHIAVE SEGRETA: ' + key);
  Logger.log('Dopo il deploy, la pagina per il telefono sarà: <URL web app>?k=' + key);
  return key;
}

function ensureTab_(ss, name, header) {
  let sh = ss.getSheetByName(name);
  if (!sh) sh = ss.insertSheet(name);
  if (sh.getLastRow() === 0) {
    sh.getRange(1, 1, 1, header.length).setValues([header]).setFontWeight('bold').setBackground('#FFD60A');
    sh.setFrozenRows(1);
  }
  return sh;
}

/* ---------- Web app ---------- */
function doGet(e) {
  const p = (e && e.parameter) || {};
  if (!checkKey_(p.k)) return ContentService.createTextOutput('Accesso negato');
  if (p.api === 'next') return json_(claimNext_());
  const t = HtmlService.createTemplateFromFile('Pagina');
  t.key = p.k;
  t.sheetUrl = SpreadsheetApp.getActive().getUrl();
  return t.evaluate()
    .setTitle('Hirostampe Lead')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function doPost(e) {
  let body = {};
  try { body = JSON.parse(e.postData.contents); } catch (err) { return json_({ ok: false, error: 'JSON non valido' }); }
  if (!checkKey_(body.k)) return json_({ ok: false, error: 'Accesso negato' });
  if (body.api === 'result') return json_(saveResult_(body));
  if (body.api === 'progress') return json_(saveProgress_(body));
  return json_({ ok: false, error: 'api sconosciuta' });
}

function checkKey_(k) {
  const key = PropertiesService.getScriptProperties().getProperty('KEY');
  return !!key && k === key;
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

/* ---------- Funzioni chiamate dalla pagina del telefono ---------- */
function addRequest(k, form) {
  if (!checkKey_(k)) throw new Error('Accesso negato');
  const nicchia = String(form.nicchia || '').trim();
  const profili = String(form.profili_ig || '').trim();
  if (!nicchia && !profili) throw new Error('Scrivi almeno una nicchia o dei profili Instagram');
  const sh = ensureTab_(SpreadsheetApp.getActive(), TAB_RICHIESTE, RICHIESTE_HEADER);
  const id = 'R' + Utilities.formatDate(new Date(), 'Europe/Rome', 'yyMMdd-HHmmss');
  const max = Math.min(Math.max(parseInt(form.max, 10) || 20, 1), 120);
  sh.appendRow([id, new Date(), nicchia, String(form.citta || '').trim(), max,
    form.siti ? 'si' : 'no', form.instagram ? 'si' : 'no', profili, 'In coda', '', '', '', '', '']);
  return getStatus(k);
}

function getStatus(k) {
  if (!checkKey_(k)) throw new Error('Accesso negato');
  const sh = ensureTab_(SpreadsheetApp.getActive(), TAB_RICHIESTE, RICHIESTE_HEADER);
  const last = sh.getLastRow();
  const n = Math.min(12, Math.max(last - 1, 0));
  const rows = n ? sh.getRange(last - n + 1, 1, n, RICHIESTE_HEADER.length).getValues() : [];
  const fmt = (d) => (d instanceof Date ? Utilities.formatDate(d, 'Europe/Rome', 'dd/MM HH:mm') : '');
  const seen = Number(PropertiesService.getScriptProperties().getProperty('WORKER_SEEN') || 0);
  return {
    macOnline: seen && Date.now() - seen < 5 * 60 * 1000,
    macVisto: seen ? Utilities.formatDate(new Date(seen), 'Europe/Rome', 'dd/MM HH:mm') : 'mai',
    richieste: rows.reverse().map((r) => ({
      id: r[0], data: fmt(r[1]), nicchia: r[2] || (r[7] ? 'Profili Instagram' : ''), citta: r[3],
      stato: r[8], nuovi: r[11], aggiornati: r[12], note: r[13],
    })),
  };
}

/* ---------- API per il Mac ---------- */
function claimNext_() {
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    PropertiesService.getScriptProperties().setProperty('WORKER_SEEN', String(Date.now()));
    const sh = ensureTab_(SpreadsheetApp.getActive(), TAB_RICHIESTE, RICHIESTE_HEADER);
    const last = sh.getLastRow();
    if (last < 2) return { ok: true, job: null };
    const data = sh.getRange(2, 1, last - 1, RICHIESTE_HEADER.length).getValues();
    const col = (name) => RICHIESTE_HEADER.indexOf(name);
    // Richieste rimaste bloccate (es. Mac spento a metà) tornano in coda.
    data.forEach((r, i) => {
      if (r[col('stato')] === 'In corso' && r[col('inizio')] instanceof Date &&
          Date.now() - r[col('inizio')].getTime() > ORE_BLOCCO * 3600 * 1000) {
        sh.getRange(i + 2, col('stato') + 1).setValue('In coda');
        r[col('stato')] = 'In coda';
      }
    });
    const i = data.findIndex((r) => r[col('stato')] === 'In coda');
    if (i < 0) return { ok: true, job: null };
    const r = data[i];
    sh.getRange(i + 2, col('stato') + 1, 1, 2).setValues([['In corso', new Date()]]);
    const list = (s) => String(s || '').split(/[,\n]/).map((x) => x.trim()).filter(Boolean);
    return {
      ok: true,
      job: {
        id: r[col('id')], cerca: list(r[col('nicchia')]), citta: list(r[col('citta')]), max: Number(r[col('max')]) || 20,
        sito: r[col('siti')] !== 'no', instagram: r[col('instagram')] !== 'no', handles: list(r[col('profili_ig')]),
      },
    };
  } finally {
    lock.releaseLock();
  }
}

function findRequestRow_(sh, id) {
  const last = sh.getLastRow();
  if (last < 2) return -1;
  const ids = sh.getRange(2, 1, last - 1, 1).getValues().map((r) => r[0]);
  const i = ids.indexOf(id);
  return i < 0 ? -1 : i + 2;
}

function saveProgress_(body) {
  PropertiesService.getScriptProperties().setProperty('WORKER_SEEN', String(Date.now()));
  const sh = ensureTab_(SpreadsheetApp.getActive(), TAB_RICHIESTE, RICHIESTE_HEADER);
  const row = findRequestRow_(sh, body.id);
  if (row > 0) sh.getRange(row, RICHIESTE_HEADER.indexOf('note') + 1).setValue(String(body.note || ''));
  return { ok: true };
}

function saveResult_(body) {
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    PropertiesService.getScriptProperties().setProperty('WORKER_SEEN', String(Date.now()));
    const ss = SpreadsheetApp.getActive();
    const req = ensureTab_(ss, TAB_RICHIESTE, RICHIESTE_HEADER);
    const reqRow = findRequestRow_(req, body.id);
    const setReq = (name, v) => reqRow > 0 && req.getRange(reqRow, RICHIESTE_HEADER.indexOf(name) + 1).setValue(v);

    if (body.error) {
      setReq('stato', 'Errore');
      setReq('fine', new Date());
      setReq('note', String(body.error).slice(0, 300));
      return { ok: true };
    }

    const sh = ensureTab_(ss, TAB_LEAD, LEAD_FIXED_START.concat(LEAD_DEFAULT, LEAD_FIXED_END));
    let header = sh.getRange(1, 1, 1, sh.getLastColumn()).getValues()[0];
    // Colonne nuove inviate dal Mac → aggiunte in fondo.
    const rows = body.rows || [];
    const extra = [];
    rows.forEach((r) => Object.keys(r).forEach((k) => {
      if (header.indexOf(k) < 0 && extra.indexOf(k) < 0) extra.push(k);
    }));
    if (extra.length) {
      sh.getRange(1, header.length + 1, 1, extra.length).setValues([extra]).setFontWeight('bold').setBackground('#FFD60A');
      header = header.concat(extra);
    }
    const H = (name) => header.indexOf(name);
    const last = sh.getLastRow();
    const existing = last > 1 ? sh.getRange(2, 1, last - 1, header.length).getValues() : [];
    // Chiave anti-doppioni: link Maps, altrimenti handle Instagram.
    const keyOf = (o) => (o.maps_url ? 'm:' + o.maps_url : o.instagram ? 'ig:' + String(o.instagram).toLowerCase() : '');
    const index = {};
    existing.forEach((r, i) => {
      const m = r[H('maps_url')];
      const ig = r[H('instagram')];
      if (m) index['m:' + m] = i;
      if (ig && index['ig:' + String(ig).toLowerCase()] === undefined) index['ig:' + String(ig).toLowerCase()] = i;
    });

    const nuove = [];
    let aggiornati = 0;
    const touched = {};
    rows.forEach((o) => {
      let i = index[keyOf(o)];
      if (i === undefined && o.instagram) i = index['ig:' + String(o.instagram).toLowerCase()];
      if (i !== undefined && i >= existing.length) return; // doppione nello stesso invio
      if (i !== undefined) {
        Object.keys(o).forEach((k) => {
          if (PROTETTI.indexOf(k) < 0 && o[k] !== '' && o[k] != null) existing[i][H(k)] = o[k];
        });
        touched[i] = true;
        aggiornati++;
      } else {
        const row = header.map((h) => (h === 'data_aggiunta' ? new Date() : h === 'richiesta' ? body.id
          : h === 'stato_contatto' ? 'da contattare' : o[h] != null ? o[h] : ''));
        index[keyOf(o)] = existing.length + nuove.length; // evita doppioni nello stesso invio
        nuove.push(row);
      }
    });
    Object.keys(touched).forEach((i) => sh.getRange(Number(i) + 2, 1, 1, header.length).setValues([existing[i]]));
    if (nuove.length) sh.getRange(sh.getLastRow() + 1, 1, nuove.length, header.length).setValues(nuove);

    setReq('stato', 'Fatto');
    setReq('fine', new Date());
    setReq('lead_nuovi', nuove.length);
    setReq('lead_aggiornati', aggiornati);
    const s = body.summary || {};
    setReq('note', `tel ${s.telefono || 0} · cell ${s.cellulari || 0} · email ${s.email || 0} · IG ${s.instagram || 0}`);
    return { ok: true, nuovi: nuove.length, aggiornati: aggiornati };
  } finally {
    lock.releaseLock();
  }
}
