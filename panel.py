import os, asyncio, collections, shutil, urllib.request, json, time, logging, sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, Response, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Suppress standard Uvicorn logs to keep Docker console clean
logging.getLogger("uvicorn.access").setLevel(logging.CRITICAL)
logging.getLogger("uvicorn.error").setLevel(logging.CRITICAL)

BASE_DIR = os.environ.get("SERVER_DIR", os.path.abspath("/app"))
PLUGINS_DIR = os.path.join(BASE_DIR, "plugins")
mc_process = None
output_history = collections.deque(maxlen=500)
connected_clients = set()
PASS_SECRET = os.environ.get("PASS", "admin")

async def stream_output(pipe):
    while True:
        line = await pipe.readline()
        if not line: break
        txt = line.decode('utf-8', errors='replace').rstrip()
        output_history.append(txt)
        dead = set()
        for c in connected_clients:
            try: await c.send_text(txt)
            except: dead.add(c)
        connected_clients.difference_update(dead)

async def startup_sequence():
    # 1. Background Download
    if os.environ.get("FOLDER_URL"):
        output_history.append("\u23f3 [Panel] Starting Google Drive sync...")
        proc = await asyncio.create_subprocess_exec(
            "python3", "download_world.py",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=BASE_DIR
        )
        await stream_output(proc.stdout)
        await proc.wait()
        output_history.append("\u2705 [Panel] World check finished.")
    
    # 2. Boot MC
    await boot_mc()

async def boot_mc():
    global mc_process
    if mc_process and mc_process.returncode is None: return
    jar = os.path.join(BASE_DIR, "purpur.jar")
    if not os.path.exists(jar):
        output_history.append("\u26a0 [Panel] purpur.jar not found. Upload it via Files.")
        return

    output_history.append("\U0001f680 [Panel] Starting Minecraft server...")
    mc_process = await asyncio.create_subprocess_exec(
        "java", "-Xmx4G", "-Xms1G", "-Dfile.encoding=UTF-8",
        "-XX:+UseG1GC", "-jar", jar, "--nogui",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=BASE_DIR
    )
    asyncio.create_task(stream_output(mc_process.stdout))

@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(PLUGINS_DIR, exist_ok=True)
    asyncio.create_task(startup_sequence())
    yield

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# ─────────────────────────────────────────────
# HTML GUI
# ─────────────────────────────────────────────
HTML_CONTENT = r"""<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>MC Panel</title>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{--f:-apple-system,BlinkMacSystemFont,'SF Pro Display',system-ui,sans-serif;--mono:'JetBrains Mono',monospace;--r:12px;--r-sm:8px;--dur:0.18s}
[data-theme=dark]{--bg:#000;--s1:#1C1C1E;--s2:#2C2C2E;--s3:#3A3A3C;--bd:rgba(255,255,255,.08);--t1:#fff;--t2:rgba(255,255,255,.55);--t3:rgba(255,255,255,.22);--acc:#32D74B;--acc-bg:rgba(50,215,75,.12);--red:#FF453A;--yel:#FFD60A;--blu:#0A84FF;--glass:rgba(28,28,30,.8);--sh:0 8px 40px rgba(0,0,0,.7)}
[data-theme=light]{--bg:#EBEBEB;--s1:#fff;--s2:#F5F5F7;--s3:#E5E5EA;--bd:rgba(0,0,0,.09);--t1:#1C1C1E;--t2:rgba(0,0,0,.5);--t3:rgba(0,0,0,.22);--acc:#28CD41;--acc-bg:rgba(40,205,65,.1);--red:#FF3B30;--yel:#FF9F0A;--blu:#007AFF;--glass:rgba(255,255,255,.85);--sh:0 8px 40px rgba(0,0,0,.12)}
html,body{height:100%;height:100dvh} body{font-family:var(--f);background:var(--bg);color:var(--t1);display:flex;flex-direction:column;overflow:hidden;-webkit-font-smoothing:antialiased;}
::-webkit-scrollbar{width:5px;height:5px} ::-webkit-scrollbar-thumb{background:var(--s3);border-radius:99px}
.toolbar{height:52px;background:var(--glass);backdrop-filter:blur(24px);border-bottom:1px solid var(--bd);display:flex;align-items:center;padding:0 16px;gap:14px;position:relative;z-index:100;flex-shrink:0}
.tb-title{position:absolute;left:50%;transform:translateX(-50%);font-size:13px;font-weight:600;display:flex;align-items:center;gap:7px}
.pip{width:7px;height:7px;border-radius:50%;background:var(--acc);box-shadow:0 0 6px var(--acc);animation:pip 2.5s ease-in-out infinite}
@keyframes pip{0%,100%{opacity:1}50%{opacity:.3}}
.icon-btn{width:30px;height:30px;border-radius:var(--r-sm);border:1px solid var(--bd);background:var(--s1);color:var(--t2);display:flex;align-items:center;justify-content:center;cursor:pointer;transition:all var(--dur)}
.icon-btn:hover{color:var(--t1);background:var(--s2)}
.app-body{flex:1;display:flex;overflow:hidden;min-height:0}
.sidebar{width:192px;background:var(--glass);backdrop-filter:blur(20px);border-right:1px solid var(--bd);display:flex;flex-direction:column;padding:10px 8px 16px;gap:2px}
.nav-item{display:flex;align-items:center;gap:9px;padding:8px 10px;border-radius:var(--r-sm);font-size:13px;font-weight:500;color:var(--t2);cursor:pointer;border:none;background:none;text-align:left}
.nav-item:hover{background:var(--s2);color:var(--t1)} .nav-item.active{background:var(--acc-bg);color:var(--acc)}
.main{flex:1;display:flex;flex-direction:column;overflow:hidden}
.tab-pane{display:none;flex:1;flex-direction:column;padding:14px;overflow:hidden} .tab-pane.active{display:flex}
.win{flex:1;display:flex;flex-direction:column;background:var(--s1);border:1px solid var(--bd);border-radius:var(--r);overflow:hidden;box-shadow:var(--sh);position:relative}
.win-bar{height:40px;background:var(--s2);border-bottom:1px solid var(--bd);display:flex;align-items:center;padding:0 14px;gap:10px}
.log-out{flex:1;overflow-y:auto;padding:12px 14px;font-family:var(--mono);font-size:11.5px;line-height:1.65;color:var(--t2)}
.cmd-bar{display:flex;align-items:center;gap:8px;padding:8px 10px;background:var(--s2);border-top:1px solid var(--bd)}
.cmd-in{flex:1;background:var(--s1);border:1px solid var(--bd);border-radius:var(--r-sm);padding:6px 12px;font-family:var(--mono);font-size:12px;color:var(--t1);outline:none}
.cmd-in:focus{border-color:var(--acc)}
.file-row{display:flex;align-items:center;gap:10px;padding:9px 16px;border-bottom:1px solid var(--bd);cursor:pointer}
.file-row:hover{background:var(--s2)} .file-row:hover .row-acts{opacity:1}
.file-name{flex:1;font-size:13px;font-weight:500}
.row-acts{display:flex;gap:5px;opacity:0;transition:opacity .2s}
.f-btn{background:none;border:none;color:var(--t2);padding:4px;border-radius:6px;cursor:pointer}
.f-btn:hover{background:var(--s3);color:var(--t1)}
.f-del:hover{background:rgba(255,59,48,.1);color:var(--red)}
.pl-grid{flex:1;overflow-y:auto;padding:14px;display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px}
.pl-card{background:var(--s2);border:1px solid var(--bd);border-radius:var(--r);padding:14px;display:flex;flex-direction:column;gap:10px}
.mc-ctrl-btn{padding:5px 12px;border:1px solid var(--bd);background:var(--s1);color:var(--t1);border-radius:var(--r-sm);font-size:11px;font-weight:600;cursor:pointer}
.mc-ctrl-btn:hover{background:var(--s3)}
.toast{position:fixed;bottom:20px;right:14px;background:var(--glass);backdrop-filter:blur(20px);border:1px solid var(--bd);border-radius:var(--r);padding:10px 14px;display:flex;align-items:center;gap:9px;font-size:13px;font-weight:500;box-shadow:var(--sh);z-index:9999;transform:translateY(10px);opacity:0;transition:all .3s}
.toast.show{transform:translateY(0);opacity:1}
</style>
</head>
<body>
<div id="app" style="display:none; height:100%; flex-direction:column;">
<header class="toolbar">
  <div style="display:flex;gap:6px"><div style="width:12px;height:12px;border-radius:50%;background:var(--red)"></div><div style="width:12px;height:12px;border-radius:50%;background:var(--yel)"></div><div style="width:12px;height:12px;border-radius:50%;background:var(--acc)"></div></div>
  <div class="tb-title"><div class="pip" id="pip"></div>Minecraft Panel</div>
  <div style="margin-left:auto"><button class="icon-btn" onclick="toggleTheme()"><svg width="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg></button></div>
</header>
<div class="app-body">
  <aside class="sidebar">
    <div style="font-size:10px;font-weight:700;color:var(--t3);padding:10px;text-transform:uppercase">Navigation</div>
    <button class="nav-item active" id="d-console" onclick="tab('console')">Console</button>
    <button class="nav-item" id="d-files" onclick="tab('files')">Files</button>
    <button class="nav-item" id="d-plugins" onclick="tab('plugins')">Plugins</button>
  </aside>
  <main class="main">
    <div class="tab-pane active" id="tab-console">
      <div class="win">
        <div class="win-bar">
          <div style="flex:1;font-size:12px;font-weight:600;color:var(--t2)">Live Server Log</div>
          <button class="mc-ctrl-btn" onclick="mcCtrl('start')" style="color:var(--acc)">Start</button>
          <button class="mc-ctrl-btn" onclick="mcCtrl('stop')">Stop</button>
          <button class="mc-ctrl-btn" onclick="mcCtrl('kill')" style="color:var(--red)">Kill</button>
        </div>
        <div class="log-out" id="logs"></div>
        <div class="cmd-bar"><input class="cmd-in" id="cmd" type="text" placeholder="Type command..." onkeydown="if(event.key==='Enter')sendCmd()"></div>
      </div>
    </div>
    <div class="tab-pane" id="tab-files">
      <div class="win">
        <div class="win-bar">
          <div id="path-bread" style="flex:1;font-size:12px;overflow-x:auto;white-space:nowrap;display:flex;gap:5px"></div>
          <div id="disk-usg" style="font-size:11px;color:var(--t3);margin-right:10px"></div>
          <button class="icon-btn" onclick="document.getElementById('up-in').click()"><svg width="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg></button>
          <input type="file" id="up-in" style="display:none" onchange="uploadFile()">
        </div>
        <div style="flex:1;overflow-y:auto" id="file-list"></div>
      </div>
    </div>
    <div class="tab-pane" id="tab-plugins">
      <div class="win">
        <div style="padding:12px 14px;background:var(--s2);border-bottom:1px solid var(--bd);display:flex;gap:10px;flex-wrap:wrap">
          <select id="pl-loader" style="padding:6px;border-radius:6px;background:var(--s1);color:var(--t1);border:1px solid var(--bd)"><option value="paper">Paper/Spigot</option><option value="purpur">Purpur</option></select>
          <select id="pl-ver" style="padding:6px;border-radius:6px;background:var(--s1);color:var(--t1);border:1px solid var(--bd)">
             <option value="1.20.4">1.20.4</option><option value="1.20.1">1.20.1</option><option value="1.19.4">1.19.4</option>
          </select>
          <input id="pl-q" type="text" placeholder="Search Modrinth..." style="flex:1;padding:6px;border-radius:6px;background:var(--s1);color:var(--t1);border:1px solid var(--bd)" onkeydown="if(event.key==='Enter')searchPlugins()">
          <button onclick="searchPlugins()" class="mc-ctrl-btn" style="background:var(--blu);color:#fff;border:none">Search</button>
        </div>
        <div class="pl-grid" id="pl-list"></div>
      </div>
    </div>
  </main>
</div>
<div id="ed-mod" style="display:none;position:fixed;inset:0;background:var(--bg);z-index:999;flex-direction:column">
  <div class="toolbar" style="justify-content:space-between">
    <div id="ed-title" style="font-size:13px;font-weight:600">Editing...</div>
    <div style="display:flex;gap:10px">
      <button class="mc-ctrl-btn" onclick="saveEd()" style="background:var(--acc);color:#fff;border:none">Save</button>
      <button class="mc-ctrl-btn" onclick="document.getElementById('ed-mod').style.display='none'">Close</button>
    </div>
  </div>
  <textarea id="ed-text" spellcheck="false" style="flex:1;background:var(--s1);color:var(--t1);font-family:var(--mono);font-size:13px;padding:16px;border:none;outline:none;resize:none"></textarea>
</div>
<div id="toasts"></div>
</div>

<script>
async function initAuth() {
    let p = localStorage.getItem('mc-pass');
    if (!p) {
        p = prompt("Enter Panel Password (PASS secret):");
        if (!p) { document.body.innerHTML = '<h2 style="color:var(--red);text-align:center;margin-top:20%">Access Denied</h2>'; return; }
    }
    let r = await fetch('/api/auth', {method:'POST', body: new URLSearchParams({pass: p})});
    if (r.ok) {
        localStorage.setItem('mc-pass', p);
        document.getElementById('app').style.display = 'flex';
        connectWS(p); tab('console');
    } else {
        localStorage.removeItem('mc-pass');
        document.body.innerHTML = '<h2 style="color:var(--red);text-align:center;margin-top:20%">Incorrect Password. Reload to try again.</h2>';
    }
}
document.addEventListener("DOMContentLoaded", initAuth);

function toggleTheme(){ const html=document.documentElement; html.dataset.theme=html.dataset.theme==='dark'?'light':'dark'; }
function toast(msg,err=false){
  const c=document.getElementById('toasts'); const d=document.createElement('div'); d.className='toast';
  d.innerHTML=`<span style="color:${err?'var(--red)':'var(--acc)'}">●</span> <span>${msg}</span>`;
  c.appendChild(d); requestAnimationFrame(()=>d.classList.add('show'));
  setTimeout(()=>{d.classList.remove('show');setTimeout(()=>d.remove(),300)},3000);
}

let curTab='console';
function tab(id){
  curTab=id; document.querySelectorAll('.tab-pane').forEach(e=>e.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(e=>e.classList.remove('active'));
  document.getElementById('tab-'+id).classList.add('active'); document.getElementById('d-'+id).classList.add('active');
  if(id==='files'&&!curPath) refreshFiles();
}

let ws;
function connectWS(p){
  ws=new WebSocket(`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}/ws?pass=${encodeURIComponent(p)}`);
  ws.onopen=()=>document.getElementById('pip').style.background='var(--acc)';
  ws.onmessage=e=>{
    const l=document.getElementById('logs'), div=document.createElement('div');
    div.innerText=e.data; l.appendChild(div);
    if(l.children.length>500) l.removeChild(l.firstChild);
    l.scrollTop=l.scrollHeight;
  };
  ws.onclose=()=>{ document.getElementById('pip').style.background='var(--red)'; setTimeout(()=>connectWS(p), 3000); };
}
function sendCmd(){ const i=document.getElementById('cmd'); if(i.value&&ws){ ws.send(i.value); i.value=''; } }
async function mcCtrl(act){
  const r=await fetch('/api/mc/control', {method:'POST', body:new URLSearchParams({action:act})});
  const t=await r.text(); toast(`Server: ${t}`);
}

function formatBytes(b){ if(!+b)return'0 B'; const i=Math.floor(Math.log(b)/Math.log(1024)); return `${(b/1024**i).toFixed(1)} ${['B','KB','MB','GB'][i]}`; }

let curPath='';
async function refreshFiles(p=curPath){
  curPath=p; 
  document.getElementById('path-bread').innerHTML=`<button class="f-btn" onclick="refreshFiles('')">Root</button> ` + p.split('/').filter(Boolean).map((x,i,a)=>`<span style="color:var(--t3)">/</span> <button class="f-btn" onclick="refreshFiles('${a.slice(0,i+1).join('/')}')">${x}</button>`).join('');
  
  const r=await fetch(`/api/fs/disk`); const dsk=await r.json();
  document.getElementById('disk-usg').innerText=`Storage: ${formatBytes(dsk.used)} / ${formatBytes(dsk.total)}`;

  const l=document.getElementById('file-list'); l.innerHTML='<div style="padding:20px;text-align:center">Loading...</div>';
  const res=await fetch(`/api/fs/list?path=${encodeURIComponent(p)}`); const d=await res.json();
  if(p) d.unshift({name:'..', is_dir:true, parent:true});
  l.innerHTML='';
  d.forEach(f=>{
    const fp=(p?p+'/':'')+f.name;
    const isTxt = !f.is_dir && f.name.match(/\.(txt|yml|yaml|json|properties|sh|py|md|csv|log)$/i);
    const row=document.createElement('div'); row.className='file-row';
    row.onclick=()=>f.is_dir?refreshFiles(fp):null;
    row.innerHTML=`
      <div style="color:${f.is_dir?'var(--acc)':'var(--t3)'}; font-size:16px">${f.is_dir?'📁':'📄'}</div>
      <div class="file-name">${f.name}</div>
      ${f.parent ? '' : `
      <div class="row-acts">
        ${isTxt?`<button class="f-btn" onclick="event.stopPropagation();openEd('${fp}','${f.name}')">Edit</button>`:''}
        ${!f.is_dir?`<a class="f-btn" href="/api/fs/download?path=${encodeURIComponent(fp)}" target="_blank" onclick="event.stopPropagation()">Down</a>`:''}
        <button class="f-btn f-del" onclick="event.stopPropagation();delFile('${fp}')">Del</button>
      </div>`}
    `;
    l.appendChild(row);
  });
}
async function delFile(p){ if(confirm('Delete '+p+'?')){ await fetch('/api/fs/delete',{method:'POST',body:new URLSearchParams({path:p})}); refreshFiles(); } }
async function uploadFile(){
  const f=document.getElementById('up-in').files[0]; if(!f)return;
  const fd=new FormData(); fd.append('path',curPath); fd.append('file',f);
  toast('Uploading...'); const r=await fetch('/api/fs/upload',{method:'POST',body:fd});
  r.ok?toast('Uploaded'):toast('Failed',true); refreshFiles();
}

let edPath='';
async function openEd(p,n){
  edPath=p; document.getElementById('ed-title').innerText='Editing: '+n;
  const r=await fetch(`/api/fs/read?path=${encodeURIComponent(p)}`);
  document.getElementById('ed-text').value=await r.text();
  document.getElementById('ed-mod').style.display='flex';
}
async function saveEd(){
  const fd=new URLSearchParams(); fd.append('path',edPath); fd.append('content',document.getElementById('ed-text').value);
  const r=await fetch('/api/fs/write',{method:'POST',body:fd});
  r.ok?toast('Saved ✓'):toast('Save failed',true);
  document.getElementById('ed-mod').style.display='none';
}

async function searchPlugins(){
  const q=document.getElementById('pl-q').value.trim(); if(!q)return;
  const list=document.getElementById('pl-list'); list.innerHTML='Loading...';
  try{
    const res=await fetch(`https://api.modrinth.com/v2/search?query=${encodeURIComponent(q)}&facets=[["project_type:plugin"]]&limit=15`);
    const data=await res.json(); list.innerHTML='';
    data.hits.forEach(p=>{
      list.innerHTML+=`<div class="pl-card">
        <div style="font-weight:600;font-size:14px">${p.title}</div>
        <div style="font-size:11px;color:var(--t2);flex:1">${p.description}</div>
        <button class="mc-ctrl-btn" style="background:var(--acc);color:#fff;border:none" onclick="instPl('${p.project_id}','${p.title}')">Install</button>
      </div>`;
    });
  }catch(e){ list.innerHTML='Error fetching plugins.'; }
}
async function instPl(id, name){
  const loader=document.getElementById('pl-loader').value, ver=document.getElementById('pl-ver').value;
  toast(`Checking ${name}...`);
  try{
    const res=await fetch(`https://api.modrinth.com/v2/project/${id}/version?loaders=["${loader}"]&game_versions=["${ver}"]`);
    const versions=await res.json();
    if(!versions.length) throw new Error("No version match");
    const fd=new URLSearchParams({url:versions[0].files[0].url, filename:versions[0].files[0].filename, project_id:id, version_id:versions[0].id, name:name});
    const dl=await fetch('/api/plugins/install',{method:'POST',body:fd});
    dl.ok?toast(`Installed ${name} ✓`):toast("Download error",true);
  }catch(e){ toast(`Failed: ${e.message}`,true); }
}
</script>
</body></html>
"""

# ─────────────────────────────────────────────
# BACKEND API
# ─────────────────────────────────────────────
def get_path(p: str):
    safe = os.path.abspath(os.path.join(BASE_DIR, (p or "").strip("/")))
    if not safe.startswith(BASE_DIR): raise HTTPException(403)
    return safe

@app.get("/")
def index(): return HTMLResponse(HTML_CONTENT)

@app.post("/api/auth")
def auth_check(password: str = Form(alias="pass")):
    if password == PASS_SECRET: return {"status": "ok"}
    raise HTTPException(401)

@app.websocket("/ws")
async def ws_end(ws: WebSocket, password: str = ""):
    if password != PASS_SECRET:
        await ws.close(code=1008)
        return
    await ws.accept()
    connected_clients.add(ws)
    for line in output_history: await ws.send_text(line)
    try:
        while True:
            cmd = await ws.receive_text()
            if mc_process and mc_process.stdin:
                mc_process.stdin.write((cmd + "\n").encode())
                await mc_process.stdin.drain()
    except: connected_clients.discard(ws)

@app.post("/api/mc/control")
async def mc_control(action: str = Form(...)):
    global mc_process
    if action == "start":
        if not mc_process or mc_process.returncode is not None:
            await boot_mc()
            return "Starting"
        return "Already running"
    elif action == "stop":
        if mc_process and mc_process.returncode is None and mc_process.stdin:
            mc_process.stdin.write(b"stop\n")
            await mc_process.stdin.drain()
            return "Stopping sent"
        return "Not running"
    elif action == "kill":
        if mc_process and mc_process.returncode is None:
            mc_process.kill()
            return "Killed"
        return "Not running"

@app.get("/api/fs/disk")
def fs_disk():
    t, u, f = shutil.disk_usage(BASE_DIR)
    return {"total": t, "used": u, "free": f}

@app.get("/api/fs/list")
def list_fs(path: str = ""):
    t = get_path(path)
    if not os.path.exists(t): return []
    res = [{"name": x, "is_dir": os.path.isdir(os.path.join(t, x))} for x in os.listdir(t)]
    return sorted(res, key=lambda k: (not k["is_dir"], k["name"].lower()))

@app.post("/api/fs/upload")
async def upload(path: str = Form(""), file: UploadFile = File(...)):
    with open(os.path.join(get_path(path), file.filename), "wb") as f: shutil.copyfileobj(file.file, f)
    return "ok"

@app.post("/api/fs/delete")
def delete(path: str = Form(...)):
    t = get_path(path)
    if os.path.isdir(t): shutil.rmtree(t)
    else: os.remove(t)
    return "ok"

@app.get("/api/fs/read")
def read(path: str):
    t = get_path(path)
    return FileResponse(t) if not path.endswith(".json") else json.load(open(t))

@app.post("/api/fs/write")
def write_fs(path: str = Form(...), content: str = Form(...)):
    with open(get_path(path), "w", encoding="utf-8") as f: f.write(content)
    return "ok"

@app.get("/api/fs/download")
def dl_fs(path: str):
    t = get_path(path)
    return FileResponse(t, filename=os.path.basename(t)) if os.path.isfile(t) else HTTPException(404)

@app.post("/api/plugins/install")
def install_pl(url: str = Form(...), filename: str = Form(...), project_id: str = Form(...), version_id: str = Form(...), name: str = Form(...)):
    dest = os.path.join(PLUGINS_DIR, filename)
    req = urllib.request.Request(url, headers={"User-Agent": "Panel/1.0"})
    with urllib.request.urlopen(req) as r, open(dest, "wb") as f: shutil.copyfileobj(r, f)
    return "ok"

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 7860)))