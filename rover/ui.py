from __future__ import annotations


def operator_panel_html() -> str:
    return """<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Pip — Cleo Rover Mk1</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
    body { margin: 0; background: radial-gradient(circle at 50% 0%, #241042, #05060b 58%); color: #eef5ff; }
    main { max-width: 980px; margin: 0 auto; padding: 24px; }
    h1 { margin: 0 0 4px; font-size: 28px; letter-spacing: .08em; text-transform: uppercase; }
    .sub { color: #9cb7d9; margin-bottom: 20px; }
    .grid { display: grid; grid-template-columns: 280px 1fr; gap: 18px; align-items: start; }
    .card { background: rgba(5,8,18,.72); border: 1px solid rgba(120,210,255,.22); border-radius: 18px; padding: 16px; box-shadow: 0 0 40px rgba(140,60,255,.12); }
    .screen-wrap { display: flex; flex-direction: column; align-items: center; gap: 12px; }
    img.screen { width: 240px; height: 320px; border-radius: 18px; border: 1px solid rgba(140,230,255,.35); box-shadow: 0 0 32px rgba(160,80,255,.35); object-fit: cover; }
    .swatch { width: 240px; height: 28px; border-radius: 10px; border: 1px solid rgba(255,255,255,.18); display:flex; align-items:center; justify-content:center; font-size:12px; letter-spacing:.05em; text-transform:uppercase; }
    .row { display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0; }
    button, select, input { background: #111827; color: #eef5ff; border: 1px solid rgba(150,210,255,.28); border-radius: 10px; padding: 10px 12px; }
    button { cursor: pointer; transition: .12s ease; }
    button:hover { border-color: #72e7ff; box-shadow: 0 0 14px rgba(114,231,255,.22); transform: translateY(-1px); }
    button.danger { border-color: rgba(255,110,110,.5); background: #251014; }
    button.live { border-color: rgba(120,255,170,.5); background: #0c2417; }
    .status { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
    .kv { background: rgba(255,255,255,.045); border-radius: 10px; padding: 10px; color: #b8c9e7; font-size: 12px; }
    .kv b { display: block; color: #fff; font-size: 17px; margin-top: 3px; }
    .pill { display:inline-block; padding:2px 8px; border-radius:999px; font-size:12px; }
    .ok { background: rgba(60,200,120,.18); color:#8ef0b6; }
    .bad { background: rgba(255,110,110,.18); color:#ffb3b3; }
    .blockers { color:#ffcf99; font-size:13px; margin: 6px 0; }
    pre { white-space: pre-wrap; color: #a9c4df; background: rgba(0,0,0,.28); border-radius: 12px; padding: 12px; max-height: 220px; overflow: auto; }
    @media (max-width: 760px) { .grid { grid-template-columns: 1fr; } .status { grid-template-columns: repeat(2,1fr);} }
  </style>
</head>
<body>
<main>
  <h1>Pip</h1>
  <div class=\"sub\">Cleo Rover Mk1 — living-being operator panel. <span id=\"ver\"></span></div>
  <div class=\"grid\">
    <section class=\"card screen-wrap\">
      <img id=\"screen\" class=\"screen\" src=\"/expression/preview.png?ts=0\" />
      <div id=\"swatch\" class=\"swatch\">mood</div>
      <div id=\"ready\"></div>
    </section>
    <section class=\"card\">
      <div class=\"status\" id=\"statusCards\"></div>
      <div class=\"blockers\" id=\"blockers\"></div>
      <h3>Life</h3>
      <div class=\"row\">
        <button class=\"live\" onclick=\"live(true)\">Go Live</button>
        <button onclick=\"live(false)\">Pause</button>
        <button onclick=\"tick()\">Arbiter Tick</button>
      </div>
      <h3>Expression</h3>
      <div class=\"row\">
        <select id=\"mode\">
          <option>idle</option><option>curious</option><option>happy</option><option>listening</option>
          <option>thinking</option><option>alert</option><option>charging</option><option>sleeping</option>
        </select>
        <input id=\"text\" placeholder=\"short status text\" maxlength=\"24\" />
        <button onclick=\"setExpression()\">Set</button>
      </div>
      <h3>Drive (manual)</h3>
      <div class=\"row\">
        <button onclick=\"drive(0.25,0)\">Forward</button>
        <button onclick=\"drive(-0.25,0)\">Back</button>
        <button onclick=\"drive(0,-0.35)\">Left</button>
        <button onclick=\"drive(0,0.35)\">Right</button>
        <button class=\"danger\" onclick=\"stop()\">STOP</button>
      </div>
      <h3>Composite health</h3>
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
function card(label, value) { return `<div class=\"kv\">${label}<b>${value}</b></div>`; }
async function refresh() {
  let h;
  try { h = await api('/health/composite'); } catch (e) { return; }
  document.getElementById('raw').textContent = JSON.stringify(h, null, 2);
  const b = h.battery || {}, f = h.feelings || {}, m = h.movement || {}, a = h.arbiter || {}, n = h.nav || {}, d = h.degradation || {};
  const soc = (b.soc_percent==null?'—':Math.round(b.soc_percent)+'%') + (b.charging?' ⚡':'');
  document.getElementById('statusCards').innerHTML =
    card('Battery', soc) +
    card('Mood', f.mood || '—') +
    card('Energy', f.energy==null?'—':Math.round(f.energy*100)+'%') +
    card('Doing', a.would_choose || '—') +
    card('Capability', d.level || '—') +
    card('Place', n.current_place || 'unmapped') +
    card('Goal', h.goal ? (h.goal.kind+':'+(h.goal.target||'')) : 'none') +
    card('Grant', m.owner || (m.permitted?'permitted':'none')) +
    card('Mode', (h.identity||{}).mode || '—');
  const ready = h.ready_to_move;
  document.getElementById('ready').innerHTML = `<span class=\"pill ${ready?'ok':'bad'}\">${ready?'ready to move':'not ready'}</span>`;
  document.getElementById('blockers').textContent = (h.blockers && h.blockers.length) ? ('Blockers: ' + h.blockers.join(' · ')) : '';
  document.getElementById('ver').textContent = 'v' + ((h.identity||{}).version||'') + ' · soul ' + ((h.identity||{}).soul_version||'');
  const rgb = h.rgb_affect;
  if (rgb && rgb.color) {
    const sw = document.getElementById('swatch');
    sw.style.background = `rgb(${rgb.color[0]},${rgb.color[1]},${rgb.color[2]})`;
    sw.textContent = (rgb.label||'') + ' · ' + (rgb.pattern||'');
    sw.style.color = (rgb.color[0]+rgb.color[1]+rgb.color[2] > 360) ? '#06121a' : '#eef5ff';
  }
  document.getElementById('screen').src = '/expression/preview.png?ts=' + Date.now();
}
async function setExpression() {
  await api('/expression', {method:'POST', body: JSON.stringify({mode: mode.value, text: text.value || null, brightness: 0.72})});
  await refresh();
}
async function drive(linear, turn) { await api('/drive', {method:'POST', body: JSON.stringify({linear, turn, duration_ms: 350})}); await refresh(); }
async function stop() { await api('/stop', {method:'POST'}); await refresh(); }
async function live(on) { await api('/pip/live?on=' + on, {method:'POST'}); await refresh(); }
async function tick() { await api('/pip/arbiter/tick?allow_movement=false', {method:'POST'}); await refresh(); }
setInterval(refresh, 1500); refresh();
</script>
</body>
</html>"""
