(function () {
  var startedAt = Date.now();
  function escaped(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#039;');
  }
  function showFailure(reason) {
    var root = document.getElementById('root');
    if (!root || root.getAttribute('data-app-mounted') === 'true') return;
    root.innerHTML = '<div style="min-height:100vh;background:#020617;color:#e2e8f0;display:grid;place-items:center;padding:24px;font-family:system-ui,sans-serif">' +
      '<div style="width:min(680px,100%);background:#0f172a;border:1px solid #334155;border-radius:20px;padding:28px;box-shadow:0 25px 80px rgba(0,0,0,.35)">' +
      '<div style="color:#f59e0b;font-size:12px;font-weight:700;letter-spacing:.18em;text-transform:uppercase">Frontend recovery</div>' +
      '<h1 style="margin:10px 0 8px;font-size:26px">The interface did not finish loading</h1>' +
      '<p style="color:#94a3b8;line-height:1.6;margin:0 0 16px">The server is reachable, but the browser could not start the application bundle. This build includes a browser-compatible bundle and a startup asset check.</p>' +
      '<div style="background:#020617;border:1px solid #1e293b;border-radius:12px;padding:12px;color:#cbd5e1;font:12px ui-monospace,monospace;word-break:break-word">' + escaped(reason || 'Frontend boot timeout') + '</div>' +
      '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:18px">' +
      '<button id="rc-recovery-reload" style="border:0;border-radius:10px;padding:10px 16px;background:#06b6d4;color:#082f49;font-weight:700;cursor:pointer">Reload</button>' +
      '<button id="rc-recovery-health" style="border:1px solid #334155;border-radius:10px;padding:10px 16px;background:#1e293b;color:#e2e8f0;font-weight:700;cursor:pointer">Open health check</button>' +
      '</div><div style="margin-top:14px;color:#64748b;font-size:12px">If this remains visible, close every old START.bat window and launch this folder again.</div>' +
      '</div></div>';
    var reloadButton = document.getElementById('rc-recovery-reload');
    var healthButton = document.getElementById('rc-recovery-health');
    if (reloadButton) reloadButton.addEventListener('click', function () { window.location.reload(); });
    if (healthButton) healthButton.addEventListener('click', function () { window.location.href = window.location.origin + '/health'; });
  }
  window.addEventListener('error', function (event) {
    if (Date.now() - startedAt < 30000) showFailure(event.message || 'JavaScript load error');
  });
  window.addEventListener('unhandledrejection', function (event) {
    if (Date.now() - startedAt < 30000) showFailure((event.reason && event.reason.message) || event.reason || 'Unhandled startup promise rejection');
  });
  window.addEventListener('riot-creator-mounted', function () {
    var root = document.getElementById('root');
    if (root) root.setAttribute('data-app-mounted', 'true');
  });
  setTimeout(function () { showFailure('Frontend boot timed out after 12 seconds.'); }, 12000);
})();
