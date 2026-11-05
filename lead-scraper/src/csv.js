const fs = require('fs');

function toCsv(rows, columns) {
  const esc = (v) => {
    const s = v == null ? '' : String(v);
    return /[",\n;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return '﻿' + [columns.join(','), ...rows.map((r) => columns.map((c) => esc(r[c])).join(','))].join('\n') + '\n';
}

function writeCsv(file, rows, columns) {
  fs.writeFileSync(file, toCsv(rows, columns));
}

module.exports = { toCsv, writeCsv };
