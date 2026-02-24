import os, asyncio, collections, shutil, urllib.request, json
from fastapi import FastAPI, WebSocket, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, Response, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

BASE_DIR = os.environ.get("SERVER_DIR", os.path.abspath("/app"))
mc_process = None
output_history = collections.deque(maxlen=300)
connected_clients = set()

HTML_CONTENT = """
<!DOCTYPE html><html lang="en" class="dark"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Server Engine</title><script src="https://cdn.tailwindcss.com"></script><script src="https://unpkg.com/lucide@latest"></script>
<style>
:root{--bg:#000;--panel:#0a0a0a;--border:#1a1a1a;--accent:#22c55e;}
body{background:var(--bg);color:#a1a1aa;font-family:ui-sans-serif,system-ui,sans-serif;margin:0;height:100vh;display:flex;flex-direction:column;overflow:hidden;}
::-webkit-scrollbar{width:4px;height:4px;} ::-webkit-scrollbar-thumb{background:#27272a;border-radius:4px;} ::-webkit-scrollbar-thumb:hover{background:var(--accent);}
.tab-content{display:none;position:absolute;inset:0;padding:8px;} .tab-content.active{display:flex;flex-direction:column;}
.nav-btn{color:#52525b;transition:.2s;} .nav-btn:hover,.nav-btn.active{color:var(--accent);}
.log-line{word-break:break-all;padding:0.5px 0;font-family:monospace;font-size:11px;}
.modal{display:none;position:fixed;inset:0;background:#000a;backdrop-filter:blur(4px);z-index:50;align-items:center;justify-content:center;} .modal.active{display:flex;}
input:focus,textarea:focus{outline:none;border-color:var(--accent);}
</style></head>
<body>
<div class="flex flex-1 overflow-hidden">
    <!-- Sidebar -->
    <aside class="w-12 bg-[#050505] border-r border-[#1a1a1a] flex flex-col items-center py-6 gap-8 z-40 shrink-0 hidden sm:flex">
        <div class="text-green-500 drop-shadow-[0_0_8px_rgba(34,197,94,0.4)]"><i data-lucide="server" class="w-5 h-5"></i></div>
        <nav class="flex flex-col gap-6 items-center">
            <button onclick="switchTab('console')" id="nav-console" class="nav-btn active"><i data-lucide="terminal-square" class="w-5 h-5"></i></button>
            <button onclick="switchTab('files')" id="nav-files" class="nav-btn"><i data-lucide="folder-tree" class="w-5 h-5"></i></button>
            <button onclick="switchTab('config')" id="nav-config" class="nav-btn"><i data-lucide="settings-2" class="w-5 h-5"></i></button>
            <button onclick="switchTab('plugins')" id="nav-plugins" class="nav-btn"><i data-lucide="puzzle" class="w-5 h-5"></i></button>
        </nav>
    </aside>

    <main class="flex-1 relative bg-black overflow-hidden sm:p-2">
        <!-- CONSOLE -->
        <div id="tab-console" class="tab-content active">
            <div class="flex-1 bg-panel border border-border rounded-xl flex flex-col overflow-hidden shadow-2xl">
                <div class="h-9 border-b border-border bg-[#050505] flex items-center px-3 gap-2 shrink-0">
                    <div class="w-2 h-2 rounded-full bg-green-500 shadow-[0_0_8px_rgba(34,197,94,0.8)]"></div><span class="text-[10px] font-mono text-zinc-500">engine-live-stream</span>
                </div>
                <div id="terminal-output" class="flex-1 p-2 overflow-y-auto text-zinc-300"></div>
                <div class="h-11 border-t border-border bg-[#050505] flex items-center px-3 gap-2 shrink-0">
                    <i data-lucide="chevron-right" class="w-3.5 h-3.5 text-green-500 shrink-0"></i>
                    <input type="text" id="cmd-input" class="flex-1 bg-transparent border-none text-green-400 font-mono text-xs" placeholder="Execute command..." autocomplete="off">
                </div>
            </div>
        </div>

        <!-- FILES -->
        <div id="tab-files" class="tab-content">
            <div class="flex-1 bg-panel border border-border rounded-xl flex flex-col overflow-hidden shadow-2xl">
                <div class="bg-[#050505] border-b border-border p-2 flex justify-between items-center gap-2 shrink-0">
                    <div id="breadcrumbs" class="flex items-center gap-1 text-[11px] font-mono text-zinc-500 overflow-x-auto"></div>
                    <div class="flex items-center gap-1">
                        <input type="file" id="file-upload" class="hidden" onchange="uploadFile(event)">
                        <button onclick="document.getElementById('file-upload').click()" class="p-1.5 rounded-md text-zinc-500 hover:text-green-500"><i data-lucide="upload" class="w-4 h-4"></i></button>
                        <button onclick="loadFiles(currentPath)" class="p-1.5 rounded-md text-zinc-500 hover:text-white"><i data-lucide="rotate-cw" class="w-4 h-4"></i></button>
                    </div>
                </div>
                <div id="file-list" class="flex-1 overflow-y-auto"></div>
            </div>
        </div>

        <!-- CONFIG -->
        <div id="tab-config" class="tab-content">
            <div class="flex-1 bg-panel border border-border rounded-xl flex flex-col overflow-hidden shadow-2xl">
                <div class="h-10 border-b border-border bg-[#050505] flex items-center justify-between px-3 shrink-0">
                    <span class="text-xs font-mono text-zinc-300 flex items-center gap-2"><i data-lucide="sliders" class="w-3.5 h-3.5 text-green-500"></i> server.properties</span>
                    <button onclick="saveConfig()" class="bg-green-600 hover:bg-green-500 text-black px-3 py-1 rounded text-[11px] font-bold flex items-center gap-1"><i data-lucide="save" class="w-3 h-3"></i> Apply</button>
                </div>
                <textarea id="config-editor" class="flex-1 bg-transparent p-3 text-zinc-300 font-mono text-[11px] resize-none border-none" spellcheck="false"></textarea>
            </div>
        </div>

        <!-- PLUGINS -->
        <div id="tab-plugins" class="tab-content">
            <div class="flex-1 bg-panel border border-border rounded-xl flex flex-col overflow-hidden shadow-2xl">
                <div class="bg-[#050505] border-b border-border p-2 flex items-center justify-between shrink-0 gap-2">
                    <div class="flex items-center gap-2">
                        <span class="text-[10px] text-zinc-500 font-mono">MC Ver:</span>
                        <input type="text" id="mc-version" value="1.20.4" class="bg-[#111] border border-[#222] text-zinc-300 text-[11px] px-2 py-1 rounded w-16 text-center font-mono">
                    </div>
                    <div class="flex bg-[#111] rounded p-0.5">
                        <button id="pbtn-installed" onclick="switchPluginView('installed')" class="px-3 py-1 text-[10px] font-bold rounded bg-[#222] text-white">Installed</button>
                        <button id="pbtn-browser" onclick="switchPluginView('browser')" class="px-3 py-1 text-[10px] font-bold rounded text-zinc-500 hover:text-white">Browser</button>
                    </div>
                    <div class="flex items-center gap-2" id="plugin-search-container" style="display:none;">
                        <input type="text" id="plugin-search" class="bg-[#111] border border-[#222] text-zinc-300 text-[11px] px-2 py-1 rounded w-32 font-mono" placeholder="Search..." onkeydown="if(event.key==='Enter') searchPlugins()">
                        <button onclick="searchPlugins()" class="text-green-500 hover:text-green-400"><i data-lucide="search" class="w-4 h-4"></i></button>
                    </div>
                </div>
                <div id="plugin-list" class="flex-1 overflow-y-auto p-2 grid grid-cols-1 sm:grid-cols-2 gap-2 content-start"></div>
            </div>
        </div>
    </main>

    <!-- Mobile Nav -->
    <nav class="flex sm:hidden bg-[#050505] border-t border-border shrink-0 pb-[env(safe-area-inset-bottom,0)]">
        <button onclick="switchTab('console')" id="mnav-console" class="flex-1 flex flex-col items-center gap-1 py-2 text-[9px] text-zinc-500 nav-btn active"><i data-lucide="terminal-square" class="w-5 h-5"></i> Console</button>
        <button onclick="switchTab('files')" id="mnav-files" class="flex-1 flex flex-col items-center gap-1 py-2 text-[9px] text-zinc-500 nav-btn"><i data-lucide="folder-tree" class="w-5 h-5"></i> Files</button>
        <button onclick="switchTab('config')" id="mnav-config" class="flex-1 flex flex-col items-center gap-1 py-2 text-[9px] text-zinc-500 nav-btn"><i data-lucide="settings-2" class="w-5 h-5"></i> Config</button>
        <button onclick="switchTab('plugins')" id="mnav-plugins" class="flex-1 flex flex-col items-center gap-1 py-2 text-[9px] text-zinc-500 nav-btn"><i data-lucide="puzzle" class="w-5 h-5"></i> Plugins</button>
    </nav>
</div>

<!-- Modal -->
<div id="editor-modal" class="modal">
    <div class="bg-panel border border-[#222] rounded-t-xl sm:rounded-xl w-full max-w-3xl h-[85vh] flex flex-col self-end sm:self-center">
        <div class="p-2 border-b border-border bg-[#050505] flex justify-between items-center shrink-0">
            <span id="editor-title" class="text-[11px] font-mono text-green-400 truncate w-2/3"></span>
            <div class="flex gap-2">
                <button onclick="document.getElementById('editor-modal').classList.remove('active')" class="px-3 py-1 text-[11px] text-zinc-500 hover:text-white">Discard</button>
                <button onclick="saveFile()" class="bg-green-600 hover:bg-green-500 text-black px-3 py-1 text-[11px] font-bold rounded flex items-center gap-1"><i data-lucide="save" class="w-3 h-3"></i> Save</button>
            </div>
        </div>
        <textarea id="editor-content" class="flex-1 bg-transparent p-3 text-zinc-300 font-mono text-[11px] resize-none border-none" spellcheck="false"></textarea>
    </div>
</div>

<div id="toast-container" class="fixed bottom-16 sm:bottom-4 right-4 z-50 flex flex-col gap-2 pointer-events-none"></div>

<script>
    lucide.createIcons();
    const showToast = (msg, type='info') => {
        const c = document.getElementById('toast-container'), t = document.createElement('div');
        const col = type==='error'?'#ef4444':type==='success'?'#22c55e':'#60a5fa';
        t.className = `flex items-center gap-2 bg-[#0a0a0a] border border-[${col}33] p-2.5 rounded-lg shadow-xl text-[11px] font-mono text-zinc-200 transition-all duration-300 translate-y-4 opacity-0`;
        t.innerHTML = `<div class="w-1.5 h-1.5 rounded-full" style="background:${col}"></div>${msg}`;
        c.appendChild(t); requestAnimationFrame(() => { t.classList.remove('translate-y-4','opacity-0'); });
        setTimeout(() => { t.classList.add('opacity-0'); setTimeout(()=>t.remove(),300); }, 3000);
    };

    // Navigation
    function switchTab(t) {
        document.querySelectorAll('.tab-content').forEach(el=>el.classList.remove('active'));
        document.querySelectorAll('.nav-btn').forEach(el=>el.classList.remove('active'));
        document.getElementById('tab-'+t).classList.add('active');
        if(document.getElementById('nav-'+t)) document.getElementById('nav-'+t).classList.add('active');
        if(document.getElementById('mnav-'+t)) document.getElementById('mnav-'+t).classList.add('active');
        if(t==='files'&&!currentPathLoaded){loadFiles(''); currentPathLoaded=true;}
        if(t==='config') loadConfig();
        if(t==='plugins'&&Object.keys(pluginsJson).length===0) initPlugins();
        if(t==='console') termOut.scrollTop=termOut.scrollHeight;
    }

    // Console
    const termOut = document.getElementById('terminal-output'), cmdInput = document.getElementById('cmd-input');
    function appendLog(txt) {
        const d = document.createElement('div'); d.className='log-line'; 
        d.innerHTML = txt.replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\\x1b\\[([0-9;]*)m(.*?)(?=\\x1b|$)/gs, (m,g1,g2) => {
            let s=''; if(g1.includes('31'))s='color:#ef4444'; else if(g1.includes('32'))s='color:#22c55e'; else if(g1.includes('33'))s='color:#eab308'; else if(g1.includes('36'))s='color:#06b6d4';
            return `<span style="${s}">${g2}</span>`;
        });
        const bot = termOut.scrollHeight - termOut.clientHeight <= termOut.scrollTop + 10;
        termOut.appendChild(d); if(termOut.childElementCount>300) termOut.removeChild(termOut.firstChild);
        if(bot) termOut.scrollTop = termOut.scrollHeight;
    }
    const ws = new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws');
    ws.onmessage = e => appendLog(e.data);
    cmdInput.onkeypress = e => { if(e.key==='Enter'&&cmdInput.value.trim()){ ws.send(cmdInput.value.trim()); cmdInput.value=''; } };

    // Files
    let currentPath = '', currentPathLoaded = false, currentEditPath = '';
    async function loadFiles(p) {
        currentPath = p; document.getElementById('breadcrumbs').innerHTML = `<button onclick="loadFiles('')" class="hover:text-green-500"><i data-lucide="home" class="w-3.5 h-3.5"></i></button> ` + p.split('/').filter(x=>x).map((x,i,a)=>`<span class="opacity-30 mx-1">/</span><span class="${i===a.length-1?'text-green-500':''}">${x}</span>`).join('');
        lucide.createIcons(); document.getElementById('file-list').innerHTML='<div class="p-4 text-center text-xs text-zinc-500 font-mono">Loading...</div>';
        try {
            const res = await fetch(`/api/fs/list?path=${encodeURIComponent(p)}`); const files = await res.json();
            let html = p?`<div class="flex items-center p-2 border-b border-[#1a1a1a] cursor-pointer hover:bg-[#111]" onclick="loadFiles('${p.split('/').slice(0,-1).join('/')}')"><i data-lucide="corner-left-up" class="w-4 h-4 text-zinc-500 mr-2"></i><span class="text-[11px] font-mono text-zinc-500">..</span></div>`:'';
            if(!files.length&&!p) html+='<div class="p-4 text-center text-xs text-zinc-500 font-mono">Empty Directory</div>';
            files.forEach(f => {
                const ic = f.is_dir ? '<i data-lucide="folder" class="w-4 h-4 text-green-500 shrink-0"></i>' : '<i data-lucide="file" class="w-4 h-4 text-zinc-500 shrink-0"></i>';
                const pth = p?`${p}/${f.name}`:f.name;
                html += `<div class="flex items-center p-2 border-b border-[#1a1a1a] cursor-pointer hover:bg-[#111] gap-2" onclick="${f.is_dir?`loadFiles('${pth}')`:`editFile('${pth}')`}">${ic}<span class="text-[11px] font-mono text-zinc-300 flex-1 truncate">${f.name}</span>
                <button onclick="event.stopPropagation(); deleteFile('${pth}')" class="p-1 hover:text-red-500 text-zinc-600"><i data-lucide="trash" class="w-3.5 h-3.5"></i></button></div>`;
            });
            document.getElementById('file-list').innerHTML = html; lucide.createIcons();
        } catch { showToast('Load failed', 'error'); }
    }
    async function deleteFile(p) {
        if(!confirm(`Delete ${p}?`)) return;
        const fd=new FormData(); fd.append('path',p);
        if((await fetch('/api/fs/delete',{method:'POST',body:fd})).ok) { showToast('Deleted','success'); loadFiles(currentPath); }
    }
    async function uploadFile(e) {
        if(!e.target.files[0]) return;
        const fd=new FormData(); fd.append('path',currentPath); fd.append('file',e.target.files[0]);
        showToast('Uploading...'); if((await fetch('/api/fs/upload',{method:'POST',body:fd})).ok) { showToast('Uploaded','success'); loadFiles(currentPath); }
        e.target.value='';
    }
    async function editFile(p) {
        try {
            const r=await fetch(`/api/fs/read?path=${encodeURIComponent(p)}`); if(!r.ok) throw new Error();
            currentEditPath=p; document.getElementById('editor-title').innerText=p; document.getElementById('editor-content').value=await r.text();
            document.getElementById('editor-modal').classList.add('active');
        } catch { showToast('Cannot read file','error'); }
    }
    async function saveFile() {
        const fd=new FormData(); fd.append('path',currentEditPath); fd.append('content',document.getElementById('editor-content').value);
        if((await fetch('/api/fs/write',{method:'POST',body:fd})).ok) { showToast('Saved','success'); document.getElementById('editor-modal').classList.remove('active'); }
    }

    // Config
    async function loadConfig() { try{ document.getElementById('config-editor').value = await(await fetch('/api/fs/read?path=server.properties')).text(); }catch{} }
    async function saveConfig() {
        const fd=new FormData(); fd.append('path','server.properties'); fd.append('content',document.getElementById('config-editor').value);
        if((await fetch('/api/fs/write',{method:'POST',body:fd})).ok) showToast('Config applied','success');
    }

    // Plugins (Modrinth)
    let pluginsJson = {}, currentPView = 'installed';
    async function initPlugins() {
        try { const r = await fetch('/api/fs/read?path=plugins/plugins.json'); if(r.ok) pluginsJson = JSON.parse(await r.text()); } catch{}
        renderInstalledPlugins(); checkUpdates();
    }
    async function savePluginsState() {
        const fd=new FormData(); fd.append('path','plugins/plugins.json'); fd.append('content',JSON.stringify(pluginsJson,null,2));
        await fetch('/api/fs/write',{method:'POST',body:fd});
    }
    function switchPluginView(v) {
        currentPView = v; document.getElementById('pbtn-installed').className = `px-3 py-1 text-[10px] font-bold rounded ${v==='installed'?'bg-[#222] text-white':'text-zinc-500 hover:text-white'}`;
        document.getElementById('pbtn-browser').className = `px-3 py-1 text-[10px] font-bold rounded ${v==='browser'?'bg-[#222] text-white':'text-zinc-500 hover:text-white'}`;
        document.getElementById('plugin-search-container').style.display = v==='browser'?'flex':'none';
        v==='installed' ? renderInstalledPlugins() : document.getElementById('plugin-list').innerHTML='<div class="col-span-full p-4 text-center text-xs text-zinc-500 font-mono">Search above to find plugins.</div>';
    }
    function renderInstalledPlugins() {
        const c = document.getElementById('plugin-list'); c.innerHTML='';
        const keys = Object.keys(pluginsJson); if(!keys.length) return c.innerHTML='<div class="col-span-full p-4 text-center text-xs text-zinc-500 font-mono">No plugins installed via engine.</div>';
        keys.forEach(k => {
            const p = pluginsJson[k];
            c.innerHTML += `<div class="bg-[#050505] border border-border rounded p-3 flex flex-col gap-2">
                <div class="flex justify-between items-start">
                    <div><h3 class="text-[12px] font-bold text-white">${p.name||k}</h3><p class="text-[10px] font-mono text-zinc-500 break-all">${p.filename}</p></div>
                    ${p.has_update ? `<button onclick="installPlugin('${k}', true)" class="bg-blue-600 hover:bg-blue-500 text-white px-2 py-1 rounded text-[10px] font-bold">Update</button>` : `<span class="bg-[#111] px-2 py-0.5 rounded text-[10px] text-zinc-500 border border-[#222]">Up to date</span>`}
                </div>
            </div>`;
        });
    }
    async function searchPlugins() {
        const q = document.getElementById('plugin-search').value.trim(); const v = document.getElementById('mc-version').value.trim(); if(!q||!v)return;
        document.getElementById('plugin-list').innerHTML='<div class="col-span-full p-4 text-center text-xs text-zinc-500 font-mono">Searching Modrinth...</div>';
        try {
            const res = await fetch(`https://api.modrinth.com/v2/search?query=${q}&facets=[["project_type:plugin"],["versions:${v}"]]`).then(r=>r.json());
            const c = document.getElementById('plugin-list'); c.innerHTML='';
            if(!res.hits.length) return c.innerHTML='<div class="col-span-full p-4 text-center text-xs text-zinc-500 font-mono">No results found for this version.</div>';
            res.hits.forEach(h => {
                c.innerHTML += `<div class="bg-[#050505] border border-border rounded p-3 flex flex-col justify-between gap-3">
                    <div><h3 class="text-[12px] font-bold text-green-400 mb-1">${h.title}</h3><p class="text-[10px] text-zinc-400 leading-snug">${h.description}</p></div>
                    <button onclick="installPlugin('${h.project_id}')" class="bg-[#1a1a1a] hover:bg-green-600 hover:text-black transition-colors text-white px-3 py-1.5 rounded text-[10px] font-bold w-full">Install Latest</button>
                </div>`;
            });
        } catch { showToast('Search failed','error'); }
    }
    async function checkUpdates() {
        const v = document.getElementById('mc-version').value.trim(); if(!v) return;
        for (let pid in pluginsJson) {
            try {
                const res = await fetch(`https://api.modrinth.com/v2/project/${pid}/version?game_versions=["${v}"]`).then(r=>r.json());
                if(res.length && res[0].id !== pluginsJson[pid].version_id) pluginsJson[pid].has_update = true;
                else pluginsJson[pid].has_update = false;
            } catch{}
        }
        if(currentPView==='installed') renderInstalledPlugins();
    }
    async function installPlugin(pid, isUpdate=false) {
        showToast(isUpdate?'Updating...':'Installing...');
        const v = document.getElementById('mc-version').value.trim();
        try {
            const res = await fetch(`https://api.modrinth.com/v2/project/${pid}/version?game_versions=["${v}"]`).then(r=>r.json());
            if(!res.length) return showToast('No compatible version found', 'error');
            const file = res[0].files.find(f=>f.primary) || res[0].files[0];
            const fd = new FormData(); fd.append('url', file.url); fd.append('filename', file.filename);
            if((await fetch('/api/plugins/install', {method:'POST', body:fd})).ok) {
                const proj = await fetch(`https://api.modrinth.com/v2/project/${pid}`).then(r=>r.json());
                pluginsJson[pid] = { project_id: pid, version_id: res[0].id, filename: file.filename, name: proj.title };
                await savePluginsState(); showToast('Success', 'success'); if(currentPView==='installed') renderInstalledPlugins();
            } else showToast('Download failed', 'error');
        } catch { showToast('Network error', 'error'); }
    }
</script></body></html>
"""

def get_safe_path(subpath: str):
    p = os.path.abspath(os.path.join(BASE_DIR, (subpath or "").strip("/")))
    if not p.startswith(BASE_DIR): raise HTTPException(403, "Access denied")
    return p

async def read_stream(stream, prefix=""):
    while True:
        try:
            line = await stream.readline()
            if not line: break
            await broadcast(prefix + line.decode('utf-8', errors='replace').rstrip('\r\n'))
        except: break

async def broadcast(msg: str):
    output_history.append(msg)
    for c in list(connected_clients):
        try: await c.send_text(msg)
        except: connected_clients.remove(c)

async def start_minecraft():
    global mc_process
    jar_path = os.path.join(BASE_DIR, "purpur.jar")
    if not os.path.exists(jar_path): await broadcast("\x1b[33m[Panel] Missing purpur.jar in app directory.\x1b[0m")
    mc_process = await asyncio.create_subprocess_exec(
        "java", "-Xmx4G", "-Dfile.encoding=UTF-8", "-jar", "purpur.jar", "--nogui",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, cwd=BASE_DIR
    )
    asyncio.create_task(read_stream(mc_process.stdout))

@app.on_event("startup")
async def startup_event():
    os.makedirs(BASE_DIR, exist_ok=True)
    asyncio.create_task(start_minecraft())

@app.get("/")
def get_panel(): return HTMLResponse(content=HTML_CONTENT)

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept(); connected_clients.add(ws)
    for l in output_history: await ws.send_text(l)
    try:
        while True:
            cmd = await ws.receive_text()
            if mc_process and mc_process.stdin: mc_process.stdin.write((cmd + "\n").encode()); await mc_process.stdin.drain()
    except: connected_clients.discard(ws)

@app.get("/api/fs/list")
def fs_list(path: str = ""):
    t = get_safe_path(path)
    if not os.path.exists(t): return []
    return sorted([{"name": f, "is_dir": os.path.isdir(os.path.join(t, f))} for f in os.listdir(t)], key=lambda x: (not x["is_dir"], x["name"].lower()))

@app.get("/api/fs/read")
def fs_read(path: str):
    try:
        with open(get_safe_path(path), 'r', encoding='utf-8') as f: return Response(content=f.read(), media_type="text/plain")
    except: raise HTTPException(400, "File is binary or unreadable")

@app.post("/api/fs/write")
def fs_write(path: str = Form(...), content: str = Form(...)):
    t = get_safe_path(path); os.makedirs(os.path.dirname(t), exist_ok=True)
    with open(t, 'w', encoding='utf-8') as f: f.write(content)
    return {"status": "ok"}

@app.post("/api/fs/upload")
async def fs_upload(path: str = Form(""), file: UploadFile = File(...)):
    d = get_safe_path(path); os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, file.filename), "wb") as b: shutil.copyfileobj(file.file, b)
    return {"status": "ok"}

@app.post("/api/fs/delete")
def fs_delete(path: str = Form(...)):
    t = get_safe_path(path)
    if os.path.isdir(t): shutil.rmtree(t)
    else: os.remove(t)
    return {"status": "ok"}

@app.post("/api/plugins/install")
def install_plugin(url: str = Form(...), filename: str = Form(...)):
    try:
        pd = get_safe_path("plugins")
        os.makedirs(pd, exist_ok=True)
        req = urllib.request.Request(url, headers={'User-Agent': 'HF-Minecraft-Panel/1.0'})
        with urllib.request.urlopen(req) as response, open(os.path.join(pd, filename), 'wb') as out_file:
            shutil.copyfileobj(response, out_file)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(400, str(e))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")