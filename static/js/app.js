/* Helpers compartilhados entre as páginas do app (admin, propostas…).
 * Carregado por templates/base.html — só helpers, sem init por página. */
'use strict';
const $ = id => document.getElementById(id);
const BRL = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
const esc = s => String(s ?? '').replace(/[&<>"']/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function toast(msg, bad) {
  const t = $('toast');
  if (!t) return;
  t.textContent = msg;
  t.className = 'show' + (bad ? ' bad' : '');
  clearTimeout(t._h);
  t._h = setTimeout(() => { t.className = ''; }, 4200);
}

async function postForm(url, obj) {
  const fd = new FormData();
  Object.entries(obj || {}).forEach(([k, v]) => fd.append(k, v));
  return fetch(url, { method: 'POST', body: fd });
}
