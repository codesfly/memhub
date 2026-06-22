"""Single-page web viewer (inline HTML + vanilla JS, no build step)."""

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>memhub</title>
<style>
 body{font:14px/1.5 -apple-system,system-ui,sans-serif;margin:0;background:#0f1115;color:#e6e6e6}
 header{padding:14px 20px;background:#161a22;border-bottom:1px solid #262b36;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
 h1{font-size:16px;margin:0 12px 0 0;color:#7aa2f7}
 input:not([type=checkbox]),select,button{background:#0f1115;color:#e6e6e6;border:1px solid #2a3140;border-radius:6px;padding:6px 9px;font-size:13px}
 button{cursor:pointer}
 button:hover{border-color:#56607a}
 input[type=search]{flex:1;min-width:180px}
 .settings{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-left:auto}
 .toggle{display:flex;align-items:center;gap:5px;color:#c8cfdf;font-size:13px}
 .status{min-width:120px;color:#8b93a7;font-size:12px}
 main{padding:16px 20px;max-width:900px;margin:0 auto}
 .card{background:#161a22;border:1px solid #262b36;border-radius:8px;padding:12px 14px;margin:10px 0}
 .meta{font-size:12px;color:#8b93a7;display:flex;gap:10px;margin-bottom:6px;align-items:center;flex-wrap:wrap}
 .kind{padding:1px 7px;border-radius:10px;background:#1f2937;color:#9ece6a;font-size:11px}
 .content{white-space:pre-wrap;word-break:break-word}
 .del{margin-left:auto;background:none;border:1px solid #3a2230;color:#f7768e;border-radius:6px;padding:3px 9px;cursor:pointer}
 .del:hover{background:#2a1620}
 .empty{color:#8b93a7;text-align:center;padding:40px}
</style></head>
<body>
<header>
 <h1>memhub</h1>
 <input id="q" type="search" placeholder="search memories…">
 <input id="project" placeholder="project filter">
 <select id="kind">
  <option value="">all kinds</option>
  <option>decision</option><option>fact</option><option>convention</option>
  <option>snippet</option><option>note</option><option>raw</option>
 </select>
 <div class="settings">
  <select id="capture-mode" title="capture mode">
   <option value="off">capture off</option>
   <option value="raw">raw capture</option>
   <option value="llm">LLM extract</option>
  </select>
  <label class="toggle" title="inject memories at session start"><input id="inject-enabled" type="checkbox">inject</label>
  <button id="clear-pending" title="clear pending captures">clear pending</button>
  <span id="settings-status" class="status"></span>
 </div>
</header>
<main id="list"><div class="empty">loading…</div></main>
<script>
const el = id => document.getElementById(id);
const esc = s => (s||"").replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function status(msg){ el('settings-status').textContent = msg || ''; }
function settingsLabel(data){
 const mode = data.capture_mode === 'llm' ? 'LLM' : data.capture_mode === 'off' ? 'capture off' : 'raw';
 return `${mode} · inject ${data.inject_enabled ? 'on' : 'off'}`;
}
async function loadSettings(){
 try{
  const data = await (await fetch('/settings')).json();
  el('capture-mode').value = data.capture_mode || 'raw';
  el('inject-enabled').checked = !!data.inject_enabled;
  status(settingsLabel(data));
 }catch(e){ status('settings unavailable'); }
}
async function saveSettings(patch){
 status('saving…');
 try{
  const r = await fetch('/settings',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(patch)});
  const data = await r.json();
  if(!r.ok) throw new Error(data.error||'save failed');
  el('capture-mode').value = data.capture_mode || 'raw';
  el('inject-enabled').checked = !!data.inject_enabled;
  status(settingsLabel(data));
 }catch(e){ status('save failed'); }
}
async function clearPending(){
 if(!confirm('Delete all pending captures?'))return;
 status('clearing…');
 try{
  const data = await (await fetch('/capture/pending',{method:'DELETE'})).json();
  status(`removed ${data.deleted||0}`);
 }catch(e){ status('clear failed'); }
}
async function load(){
 const q = el('q').value.trim(), project = el('project').value.trim(), kind = el('kind').value;
 let url, key;
 if(q){ url = `/search?query=${encodeURIComponent(q)}&scope=all&limit=100`; key='results'; }
 else { const p=new URLSearchParams(); if(project)p.set('project',project); if(kind)p.set('kind',kind); p.set('limit','100'); url=`/memories?${p}`; key='memories'; }
 let data; try{ data = await (await fetch(url)).json(); }catch(e){ el('list').innerHTML='<div class="empty">service unreachable</div>'; return; }
 let items = data[key]||[];
 if(q && kind) items = items.filter(m=>m.kind===kind);
 if(q && project) items = items.filter(m=>m.project===project);
 if(!items.length){ el('list').innerHTML='<div class="empty">no memories</div>'; return; }
 el('list').innerHTML = items.map(m=>`<div class="card">
   <div class="meta"><span class="kind">${esc(m.kind)}</span>
     <span>${esc(m.project||'—')}</span><span>${esc(m.agent||'')}</span>
     <span>${new Date((m.created_at||0)*1000).toLocaleString()}</span>
     <button class="del" data-id="${esc(String(m.id))}">delete</button></div>
   <div class="content">${esc(m.content)}</div></div>`).join('');
 document.querySelectorAll('.del').forEach(b=>b.onclick=async()=>{
   if(!confirm('Delete this memory?'))return;
   await fetch(`/memories/${b.dataset.id}`,{method:'DELETE'}); load();
 });
}
['q','project','kind'].forEach(id=>el(id).addEventListener('input',()=>{clearTimeout(window._t);window._t=setTimeout(load,250)}));
el('capture-mode').addEventListener('change',()=>saveSettings({capture_mode:el('capture-mode').value}));
el('inject-enabled').addEventListener('change',()=>saveSettings({inject_enabled:el('inject-enabled').checked}));
el('clear-pending').addEventListener('click', clearPending);
loadSettings();
load();
</script>
</body></html>"""
