from __future__ import annotations


def operator_panel_html() -> str:
    # Cyberpunk operator console for Pip. Served at GET / by the body service.
    # Self-contained (no build step): polls the live API and repaints. Designed to
    # be left open full-screen on the PC while Pip is running.
    return r"""<!doctype html>
<html lang='en'>
<head>
<meta charset='utf-8' />
<meta name='viewport' content='width=device-width, initial-scale=1' />
<title>PIP // CLEO ROVER MK1</title>
<link rel='preconnect' href='https://fonts.googleapis.com'>
<link href='https://fonts.googleapis.com/css2?family=Orbitron:wght@500;700;900&family=Share+Tech+Mono&display=swap' rel='stylesheet'>
<style>
:root{
  --bg:#04070e; --bg2:#070d18; --panel:rgba(8,16,28,.72); --edge:rgba(0,229,255,.30);
  --cyan:#00e5ff; --mag:#ff2bd6; --lime:#7CFF6B; --amber:#ffb020; --red:#ff3b5c;
  --ink:#dff3ff; --dim:#6f8bb0; --mono:'Share Tech Mono',ui-monospace,Consolas,monospace;
  --disp:'Orbitron',var(--mono);
}
*{box-sizing:border-box}
html,body{height:100%}
body{
  margin:0; background:
    radial-gradient(1200px 600px at 80% -10%, rgba(255,43,214,.10), transparent 60%),
    radial-gradient(1000px 700px at 0% 110%, rgba(0,229,255,.10), transparent 55%),
    var(--bg);
  color:var(--ink); font-family:var(--mono); letter-spacing:.02em;
  background-attachment:fixed;
}
body::before{ /* grid */
  content:''; position:fixed; inset:0; pointer-events:none; z-index:0; opacity:.35;
  background-image:linear-gradient(rgba(0,229,255,.05) 1px,transparent 1px),linear-gradient(90deg,rgba(0,229,255,.05) 1px,transparent 1px);
  background-size:38px 38px;
}
body::after{ /* scanlines */
  content:''; position:fixed; inset:0; pointer-events:none; z-index:9999;
  background:repeating-linear-gradient(transparent 0 2px,rgba(0,0,0,.16) 2px 3px); mix-blend-mode:overlay; opacity:.5;
}
.wrap{position:relative; z-index:1; max-width:1480px; margin:0 auto; padding:14px 18px 26px}
header{display:flex; align-items:center; gap:16px; padding:10px 16px; margin-bottom:14px;
  background:linear-gradient(90deg,rgba(0,229,255,.08),transparent 60%); border:1px solid var(--edge);
  border-radius:12px; box-shadow:0 0 30px rgba(0,229,255,.08), inset 0 0 24px rgba(0,229,255,.04);}
h1{font-family:var(--disp); font-weight:900; font-size:26px; margin:0; letter-spacing:.18em;
  background:linear-gradient(90deg,var(--cyan),var(--mag)); -webkit-background-clip:text; background-clip:text; color:transparent;
  text-shadow:0 0 18px rgba(0,229,255,.25);}
.tag{font-size:11px; color:var(--dim); letter-spacing:.25em; text-transform:uppercase}
.spacer{flex:1}
.conn{display:flex; align-items:center; gap:8px; font-size:12px; color:var(--dim); text-transform:uppercase; letter-spacing:.18em}
.dot{width:10px; height:10px; border-radius:50%; background:var(--red); box-shadow:0 0 10px var(--red); animation:pulse 1.4s infinite}
.dot.ok{background:var(--lime); box-shadow:0 0 12px var(--lime)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
.clock{font-family:var(--disp); font-size:15px; color:var(--cyan); text-shadow:0 0 10px rgba(0,229,255,.4)}

.kpis{display:grid; grid-template-columns:repeat(6,1fr); gap:12px; margin-bottom:14px}
.kpi{position:relative; background:var(--panel); border:1px solid var(--edge); border-radius:12px; padding:12px 14px; overflow:hidden}
.kpi::before{content:''; position:absolute; left:0; top:0; bottom:0; width:3px; background:var(--cyan); box-shadow:0 0 12px var(--cyan)}
.kpi .l{font-size:10px; letter-spacing:.22em; color:var(--dim); text-transform:uppercase}
.kpi .v{font-family:var(--disp); font-weight:700; font-size:24px; margin-top:4px; line-height:1}
.kpi .s{font-size:11px; color:var(--dim); margin-top:4px; min-height:14px}
.kpi.mag::before{background:var(--mag); box-shadow:0 0 12px var(--mag)}
.kpi.lime::before{background:var(--lime); box-shadow:0 0 12px var(--lime)}
.kpi.amber::before{background:var(--amber); box-shadow:0 0 12px var(--amber)}

.cols{display:grid; grid-template-columns:300px 1fr 360px; gap:14px; align-items:start}
@media(max-width:1200px){.cols{grid-template-columns:1fr 1fr}.kpis{grid-template-columns:repeat(3,1fr)}}
@media(max-width:760px){.cols{grid-template-columns:1fr}.kpis{grid-template-columns:repeat(2,1fr)}}
.panel{background:var(--panel); border:1px solid var(--edge); border-radius:12px; padding:14px; margin-bottom:14px;
  box-shadow:inset 0 0 30px rgba(0,40,70,.18)}
.panel h2{font-family:var(--disp); font-weight:700; font-size:12px; letter-spacing:.24em; text-transform:uppercase;
  color:var(--cyan); margin:0 0 12px; padding-bottom:8px; border-bottom:1px solid rgba(0,229,255,.18); display:flex; gap:8px; align-items:center}
.panel h2 .mk{color:var(--mag)}

.orb{width:150px; height:150px; border-radius:50%; margin:6px auto 14px; position:relative;
  background:radial-gradient(circle at 38% 32%, #fff6, #0000 42%), var(--orbc,#0a4);
  box-shadow:0 0 50px var(--orbc,#0a4), inset 0 0 40px rgba(0,0,0,.5); animation:breathe 3.4s ease-in-out infinite}
@keyframes breathe{0%,100%{transform:scale(.96); filter:brightness(.9)}50%{transform:scale(1.04); filter:brightness(1.18)}}
.orb.pulse{animation:opulse 1s ease-in-out infinite}
@keyframes opulse{0%,100%{transform:scale(.93)}50%{transform:scale(1.07)}}
.orb.flash{animation:oflash .5s steps(2) infinite}
@keyframes oflash{0%{filter:brightness(1.4)}50%{filter:brightness(.6)}}
.moodlabel{text-align:center; font-family:var(--disp); letter-spacing:.16em; text-transform:uppercase; font-size:14px}
.moodsub{text-align:center; font-size:11px; color:var(--dim); margin-top:2px}

.bar{height:9px; border-radius:6px; background:rgba(255,255,255,.06); overflow:hidden; margin:6px 0 2px; border:1px solid rgba(255,255,255,.06)}
.bar > i{display:block; height:100%; width:0%; border-radius:6px; transition:width .5s ease}
.barrow{font-size:11px; color:var(--dim); display:flex; justify-content:space-between; text-transform:uppercase; letter-spacing:.12em}
.fill-cy{background:linear-gradient(90deg,#0aa,var(--cyan)); box-shadow:0 0 10px rgba(0,229,255,.6)}
.fill-mg{background:linear-gradient(90deg,#a18,var(--mag)); box-shadow:0 0 10px rgba(255,43,214,.5)}
.fill-li{background:linear-gradient(90deg,#5a3,var(--lime)); box-shadow:0 0 10px rgba(124,255,107,.5)}
.fill-am{background:linear-gradient(90deg,#a70,var(--amber)); box-shadow:0 0 10px rgba(255,176,32,.5)}

.grid2{display:grid; grid-template-columns:1fr 1fr; gap:10px}
.cell{background:rgba(255,255,255,.035); border:1px solid rgba(255,255,255,.05); border-radius:9px; padding:9px 10px}
.cell .l{font-size:10px; letter-spacing:.18em; color:var(--dim); text-transform:uppercase}
.cell .v{font-family:var(--disp); font-size:16px; margin-top:3px; color:var(--ink)}

.range{position:relative; height:26px; border-radius:8px; background:linear-gradient(90deg,rgba(255,59,92,.25),rgba(255,176,32,.18) 25%,rgba(124,255,107,.16) 55%); border:1px solid rgba(255,255,255,.08); overflow:hidden}
.range > .needle{position:absolute; top:-2px; bottom:-2px; width:3px; background:#fff; box-shadow:0 0 10px #fff; transition:left .4s ease}
.range > .stop{position:absolute; top:0; bottom:0; width:2px; background:var(--red); box-shadow:0 0 8px var(--red)}
.range > .lab{position:absolute; right:8px; top:4px; font-size:12px; color:#fff; font-family:var(--disp)}

.leds{display:flex; gap:8px; justify-content:space-between; margin-top:4px}
.led{flex:1; text-align:center; padding:8px 0; border-radius:8px; border:1px solid rgba(255,255,255,.08); font-size:11px; letter-spacing:.1em; color:var(--dim); background:rgba(255,255,255,.03)}
.led.hot{color:#04121a; background:var(--lime); box-shadow:0 0 14px var(--lime); border-color:transparent; font-weight:700}
.led.warn{color:#1a0f04; background:var(--amber); box-shadow:0 0 14px var(--amber); border-color:transparent}

.pill{display:inline-flex; align-items:center; gap:6px; padding:3px 10px; border-radius:999px; font-size:11px; letter-spacing:.14em; text-transform:uppercase}
.pill.ok{background:rgba(124,255,107,.15); color:var(--lime); border:1px solid rgba(124,255,107,.35)}
.pill.bad{background:rgba(255,59,92,.15); color:var(--red); border:1px solid rgba(255,59,92,.35)}
.pill.warn{background:rgba(255,176,32,.14); color:var(--amber); border:1px solid rgba(255,176,32,.35)}
.blockers{color:var(--amber); font-size:12px; margin-top:8px; min-height:14px}

.log{font-size:12px; line-height:1.5; max-height:230px; overflow:auto}
.log .ln{padding:3px 0; border-bottom:1px dashed rgba(255,255,255,.06); color:#bcd}
.log .ln::before{content:'> '; color:var(--cyan)}
.diary{font-size:13px; line-height:1.6; color:#cfe6ff}
.diary .mood{color:var(--mag); font-family:var(--disp); letter-spacing:.06em; margin-bottom:8px; display:block}
.tasks .row{display:flex; justify-content:space-between; gap:8px; font-size:12px; padding:5px 0; border-bottom:1px dashed rgba(255,255,255,.06)}
.tasks .t{color:var(--cyan)} .tasks .r{color:var(--dim); flex:1; text-align:left; padding-left:8px} .tasks .a{color:var(--dim)}
.move0{color:var(--dim)} .move1{color:var(--amber)}

.alerts{min-height:24px}
.alert{background:rgba(255,59,92,.12); border:1px solid rgba(255,59,92,.4); border-radius:8px; padding:8px 10px; margin:6px 0; font-size:12px; color:#ffd0d8}
.noalert{color:var(--dim); font-size:12px}

.controls{display:flex; flex-wrap:wrap; gap:10px; align-items:center}
button{font-family:var(--mono); background:rgba(0,229,255,.06); color:var(--ink); border:1px solid var(--edge); border-radius:9px; padding:9px 14px; cursor:pointer; letter-spacing:.1em; text-transform:uppercase; font-size:12px; transition:.12s}
button:hover{border-color:var(--cyan); box-shadow:0 0 14px rgba(0,229,255,.3); transform:translateY(-1px)}
button.live{border-color:rgba(124,255,107,.5); color:var(--lime); background:rgba(124,255,107,.06)}
button.stop{border-color:rgba(255,59,92,.6); color:#fff; background:rgba(255,59,92,.22); font-weight:700}
button.stop:hover{box-shadow:0 0 18px rgba(255,59,92,.5)}
details{margin-top:10px} summary{cursor:pointer; color:var(--amber); font-size:12px; letter-spacing:.12em}
.foot{display:flex; gap:14px; align-items:center; color:var(--dim); font-size:11px; margin-top:10px; letter-spacing:.12em}
img.screen{width:100%; max-width:240px; border-radius:10px; border:1px solid rgba(0,229,255,.25); display:block; margin:0 auto; opacity:.9}
</style>
</head>
<body>
<div class='wrap'>
  <header>
    <div>
      <h1>PIP</h1>
      <div class='tag'>Cleo Rover MK1 · living-being console</div>
    </div>
    <div class='spacer'></div>
    <div class='clock' id='clock'>--:--:--</div>
    <div class='conn'><span class='dot' id='cdot'></span><span id='cstat'>linking</span></div>
  </header>

  <section class='kpis' id='kpis'></section>

  <div class='cols'>
    <!-- LEFT: soul + feelings -->
    <div>
      <div class='panel'>
        <h2><span class='mk'>//</span> Soul</h2>
        <div class='orb' id='orb'></div>
        <div class='moodlabel' id='moodlabel'>—</div>
        <div class='moodsub' id='moodsub'>—</div>
        <div id='readyline' style='text-align:center;margin-top:10px'></div>
        <div class='blockers' id='blockers'></div>
      </div>
      <div class='panel'>
        <h2><span class='mk'>//</span> Feelings</h2>
        <div id='feelings'></div>
      </div>
      <div class='panel'>
        <h2><span class='mk'>//</span> Vision</h2>
        <img class='screen' id='screen' src='/expression/preview.png?ts=0' onerror="this.style.display='none'"/>
      </div>
    </div>

    <!-- CENTER: sensors + telemetry -->
    <div>
      <div class='panel'>
        <h2><span class='mk'>//</span> Forward range</h2>
        <div class='range'><div class='stop' id='rstop'></div><div class='needle' id='rneedle'></div><div class='lab' id='rlab'>— cm</div></div>
        <div class='barrow' style='margin-top:6px'><span>0</span><span>stop <span id='stopcm'>—</span></span><span>250cm</span></div>
      </div>
      <div class='panel'>
        <h2><span class='mk'>//</span> Cliff / line IR</h2>
        <div class='leds' id='lineleds'></div>
        <div class='leds' id='bumpleds' style='margin-top:8px'></div>
      </div>
      <div class='panel'>
        <h2><span class='mk'>//</span> Telemetry</h2>
        <div class='grid2' id='telemetry'></div>
      </div>
      <div class='panel'>
        <h2><span class='mk'>//</span> ADC channels (V)</h2>
        <div id='adc' class='grid2'></div>
      </div>
    </div>

    <!-- RIGHT: diary + interrupts + tasks + control -->
    <div>
      <div class='panel'>
        <h2><span class='mk'>//</span> Interrupts</h2>
        <div class='alerts' id='alerts'></div>
      </div>
      <div class='panel'>
        <h2><span class='mk'>//</span> Inner life</h2>
        <div class='diary' id='diary'>—</div>
      </div>
      <div class='panel'>
        <h2><span class='mk'>//</span> Recent actions</h2>
        <div class='tasks' id='tasks'></div>
      </div>
      <div class='panel'>
        <h2><span class='mk'>//</span> Control</h2>
        <div class='controls'>
          <button class='live' onclick='live(true)'>Go Live</button>
          <button onclick='live(false)'>Pause</button>
          <button onclick='tick()'>Arbiter Tick</button>
          <button class='stop' onclick='estop()'>■ STOP</button>
        </div>
        <details>
          <summary>⚠ manual drive (armed only)</summary>
          <div class='controls' style='margin-top:8px'>
            <button onclick='drive(0.22,0)'>▲ fwd</button>
            <button onclick='drive(-0.22,0)'>▼ back</button>
            <button onclick='drive(0,-0.32)'>◄ left</button>
            <button onclick='drive(0,0.32)'>► right</button>
          </div>
        </details>
        <div class='foot'><span id='ver'></span><span id='upd'></span></div>
      </div>
    </div>
  </div>
</div>

<script>
const $=id=>document.getElementById(id);
let okCount=0;
async function j(p,opts){ const r=await fetch(p,Object.assign({headers:{'content-type':'application/json'}},opts||{})); if(!r.ok) throw new Error(p); return r.json(); }
function pct(x){ return Math.max(0,Math.min(100,Math.round((x||0)*100))); }
function ago(ts){ if(!ts) return ''; const s=Math.max(0,Math.floor(Date.now()/1000-ts)); if(s<60) return s+'s'; if(s<3600) return Math.floor(s/60)+'m'; return Math.floor(s/3600)+'h'; }
function bar(label,val,cls){ return `<div class='barrow'><span>${label}</span><span>${val}%</span></div><div class='bar'><i class='${cls}' style='width:${val}%'></i></div>`; }

function setConn(ok){ const d=$('cdot'),s=$('cstat'); if(ok){d.classList.add('ok'); s.textContent='online';} else {d.classList.remove('ok'); s.textContent='offline';} }

async function fast(){
  let h,se,st;
  try{ [h,se,st]=await Promise.all([j('/health/composite'),j('/sensors').catch(()=>({})),j('/status').catch(()=>({}))]); setConn(true); okCount++; }
  catch(e){ setConn(false); return; }
  const b=h.battery||{},f=h.feelings||{},m=h.movement||{},a=h.arbiter||{},n=h.nav||{},d=h.degradation||{},sub=h.subsystems||{},rgb=h.rgb_affect||{},id=h.identity||{};
  // KPI tiles
  const soc=b.soc_percent==null?'—':Math.round(b.soc_percent)+'%';
  const battClass = (b.critical?'kpi':(b.warn?'kpi amber':'kpi'));
  $('kpis').innerHTML=
    `<div class='${b.critical?"kpi mag":(b.warn?"kpi amber":"kpi")}'><div class='l'>Battery</div><div class='v'>${soc}${b.charging?' ⚡':''}</div><div class='s'>${(b.voltage??'—')} V · ${b.recommendation||''}</div></div>`+
    `<div class='kpi lime'><div class='l'>Energy</div><div class='v'>${pct(f.energy)}%</div><div class='s'>conf ${pct(f.confidence)}% · bored ${pct(f.boredom)}%</div></div>`+
    `<div class='kpi mag'><div class='l'>Mood</div><div class='v'>${f.mood||'—'}</div><div class='s'>${rgb.label||''} · ${rgb.pattern||''}</div></div>`+
    `<div class='kpi'><div class='l'>Behavior</div><div class='v' style='font-size:18px'>${a.would_choose||'—'}</div><div class='s'>${a.reason||''}</div></div>`+
    `<div class='kpi amber'><div class='l'>Capability</div><div class='v' style='font-size:18px'>${d.level||'—'}</div><div class='s'>${(d.reasons||[]).join(', ')}</div></div>`+
    `<div class='kpi ${h.ready_to_move?"lime":"mag"}'><div class='l'>Drive</div><div class='v' style='font-size:16px'>${h.ready_to_move?'READY':'LOCKED'}</div><div class='s'>${sub.motors_armed?'motors armed':'motors disarmed'}</div></div>`;
  // soul orb
  const c=rgb.color||[10,160,90]; const orb=$('orb');
  orb.style.setProperty('--orbc',`rgb(${c[0]},${c[1]},${c[2]})`);
  orb.className='orb'+(rgb.pattern==='pulse'?' pulse':(rgb.pattern==='flash'?' flash':''));
  $('moodlabel').textContent=(f.mood||'—');
  $('moodsub').textContent=(rgb.label||'')+' · '+(rgb.pattern||'breathe');
  $('readyline').innerHTML=`<span class='pill ${h.ready_to_move?"ok":"bad"}'>${h.ready_to_move?'ready to move':'not ready'}</span>`;
  $('blockers').textContent=(h.blockers&&h.blockers.length)?('⛔ '+h.blockers.join(' · ')):'';
  // feelings bars
  $('feelings').innerHTML=
    bar('energy',pct(f.energy),'fill-li')+bar('curiosity',pct(f.curiosity),'fill-cy')+
    bar('attention',pct(f.attention),'fill-cy')+bar('confidence',pct(f.confidence),'fill-mg')+
    bar('boredom',pct(f.boredom),'fill-am');
  // forward range
  const fd=(se.front_distance_cm!=null)?se.front_distance_cm:(st.range_state?st.range_state.median_cm:null);
  const stopcm=se.front_stop_distance_cm||(st.safety?st.safety.front_stop_distance_cm:18);
  const max=250; const p=fd==null?0:Math.min(100,fd/max*100);
  $('rneedle').style.left=p+'%'; $('rstop').style.left=Math.min(100,stopcm/max*100)+'%';
  $('rlab').textContent=(fd==null?'—':Math.round(fd))+' cm'; $('stopcm').textContent=Math.round(stopcm);
  // line + bumpers
  const ls=se.line_sensors||{}; const lab={left:'L',center:'C',right:'R'};
  $('lineleds').innerHTML=['left','center','right'].map(k=>`<div class='led ${ls[k]?'warn':''}'>IR ${lab[k]} ${ls[k]??'—'}</div>`).join('');
  const bp=se.bumpers||{};
  $('bumpleds').innerHTML=['left','right'].map(k=>`<div class='led ${bp[k]?'warn':''}'>BUMP ${k[0].toUpperCase()} ${bp[k]??'—'}</div>`).join('');
  // telemetry
  const pan=(st.turret?st.turret.pan_deg:(sub.turret_pan));
  $('telemetry').innerHTML=
    cell('Place',n.current_place||'unmapped')+
    cell('Topo',(n.topo?`${n.topo.places||0} pl · ${n.topo.transitions||0} tr`:'—'))+
    cell('Goal',h.goal?(h.goal.kind+':'+(h.goal.target||'')):'none')+
    cell('Grant',m.owner||(m.permitted?'permitted':'none'))+
    cell('Turret pan',pan==null?'—':Math.round(pan)+'°')+
    cell('Person',a.context?(a.context.person_present?'present':'none'):(sub.person_present?'present':'—'))+
    cell('Mind',sub.mind_configured?'connected':'offline')+
    cell('Mode',id.mode||'—');
  // adc
  const adc=se.adc_channels||{};
  $('adc').innerHTML=Object.keys(adc).length?Object.entries(adc).map(([k,v])=>cell('ch'+k,(+v).toFixed(2))).join(''):"<div class='cell'><div class='l'>adc</div><div class='v'>—</div></div>";
  $('ver').textContent='v'+(id.version||'')+' · soul '+(id.soul_version||'');
  $('upd').textContent='· upd '+new Date().toLocaleTimeString();
  $('screen').src='/expression/preview.png?ts='+Date.now();
}
function cell(l,v){ return `<div class='cell'><div class='l'>${l}</div><div class='v'>${v}</div></div>`; }

async function slow(){
  try{ const d=await j('/life/diary'); const lines=(d.lines||[]); $('diary').innerHTML=`<span class='mood'>${d.mood_line||''}</span>`+lines.slice(1).map(x=>`<div>${x}</div>`).join(''); }catch(e){}
  try{ const it=await j('/pip/interrupts'); const arr=it.interrupts||[]; $('alerts').innerHTML=arr.length?arr.map(x=>`<div class='alert'>⚠ ${x.kind||x.type||'interrupt'} — ${x.reason||x.message||JSON.stringify(x).slice(0,80)}</div>`).join(''):"<div class='noalert'>no pending interrupts</div>"; }catch(e){}
  try{ const t=await j('/tasks/history?limit=8'); const hs=t.history||[]; $('tasks').innerHTML=hs.map(r=>`<div class='row'><span class='t'>${(r.task||'').replace('arbiter:','')}</span><span class='r'>${r.reason||''}</span><span class='a move${r.did_move?1:0}'>${r.did_move?'⊳':'·'} ${ago(r.at)}</span></div>`).join('')||"<div class='noalert'>no actions yet</div>"; }catch(e){}
}
function tickClock(){ $('clock').textContent=new Date().toLocaleTimeString(); }
async function live(on){ try{await j('/pip/live?on='+on,{method:'POST'});}catch(e){} fast(); }
async function tick(){ try{await j('/pip/arbiter/tick?allow_movement=false',{method:'POST'});}catch(e){} fast(); }
async function estop(){ try{await j('/stop',{method:'POST'});}catch(e){} fast(); }
async function drive(linear,turn){ try{await j('/drive',{method:'POST',body:JSON.stringify({linear,turn,duration_ms:350})});}catch(e){} fast(); }
setInterval(tickClock,1000); tickClock();
setInterval(fast,1500); fast();
setInterval(slow,4000); slow();
</script>
</body>
</html>"""
