from __future__ import annotations


def operator_panel_html() -> str:
    return """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Cleo Rover Mk1</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
    body { margin: 0; background: radial-gradient(circle at 50% 0%, #241042, #05060b 58%); color: #eef5ff; }
    main { max-width: 920px; margin: 0 auto; padding: 24px; }
    h1 { margin: 0 0 4px; font-size: 28px; letter-spacing: .08em; text-transform: uppercase; }
    .sub { color: #9cb7d9; margin-bottom: 24px; }
    .grid { display: grid; grid-template-columns: 280px 1fr; gap: 18px; align-items: start; }
    .card { background: rgba(5,8,18,.72); border: 1px solid rgba(120,210,255,.22); border-radius: 18px; padding: 16px; box-shadow: 0 0 40px rgba(140,60,255,.12); }
    .screen-wrap { display: flex; justify-content: center; }
    img.screen { width: 240px; height: 320px; border-radius: 18px; border: 1px solid rgba(140,230,255,.35); box-shadow: 0 0 32px rgba(160,80,255,.35); object-fit: cover; }
    .row { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0; }
    button, select, input { background: #111827; color: #eef5ff; border: 1px solid rgba(150,210,255,.28); border-radius: 10px; padding: 10px 12px; }
    button { cursor: pointer; transition: .12s ease; }
    button:hover { border-color: #72e7ff; box-shadow: 0 0 14px rgba(114,231,255,.22); transform: translateY(-1px); }
    button.danger { border-color: rgba(255,110,110,.5); background: #251014; }
    .status { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .kv { background: rgba(255,255,255,.045); border-radius: 10px; padding: 10px; color: #b8c9e7; }
    .kv b { display: block; color: #fff; font-size: 18px; margin-top: 3px; }
    pre { white-space: pre-wrap; color: #a9c4df; background: rgba(0,0,0,.28); border-radius: 12px; padding: 12px; max-height: 260px; overflow: auto; }
    @media (max-width: 760px) { .grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
<main>
  <h1>Cleo Rover Mk1</h1>
  <div class=\"sub\">Obsidian Familiar operator panel, sim-safe until the body arrives.</div>
  <div class=\"grid\">
    <section class=\"card screen-wrap\"><img id=\"screen\" class=\"screen\" src=\"/expression/preview.png?ts=0\" /></section>
    <section class=\"card\">
      <div class=\"status\" id=\"statusCards\"></div>
      <h3>Expression</h3>
      <div class=\"row\">
        <select id=\"mode\">
          <option>idle</option><option>listening</option><option>thinking</option><option>speaking</option>
          <option>alert</option><option>charging</option><option>disconnected</option><option>manual</option>
        </select>
        <input id=\"text\" placeholder=\"short status text\" maxlength=\"24\" />
        <button onclick=\"setExpression()\">Set</button>
      </div>
      <h3>Drive</h3>
      <div class=\"row\">
        <button onclick=\"drive(0.25,0)\">Forward</button>
        <button onclick=\"drive(-0.25,0)\">Back</button>
        <button onclick=\"drive(0,-0.35)\">Left</button>
        <button onclick=\"drive(0,0.35)\">Right</button>
        <button class=\"danger\" onclick=\"stop()\">STOP</button>
      </div>
      <h3>Raw status</h3>
      <pre id=\"raw\"></pre>
    </section>
  </div>
</main>
<script>
async function api(path, opts={}) {
  const res = await fetch(path, {headers: {'content-type':'application/json'}, ...opts});
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}
async function refresh() {
  const s = await api('/status');
  document.getElementById('raw').textContent = JSON.stringify(s, null, 2);
  document.getElementById('statusCards').innerHTML = `
    <div class=\"kv\">Mode<b>${s.mode}</b></div>
    <div class=\"kv\">Stopped<b>${s.stopped}</b></div>
    <div class=\"kv\">Expression<b>${s.expression.mode}</b></div>
    <div class=\"kv\">Camera<b>${s.camera_ready ? 'ready' : 'pending'}</b></div>`;
  document.getElementById('mode').value = s.expression.mode;
  document.getElementById('screen').src = '/expression/preview.png?ts=' + Date.now();
}
async function setExpression() {
  await api('/expression', {method:'POST', body: JSON.stringify({mode: mode.value, text: text.value || null, brightness: 0.72})});
  await refresh();
}
async function drive(linear, turn) {
  await api('/drive', {method:'POST', body: JSON.stringify({linear, turn, duration_ms: 350})});
  await refresh();
}
async function stop() { await api('/stop', {method:'POST'}); await refresh(); }
setInterval(refresh, 1500); refresh();
</script>
</body>
</html>"""
