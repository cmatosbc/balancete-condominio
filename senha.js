/* Portão de senha — proteção VISUAL apenas.
   Não é segurança real: dados.js e o repositório continuam acessíveis
   a quem inspecionar. Serve para afastar curiosos.

   Senha atual: elitspark2026
   Para trocar: rode `echo -n "NOVASENHA" | sha256sum` e substitua EXPECTED. */
(function () {
  var EXPECTED = '39de14ed30aaf702a2482093b94a426550a4b0896f0614531d690125022f455b';
  var KEY = 'cond_acesso_v1';
  if (localStorage.getItem(KEY) === EXPECTED) return;

  document.documentElement.style.background = '#070c1a';
  document.documentElement.style.visibility = 'hidden';

  function sha256(s) {
    return crypto.subtle.digest('SHA-256', new TextEncoder().encode(s)).then(function (b) {
      return Array.from(new Uint8Array(b))
        .map(function (x) { return x.toString(16).padStart(2, '0'); }).join('');
    });
  }

  function showGate() {
    document.documentElement.style.visibility = '';
    var o = document.createElement('div');
    o.innerHTML =
      '<div style="position:fixed;inset:0;z-index:99999;' +
      'background:radial-gradient(1100px 600px at 15% -10%, rgba(56,189,248,.10), transparent 60%),#070c1a;' +
      'display:flex;align-items:center;justify-content:center;padding:20px;' +
      'font-family:Inter,system-ui,sans-serif">' +
      '<form style="background:rgba(15,23,42,.78);border:1px solid rgba(148,163,184,.14);' +
      'border-radius:22px;padding:40px 34px;max-width:360px;width:100%;text-align:center;' +
      'backdrop-filter:blur(10px);box-shadow:0 24px 60px rgba(0,0,0,.5)">' +
      '<div style="font-size:34px">🔒</div>' +
      '<div style="color:#7dd3fc;font-size:11px;letter-spacing:3px;text-transform:uppercase;' +
      'font-weight:600;margin:12px 0 6px">Condomínio Elit\'s Park</div>' +
      '<div style="color:#e8edf6;font-family:\'Space Grotesk\',sans-serif;font-size:22px;' +
      'margin-bottom:6px">Área dos condôminos</div>' +
      '<div style="color:#8a94a8;font-size:13px;margin-bottom:22px">' +
      'Digite a senha informada pela administração</div>' +
      '<input id="gateInp" type="password" placeholder="Senha" autocomplete="current-password" ' +
      'style="width:100%;padding:12px 14px;border-radius:10px;' +
      'border:1px solid rgba(148,163,184,.22);background:rgba(2,6,23,.65);color:#e8edf6;' +
      'font-size:15px;outline:none;box-sizing:border-box">' +
      '<div id="gateErr" style="display:none;color:#fb7185;font-size:12.5px;margin-top:8px">' +
      'Senha incorreta — tente novamente</div>' +
      '<button type="submit" style="margin-top:16px;width:100%;padding:12px;border-radius:10px;' +
      'border:none;background:linear-gradient(135deg,#38bdf8,#818cf8);color:#0b1220;' +
      'font-weight:700;font-size:14px;cursor:pointer">Entrar</button>' +
      '</form></div>';
    document.body.appendChild(o.firstChild);
    var inp = document.getElementById('gateInp');
    var err = document.getElementById('gateErr');
    inp.focus();
    inp.closest('form').addEventListener('submit', function (e) {
      e.preventDefault();
      sha256(inp.value).then(function (h) {
        if (h === EXPECTED) { localStorage.setItem(KEY, h); location.reload(); }
        else { err.style.display = 'block'; inp.value = ''; inp.focus(); }
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', showGate);
  } else {
    showGate();
  }
})();
