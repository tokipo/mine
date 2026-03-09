import os, asyncio, collections, shutil, urllib.request, json, time
from fastapi import FastAPI, WebSocket, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# --- CONFIG ---
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
BASE_DIR = os.environ.get("SERVER_DIR", os.path.abspath("/app"))
PLUGINS_DIR = os.path.join(BASE_DIR, "plugins")
mc_process = None
output_history = collections.deque(maxlen=300)
connected_clients = set()

# --- HTML GUI ---
HTML_CONTENT = """
<!DOCTYPE html><html lang="en" class="dark"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no"><title>Server Engine</title>
<script src="https://cdn.tailwindcss.com"></script><script src="https://unpkg.com/lucide@latest"></script>
<style>
:root{--bg:#050505;--panel:#0a0a0a;--border:#1a1a1a;--accent:#22c55e;--text:#a1a1aa;}
body{background:var(--bg);color:var(--text);font-family:ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,sans-serif;height:100dvh;display:flex;flex-direction:column;overflow:hidden;user-select:none;}
::-webkit-scrollbar{width:4px}::-webkit-scrollbar-thumb{background:#27272a;border-radius:2px}::-webkit-scrollbar-thumb:hover{background:var(--accent)}
.tab-pane{display:none;flex:1;flex-direction:column;overflow:hidden;position:relative;animation:fadeIn 0.2s ease-out} .tab-pane.active{display:flex}
@keyframes fadeIn{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}
.nav-btn{transition:all 0.2s} .nav-btn.active{color:var(--accent)} .nav-btn.active::after{content:'';position:absolute;bottom:-1px;left:0;right:0;height:1px;background:var(--accent);box-shadow:0 -1px 4px var(--accent)}
.log-line{font-family:'JetBrains Mono',monospace;font-size:11px;line-height:1.4;word-break:break-all;padding:1px 0}
input:focus,select:focus,textarea:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 1px rgba(34,197,94,0.1)}
.loader{border:2px solid #222;border-top:2px solid var(--accent);border-radius:50%;width:16px;height:16px;animation:spin .6s linear infinite}
@keyframes spin{0%{transform:rotate(0deg)}100%{transform:rotate(360deg)}}
</style></head>
<body>
<!-- MAIN LAYOUT -->
<div class="flex flex-1 overflow-hidden">
    <!-- DESKTOP SIDEBAR -->
    <aside class="hidden sm:flex flex-col w-14 bg-black border-r border-[#1a1a1a] items-center py-6 gap-6 z-20">
        <div class="text-green-500 drop-shadow-md"><i data-lucide="cpu" class="w-6 h-6"></i></div>
        <nav class="flex flex-col gap-6 w-full items-center">
            <button onclick="tab('console')" id="d-console" class="nav-btn active p-2 hover:text-white" title="Console"><i data-lucide="terminal-square" class="w-5 h-5"></i></button>
            <button onclick="tab('files')" id="d-files" class="nav-btn p-2 hover:text-white" title="Files"><i data-lucide="folder-tree" class="w-5 h-5"></i></button>
            <button onclick="tab('plugins')" id="d-plugins" class="nav-btn p-2 hover:text-white" title="Plugins"><i data-lucide="package-search" class="w-5 h-5"></i></button>
        </nav>
    </aside>

    <main class="flex-1 flex flex-col relative bg-[#050505] overflow-hidden">
        
        <!-- CONSOLE -->
        <div id="tab-console" class="tab-pane active p-2 sm:p-4">
            <div class="flex-1 bg-black border border-[#1a1a1a] rounded-lg flex flex-col overflow-hidden shadow-2xl">
                <div class="h-8 bg-[#0a0a0a] border-b border-[#1a1a1a] flex items-center px-3 gap-2">
                    <div class="w-2 h-2 rounded-full bg-green-500 shadow-[0_0_6px_#22c55e]"></div><span class="text-[10px] font-mono text-zinc-500 uppercase tracking-wider">Live Stream</span>
                </div>
                <div id="logs" class="flex-1 overflow-y-auto p-3 text-zinc-300 scroll-smooth"></div>
                <div class="p-2 bg-[#0a0a0a] border-t border-[#1a1a1a] flex gap-2">
                    <input id="cmd" type="text" class="flex-1 bg-[#050505] border border-[#222] rounded text-xs px-3 py-2 font-mono text-green-400 placeholder-zinc-700" placeholder="Type a command..." autocomplete="off">
                    <button onclick="sendCmd()" class="bg-[#1a1a1a] hover:bg-[#222] text-white p-2 rounded border border-[#222]"><i data-lucide="send-horizontal" class="w-4 h-4"></i></button>
                </div>
            </div>
        </div>

        <!-- FILES -->
        <div id="tab-files" class="tab-pane p-2 sm:p-4">
            <div class="flex-1 bg-black border border-[#1a1a1a] rounded-lg flex flex-col overflow-hidden">
                <div class="p-3 border-b border-[#1a1a1a] flex items-center gap-2 bg-[#0a0a0a]">
                    <div id="path-bread" class="flex-1 flex items-center gap-1 text-[11px] font-mono overflow-x-auto whitespace-nowrap mask-linear"></div>
                    <button onclick="document.getElementById('up').click()" class="hover:text-white"><i data-lucide="upload-cloud" class="w-4 h-4"></i></button>
                    <button onclick="refreshFiles()" class="hover:text-white"><i data-lucide="refresh-cw" class="w-4 h-4"></i></button>
                    <input type="file" id="up" class="hidden" onchange="uploadFile()">
                </div>
                <div id="file-list" class="flex-1 overflow-y-auto"></div>
            </div>
        </div>

        <!-- PLUGINS (BROWSER & INSTALLED) -->
        <div id="tab-plugins" class="tab-pane p-2 sm:p-4">
            <div class="flex-1 bg-black border border-[#1a1a1a] rounded-lg flex flex-col overflow-hidden">
                <!-- Plugin Header/Controls -->
                <div class="p-3 border-b border-[#1a1a1a] bg-[#0a0a0a] flex flex-col gap-3 shrink-0">
                    <div class="flex gap-2 w-full">
                        <div class="flex bg-[#111] rounded border border-[#222] p-0.5 shrink-0">
                            <button onclick="setPView('browser')" id="pv-browser" class="px-3 py-1 text-[10px] font-bold rounded bg-[#222] text-white transition-all">Browse</button>
                            <button onclick="setPView('installed')" id="pv-installed" class="px-3 py-1 text-[10px] font-bold rounded text-zinc-500 hover:text-white transition-all">Installed</button>
                        </div>
                        <div class="h-full w-[1px] bg-[#222] mx-1"></div>
                        <!-- Configuration -->
                        <select id="pl-loader" class="bg-[#111] border border-[#222] text-zinc-300 text-[10px] px-2 rounded focus:ring-0 w-24">
                            <option value="paper">Paper/Spigot</option>
                            <option value="purpur">Purpur</option>
                            <option value="velocity">Velocity</option>
                            <option value="waterfall">Waterfall</option>
                            <option value="fabric">Fabric</option>
                        </select>
                        <input type="text" id="pl-version" value="1.20.4" class="bg-[#111] border border-[#222] text-zinc-300 text-[10px] px-2 rounded w-16 text-center" placeholder="Ver">
                    </div>
                    <!-- Search Bar -->
                    <div id="search-box" class="flex gap-2">
                        <div class="relative flex-1">
                            <i data-lucide="search" class="absolute left-2.5 top-2 w-3.5 h-3.5 text-zinc-500"></i>
                            <input type="text" id="pl-query" class="w-full bg-[#050505] border border-[#222] rounded text-[11px] pl-8 pr-3 py-1.5 text-white placeholder-zinc-700" placeholder="Search Modrinth (e.g. LuckPerms)..." onkeydown="if(event.key==='Enter') searchPlugins()">
                        </div>
                        <button onclick="searchPlugins()" class="bg-green-600 hover:bg-green-500 text-black px-3 py-1 rounded text-[10px] font-bold">Search</button>
                    </div>
                </div>
                
                <!-- Results Area -->
                <div id="pl-list" class="flex-1 overflow-y-auto p-2 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 content-start">
                    <div class="col-span-full flex flex-col items-center justify-center text-zinc-600 h-64 gap-2">
                        <i data-lucide="search-code" class="w-8 h-8 opacity-20"></i>
                        <span class="text-xs">Select loader & version, then search.</span>
                    </div>
                </div>
            </div>
        </div>
    </main>
</div>

<!-- MOBILE NAV -->
<nav class="sm:hidden flex bg-black border-t border-[#1a1a1a] pb-[env(safe-area-inset-bottom,0)]">
    <button onclick="tab('console')" id="m-console" class="nav-btn active flex-1 py-3 flex justify-center text-zinc-500"><i data-lucide="terminal-square" class="w-5 h-5"></i></button>
    <button onclick="tab('files')" id="m-files" class="nav-btn flex-1 py-3 flex justify-center text-zinc-500"><i data-lucide="folder-tree" class="w-5 h-5"></i></button>
    <button onclick="tab('plugins')" id="m-plugins" class="nav-btn flex-1 py-3 flex justify-center text-zinc-500"><i data-lucide="package-search" class="w-5 h-5"></i></button>
</nav>

<!-- TOASTS -->
<div id="toasts" class="fixed bottom-16 sm:bottom-6 right-4 z-50 flex flex-col gap-2 pointer-events-none"></div>

<script>
lucide.createIcons();
let curPath = "", curView = "browser";

// --- UTILS ---
const toast = (msg, err=false) => {
    const d = document.createElement("div");
    d.className = `flex items-center gap-3 px-4 py-3 rounded-lg border shadow-xl backdrop-blur-md transform transition-all duration-300 translate-y-8 opacity-0 pointer-events-auto ${err ? 'bg-red-950/90 border-red-900 text-red-200' : 'bg-zinc-900/90 border-zinc-800 text-zinc-200'}`;
    d.innerHTML = `<i data-lucide="${err?'alert-circle':'check-circle-2'}" class="w-4 h-4 ${err?'text-red-500':'text-green-500'}"></i><span class="text-[11px] font-medium">${msg}</span>`;
    document.getElementById("toasts").appendChild(d);
    lucide.createIcons();
    requestAnimationFrame(() => d.classList.remove("translate-y-8", "opacity-0"));
    setTimeout(() => { d.classList.add("translate-y-4", "opacity-0"); setTimeout(() => d.remove(), 300); }, 3000);
};

function tab(id) {
    document.querySelectorAll(".tab-pane").forEach(e => e.classList.remove("active"));
    document.querySelectorAll(".nav-btn").forEach(e => e.classList.remove("active"));
    document.getElementById("tab-" + id).classList.add("active");
    if(document.getElementById("d-" + id)) document.getElementById("d-" + id).classList.add("active");
    if(document.getElementById("m-" + id)) document.getElementById("m-" + id).classList.add("active");
    if(id === "files" && !curPath) refreshFiles();
    if(id === "plugins" && curView === "installed") loadInstalled();
}

// --- CONSOLE ---
const logs = document.getElementById("logs");
const ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
ws.onmessage = e => {
    const l = document.createElement("div"); l.className = "log-line";
    // Basic ANSI color parsing
    l.innerHTML = e.data.replace(/</g, "&lt;").replace(/\x1b\[31m/g, '<span class="text-red-400">').replace(/\x1b\[32m/g, '<span class="text-green-400">').replace(/\x1b\[33m/g, '<span class="text-yellow-400">').replace(/\x1b\[36m/g, '<span class="text-cyan-400">').replace(/\x1b\[0m/g, '</span>');
    logs.appendChild(l);
    if(logs.children.length > 300) logs.removeChild(logs.firstChild);
    if(logs.scrollHeight - logs.scrollTop < logs.clientHeight + 50) logs.scrollTop = logs.scrollHeight;
};
function sendCmd() {
    const i = document.getElementById("cmd"); if(!i.value.trim()) return;
    ws.send(i.value); i.value = "";
}

// --- FILES ---
async function refreshFiles(p = curPath) {
    curPath = p;
    document.getElementById("path-bread").innerHTML = `<button onclick="refreshFiles('')" class="hover:text-green-400"><i data-lucide="home" class="w-3 h-3"></i></button>` + p.split("/").filter(Boolean).map((x,i,a) => `<span class="opacity-25">/</span><button onclick="refreshFiles('${a.slice(0,i+1).join("/")}')" class="hover:text-white">${x}</button>`).join("");
    lucide.createIcons();
    const l = document.getElementById("file-list"); l.innerHTML = `<div class="p-4 flex justify-center"><div class="loader"></div></div>`;
    try {
        const r = await fetch(`/api/fs/list?path=${encodeURIComponent(p)}`);
        const d = await r.json();
        l.innerHTML = "";
        if(p) d.unshift({name:"..", is_dir:true, parent:true});
        if(d.length === 0) l.innerHTML = `<div class="p-8 text-center text-xs text-zinc-600">Empty Directory</div>`;
        d.forEach(f => {
            const row = document.createElement("div");
            row.className = "flex items-center gap-3 p-2 border-b border-[#111] hover:bg-[#111] cursor-pointer group";
            if(f.parent) {
                row.onclick = () => refreshFiles(p.split("/").slice(0,-1).join("/"));
                row.innerHTML = `<i data-lucide="corner-left-up" class="w-4 h-4 text-zinc-500"></i><span class="text-xs text-zinc-500">Back</span>`;
            } else {
                row.onclick = () => f.is_dir ? refreshFiles((p?p+"/":"")+f.name) : null;
                row.innerHTML = `
                    <i data-lucide="${f.is_dir?'folder':'file'}" class="w-4 h-4 ${f.is_dir?'text-green-500':'text-zinc-500'}"></i>
                    <span class="flex-1 text-xs font-mono text-zinc-300 truncate">${f.name}</span>
                    <button onclick="event.stopPropagation(); delFile('${(p?p+"/":"")+f.name}')" class="opacity-0 group-hover:opacity-100 p-1 hover:text-red-500 transition-opacity"><i data-lucide="trash-2" class="w-3.5 h-3.5"></i></button>
                `;
            }
            l.appendChild(row);
        });
        lucide.createIcons();
    } catch(e) { toast("Failed to load files", true); }
}
async function uploadFile() {
    const f = document.getElementById("up").files[0]; if(!f) return;
    const fd = new FormData(); fd.append("path", curPath); fd.append("file", f);
    toast("Uploading...");
    if((await fetch("/api/fs/upload", {method:"POST", body:fd})).ok) { toast("Uploaded"); refreshFiles(); } else toast("Upload failed", true);
}
async function delFile(p) {
    if(!confirm("Delete " + p + "?")) return;
    const fd = new FormData(); fd.append("path", p);
    if((await fetch("/api/fs/delete", {method:"POST", body:fd})).ok) { toast("Deleted"); refreshFiles(); }
}

// --- PLUGINS (MODRINTH) ---
function setPView(v) {
    curView = v;
    document.getElementById("pv-browser").className = `px-3 py-1 text-[10px] font-bold rounded transition-all ${v==='browser'?'bg-[#222] text-white':'text-zinc-500 hover:text-white'}`;
    document.getElementById("pv-installed").className = `px-3 py-1 text-[10px] font-bold rounded transition-all ${v==='installed'?'bg-[#222] text-white':'text-zinc-500 hover:text-white'}`;
    document.getElementById("search-box").style.display = v === 'browser' ? 'flex' : 'none';
    if(v === 'browser') {
        document.getElementById("pl-list").innerHTML = `<div class="col-span-full flex flex-col items-center justify-center text-zinc-600 h-64 gap-2"><i data-lucide="search" class="w-8 h-8 opacity-20"></i><span class="text-xs">Ready to search.</span></div>`;
        lucide.createIcons();
    } else loadInstalled();
}

async function searchPlugins() {
    const q = document.getElementById("pl-query").value.trim();
    if(!q) return;
    const list = document.getElementById("pl-list");
    list.innerHTML = `<div class="col-span-full flex justify-center py-10"><div class="loader"></div></div>`;
    
    // We map user selection to generic facets for broader results, then filter versions strictly on install click
    try {
        const res = await fetch(`https://api.modrinth.com/v2/search?query=${encodeURIComponent(q)}&facets=[["project_type:plugin"]]&limit=20`);
        const data = await res.json();
        list.innerHTML = "";
        
        if(data.hits.length === 0) {
            list.innerHTML = `<div class="col-span-full text-center text-xs text-zinc-500 py-8">No results found on Modrinth.</div>`;
            return;
        }

        data.hits.forEach(p => {
            const card = document.createElement("div");
            card.className = "bg-[#080808] border border-[#1a1a1a] rounded p-3 flex flex-col gap-2 hover:border-[#333] transition-colors";
            card.innerHTML = `
                <div class="flex gap-3">
                    <img src="${p.icon_url || 'https://cdn.modrinth.com/assets/unknown_icon.png'}" class="w-8 h-8 rounded bg-[#111]" onerror="this.src='https://placehold.co/32x32/111/444?text=?'">
                    <div class="flex-1 min-w-0">
                        <div class="flex justify-between items-start">
                            <h3 class="text-xs font-bold text-zinc-200 truncate pr-2" title="${p.title}">${p.title}</h3>
                            <span class="text-[9px] bg-[#111] text-zinc-500 px-1 rounded border border-[#222]">${p.downloads.toLocaleString()} dl</span>
                        </div>
                        <p class="text-[10px] text-zinc-500 line-clamp-2 leading-tight mt-0.5">${p.description}</p>
                    </div>
                </div>
                <div class="mt-auto pt-2 border-t border-[#1a1a1a]">
                    <button onclick="resolveInstall('${p.project_id}', '${p.title.replace(/'/g, "")}')" id="btn-${p.project_id}" class="w-full bg-[#111] hover:bg-green-600 hover:text-black text-zinc-400 text-[10px] font-bold py-1.5 rounded transition-colors flex items-center justify-center gap-1">
                        <i data-lucide="download" class="w-3 h-3"></i> Install
                    </button>
                </div>
            `;
            list.appendChild(card);
        });
        lucide.createIcons();
    } catch(e) {
        list.innerHTML = `<div class="col-span-full text-center text-xs text-red-400 py-8">Error connecting to Modrinth API.</div>`;
    }
}

async function resolveInstall(id, name) {
    const loaderRaw = document.getElementById("pl-loader").value;
    const version = document.getElementById("pl-version").value.trim();
    const btn = document.getElementById(`btn-${id}`);
    
    // UI Loading State
    const ogHtml = btn.innerHTML;
    btn.innerHTML = `<div class="loader w-3 h-3 border-zinc-400 border-t-transparent"></div> Checking...`;
    btn.disabled = true;

    // Smart Loader Mapping: Purpur/Waterfall usually support Spigot/Paper plugins
    let loaders = [loaderRaw];
    if(loaderRaw === 'purpur') loaders = ['paper', 'spigot', 'purpur'];
    if(loaderRaw === 'paper') loaders = ['paper', 'spigot'];
    if(loaderRaw === 'waterfall') loaders = ['bungeecord', 'waterfall'];

    try {
        // Construct array string for API: '["paper", "spigot"]'
        const lQuery = JSON.stringify(loaders);
        const vQuery = JSON.stringify([version]);
        
        const res = await fetch(`https://api.modrinth.com/v2/project/${id}/version?loaders=${lQuery}&game_versions=${vQuery}`);
        const versions = await res.json();

        if(!versions.length) {
            toast(`No version found for ${loaderRaw} ${version}`, true);
            btn.innerHTML = `<span class="text-red-400">Incompatible</span>`;
            setTimeout(() => { btn.innerHTML = ogHtml; btn.disabled = false; }, 2000);
            return;
        }

        // Install the first match
        const file = versions[0].files.find(f => f.primary) || versions[0].files[0];
        btn.innerHTML = `Downloading...`;
        
        const fd = new FormData();
        fd.append("url", file.url);
        fd.append("filename", file.filename);
        fd.append("project_id", id);
        fd.append("version_id", versions[0].id);
        fd.append("name", name);

        const dl = await fetch("/api/plugins/install", {method: "POST", body: fd});
        if(dl.ok) {
            toast(`Installed ${name}`);
            btn.className = "w-full bg-green-600 text-black text-[10px] font-bold py-1.5 rounded flex items-center justify-center gap-1 cursor-default";
            btn.innerHTML = `<i data-lucide="check" class="w-3 h-3"></i> Installed`;
            lucide.createIcons();
        } else {
            throw new Error("Server error");
        }
    } catch(e) {
        toast("Installation failed", true);
        btn.innerHTML = `<span class="text-red-400">Error</span>`;
        setTimeout(() => { btn.innerHTML = ogHtml; btn.disabled = false; }, 2000);
    }
}

async function loadInstalled() {
    const l = document.getElementById("pl-list");
    l.innerHTML = `<div class="col-span-full flex justify-center py-10"><div class="loader"></div></div>`;
    try {
        const r = await fetch("/api/fs/read?path=plugins/plugins.json");
        if(!r.ok) throw new Error();
        const json = await r.json();
        l.innerHTML = "";
        
        if(Object.keys(json).length === 0) {
            l.innerHTML = `<div class="col-span-full text-center text-xs text-zinc-500 py-8">No plugins installed via Panel.</div>`;
            return;
        }

        for(const [pid, data] of Object.entries(json)) {
            const card = document.createElement("div");
            card.className = "bg-[#080808] border border-[#1a1a1a] rounded p-3 flex flex-col gap-2";
            card.innerHTML = `
                <div class="flex justify-between items-start">
                    <h3 class="text-xs font-bold text-zinc-200">${data.name}</h3>
                    <button onclick="delFile('plugins/${data.filename}')" class="text-zinc-600 hover:text-red-500"><i data-lucide="trash" class="w-3 h-3"></i></button>
                </div>
                <div class="text-[10px] text-zinc-500 font-mono truncate">${data.filename}</div>
                <div class="mt-auto flex gap-2">
                    <button class="flex-1 bg-[#111] text-zinc-500 text-[9px] py-1 rounded cursor-not-allowed">Installed</button>
                    <!-- Future: Check update logic here -->
                </div>
            `;
            l.appendChild(card);
        }
        lucide.createIcons();
    } catch(e) {
        l.innerHTML = `<div class="col-span-full text-center text-xs text-zinc-500 py-8">No plugins.json record found.</div>`;
    }
}
</script></body></html>
"""

# --- BACKEND LOGIC ---
def get_path(p: str):
    safe = os.path.abspath(os.path.join(BASE_DIR, (p or "").strip("/")))
    if not safe.startswith(BASE_DIR): raise HTTPException(403, "Access Denied")
    return safe

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

async def boot_mc():
    global mc_process
    jar = os.path.join(BASE_DIR, "purpur.jar")
    if not os.path.exists(jar):
        output_history.append("\x1b[33m[System] purpur.jar not found in /app. Please upload it via Files tab.\x1b[0m")
        return
    
    # Low resource flags
    mc_process = await asyncio.create_subprocess_exec(
        "java", "-Xmx4G", "-Xms1G", "-Dfile.encoding=UTF-8", "-jar", jar, "--nogui",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, cwd=BASE_DIR
    )
    asyncio.create_task(stream_output(mc_process.stdout))

@app.on_event("startup")
async def start():
    os.makedirs(PLUGINS_DIR, exist_ok=True)
    asyncio.create_task(boot_mc())

@app.get("/")
def index(): return HTMLResponse(HTML_CONTENT)

@app.websocket("/ws")
async def ws_end(ws: WebSocket):
    await ws.accept()
    connected_clients.add(ws)
    for l in output_history: await ws.send_text(l)
    try:
        while True:
            cmd = await ws.receive_text()
            if mc_process and mc_process.stdin:
                mc_process.stdin.write((cmd + "\n").encode())
                await mc_process.stdin.drain()
    except: connected_clients.remove(ws)

# FS API
@app.get("/api/fs/list")
def list_fs(path: str=""):
    t = get_path(path)
    if not os.path.exists(t): return []
    res = []
    for x in os.listdir(t):
        fp = os.path.join(t, x)
        res.append({"name": x, "is_dir": os.path.isdir(fp)})
    return sorted(res, key=lambda k: (not k["is_dir"], k["name"].lower()))

@app.post("/api/fs/upload")
async def upload(path: str=Form(""), file: UploadFile=File(...)):
    t = get_path(path)
    os.makedirs(t, exist_ok=True)
    with open(os.path.join(t, file.filename), "wb") as f: shutil.copyfileobj(file.file, f)
    return "ok"

@app.post("/api/fs/delete")
def delete(path: str=Form(...)):
    t = get_path(path)
    if os.path.isdir(t): shutil.rmtree(t)
    else: os.remove(t)
    return "ok"

@app.get("/api/fs/read")
def read(path: str):
    try:
        with open(get_path(path), "r", encoding="utf-8") as f: return json.load(f) if path.endswith(".json") else Response(f.read())
    except: raise HTTPException(404)

# PLUGIN INSTALLER
@app.post("/api/plugins/install")
def install_pl(url: str=Form(...), filename: str=Form(...), project_id: str=Form(...), version_id: str=Form(...), name: str=Form(...)):
    try:
        # Download
        dest = os.path.join(PLUGINS_DIR, filename)
        req = urllib.request.Request(url, headers={'User-Agent': 'HF-Panel/1.0'})
        with urllib.request.urlopen(req) as r, open(dest, 'wb') as f:
            shutil.copyfileobj(r, f)
        
        # Update JSON Record
        j_path = os.path.join(PLUGINS_DIR, "plugins.json")
        data = {}
        if os.path.exists(j_path):
            try:
                with open(j_path, 'r') as f: data = json.load(f)
            except: pass
        
        data[project_id] = {
            "name": name,
            "filename": filename,
            "version_id": version_id,
            "installed_at": time.time()
        }
        
        with open(j_path, 'w') as f: json.dump(data, f, indent=2)
        return "ok"
    except Exception as e:
        raise HTTPException(500, str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 7860)), log_level="error")