import os
import asyncio
import collections
from fastapi import FastAPI, WebSocket, Request, Response, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import shutil
from datetime import datetime

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

mc_process = None
output_history = collections.deque(maxlen=300)
connected_clients = set()
BASE_DIR = os.path.abspath("/app")

# -----------------
# HTML FRONTEND
# -----------------
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Server Control Panel</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm/css/xterm.css" />
    <script src="https://cdn.jsdelivr.net/npm/xterm/lib/xterm.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit/lib/xterm-addon-fit.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        .terminal-container { height: calc(100vh - 180px); width: 100%; padding: 10px; background: #1e1d23; border-radius: 8px;}
        body { background-color: #0f172a; color: #f8fafc; }
        .hidden-tab { display: none; }
    </style>
</head>
<body class="flex flex-col h-screen font-sans">
    <!-- Navbar -->
    <nav class="bg-slate-800 border-b border-slate-700 px-6 py-4 flex justify-between items-center shadow-lg">
        <div class="text-xl font-bold flex items-center gap-2"><i class="fa-solid fa-server text-blue-500"></i> Server Panel</div>
        <div class="flex gap-4">
            <button onclick="switchTab('console')" id="btn-console" class="px-4 py-2 bg-blue-600 rounded-lg font-semibold shadow hover:bg-blue-500 transition"><i class="fa-solid fa-terminal"></i> Console</button>
            <button onclick="switchTab('files')" id="btn-files" class="px-4 py-2 bg-slate-700 rounded-lg font-semibold shadow hover:bg-slate-600 transition"><i class="fa-solid fa-folder"></i> Files</button>
        </div>
    </nav>

    <!-- Main Content -->
    <main class="flex-grow p-4 md:p-6 overflow-hidden flex flex-col">
        <!-- Console Tab -->
        <div id="tab-console" class="flex flex-col h-full w-full max-w-6xl mx-auto">
            <div id="terminal" class="terminal-container shadow-2xl"></div>
            <div class="mt-4 flex gap-2">
                <input type="text" id="cmd-input" class="flex-grow bg-slate-800 border border-slate-600 rounded-lg px-4 py-3 focus:outline-none focus:border-blue-500 shadow-inner" placeholder="Type a console command and press Enter...">
                <button onclick="sendCommand()" class="bg-blue-600 px-6 py-3 rounded-lg font-bold hover:bg-blue-500 transition shadow"><i class="fa-solid fa-paper-plane"></i></button>
            </div>
        </div>

        <!-- File Manager Tab -->
        <div id="tab-files" class="hidden-tab flex flex-col h-full w-full max-w-6xl mx-auto bg-slate-800 rounded-lg shadow-xl overflow-hidden border border-slate-700">
            <div class="bg-slate-900 px-4 py-3 flex justify-between items-center border-b border-slate-700">
                <div class="flex items-center gap-2 text-sm md:text-base font-mono bg-slate-800 px-3 py-1 rounded text-green-400" id="breadcrumbs">/app</div>
                <div class="flex gap-2">
                    <input type="file" id="file-upload" class="hidden" onchange="uploadFile()">
                    <button onclick="document.getElementById('file-upload').click()" class="bg-green-600 px-3 py-1 md:px-4 md:py-2 rounded text-sm font-bold hover:bg-green-500 transition"><i class="fa-solid fa-upload"></i> Upload</button>
                    <button onclick="loadFiles(currentPath)" class="bg-slate-700 px-3 py-1 md:px-4 md:py-2 rounded text-sm font-bold hover:bg-slate-600 transition"><i class="fa-solid fa-rotate-right"></i> Refresh</button>
                </div>
            </div>
            <div class="overflow-y-auto flex-grow p-0">
                <table class="w-full text-left border-collapse">
                    <thead class="bg-slate-900 sticky top-0 shadow">
                        <tr>
                            <th class="p-3 text-slate-300">Name</th>
                            <th class="p-3 text-slate-300 w-24 md:w-32">Size</th>
                            <th class="p-3 text-slate-300 w-32 md:w-48 text-right">Actions</th>
                        </tr>
                    </thead>
                    <tbody id="file-list" class="divide-y divide-slate-700"></tbody>
                </table>
            </div>
        </div>
    </main>

    <!-- Editor Modal -->
    <div id="editor-modal" class="fixed inset-0 bg-black/80 hidden items-center justify-center p-4 z-50">
        <div class="bg-slate-800 rounded-xl w-full max-w-4xl h-[80vh] flex flex-col overflow-hidden border border-slate-600 shadow-2xl">
            <div class="bg-slate-900 p-3 flex justify-between items-center border-b border-slate-700">
                <h3 class="font-mono text-green-400" id="editor-title">file.txt</h3>
                <div class="flex gap-2">
                    <button onclick="saveFile()" class="bg-blue-600 px-4 py-1 rounded hover:bg-blue-500 font-bold">Save</button>
                    <button onclick="closeEditor()" class="bg-slate-700 px-4 py-1 rounded hover:bg-slate-600 font-bold">Close</button>
                </div>
            </div>
            <textarea id="editor-content" class="flex-grow bg-[#1e1e1e] text-slate-200 p-4 font-mono text-sm resize-none focus:outline-none" spellcheck="false"></textarea>
        </div>
    </div>

    <script>
        // --- UI Logic ---
        function switchTab(tab) {
            document.getElementById('tab-console').classList.add('hidden-tab');
            document.getElementById('tab-files').classList.add('hidden-tab');
            document.getElementById('btn-console').classList.replace('bg-blue-600', 'bg-slate-700');
            document.getElementById('btn-files').classList.replace('bg-blue-600', 'bg-slate-700');
            
            document.getElementById('tab-' + tab).classList.remove('hidden-tab');
            document.getElementById('btn-' + tab).classList.replace('bg-slate-700', 'bg-blue-600');

            if(tab === 'console' && fitAddon) setTimeout(() => fitAddon.fit(), 100);
            if(tab === 'files') loadFiles(currentPath);
        }

        // --- Terminal Logic ---
        const term = new Terminal({ theme: { background: '#1e1d23' }, convertEol: true });
        const fitAddon = new FitAddon.FitAddon();
        term.loadAddon(fitAddon);
        term.open(document.getElementById('terminal'));
        fitAddon.fit();
        window.addEventListener('resize', () => fitAddon.fit());

        const wsUrl = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws';
        const ws = new WebSocket(wsUrl);
        ws.onmessage = e => term.write(e.data + '\\n');
        
        const cmdInput = document.getElementById('cmd-input');
        cmdInput.addEventListener('keypress', e => {
            if (e.key === 'Enter' && cmdInput.value.trim() !== '') {
                sendCommand();
            }
        });

        function sendCommand() {
            if(cmdInput.value) { ws.send(cmdInput.value); cmdInput.value = ''; }
        }

        // --- File Manager Logic ---
        let currentPath = '';
        let editingFilePath = '';

        async function loadFiles(path) {
            currentPath = path;
            document.getElementById('breadcrumbs').innerText = '/app' + (path ? '/' + path : '');
            const res = await fetch(`/api/fs/list?path=${encodeURIComponent(path)}`);
            const files = await res.json();
            const list = document.getElementById('file-list');
            list.innerHTML = '';
            
            if (path !== '') {
                const parent = path.split('/').slice(0, -1).join('/');
                list.innerHTML += `<tr class="hover:bg-slate-700/50 cursor-pointer transition" onclick="loadFiles('${parent}')">
                    <td class="p-3"><i class="fa-solid fa-level-up-alt text-slate-400 mr-2"></i> ..</td>
                    <td></td><td></td>
                </tr>`;
            }

            files.forEach(f => {
                const icon = f.is_dir ? '<i class="fa-solid fa-folder text-blue-400"></i>' : '<i class="fa-solid fa-file text-slate-400"></i>';
                const size = f.is_dir ? '-' : (f.size / 1024).toFixed(1) + ' KB';
                const actionClick = f.is_dir ? `onclick="loadFiles('${path ? path+'/'+f.name : f.name}')"` : '';
                
                let row = `<tr class="hover:bg-slate-700/50 transition border-t border-slate-700">
                    <td class="p-3 font-mono text-sm cursor-pointer" ${actionClick}>${icon} &nbsp;${f.name}</td>
                    <td class="p-3 text-slate-400 text-sm">${size}</td>
                    <td class="p-3 text-right">`;
                
                if (!f.is_dir) {
                    row += `<button onclick="editFile('${path ? path+'/'+f.name : f.name}')" class="text-blue-400 hover:text-blue-300 mx-2" title="Edit"><i class="fa-solid fa-edit"></i></button>`;
                    row += `<a href="/api/fs/download?path=${encodeURIComponent(path ? path+'/'+f.name : f.name)}" class="text-green-400 hover:text-green-300 mx-2" title="Download"><i class="fa-solid fa-download"></i></a>`;
                }
                row += `<button onclick="deleteFile('${path ? path+'/'+f.name : f.name}')" class="text-red-400 hover:text-red-300 ml-2" title="Delete"><i class="fa-solid fa-trash"></i></button>`;
                row += `</td></tr>`;
                list.innerHTML += row;
            });
        }

        async function editFile(path) {
            editingFilePath = path;
            const res = await fetch(`/api/fs/read?path=${encodeURIComponent(path)}`);
            if(res.ok) {
                const text = await res.text();
                document.getElementById('editor-content').value = text;
                document.getElementById('editor-title').innerText = path;
                document.getElementById('editor-modal').classList.replace('hidden', 'flex');
            } else {
                alert('Cannot read file (might not be text)');
            }
        }

        function closeEditor() { document.getElementById('editor-modal').classList.replace('flex', 'hidden'); }

        async function saveFile() {
            const content = document.getElementById('editor-content').value;
            const formData = new FormData();
            formData.append('path', editingFilePath);
            formData.append('content', content);
            const res = await fetch('/api/fs/write', { method: 'POST', body: formData });
            if(res.ok) { closeEditor(); } else { alert('Failed to save file.'); }
        }

        async function deleteFile(path) {
            if(confirm('Are you sure you want to delete ' + path + '?')) {
                const formData = new FormData(); formData.append('path', path);
                await fetch('/api/fs/delete', { method: 'POST', body: formData });
                loadFiles(currentPath);
            }
        }

        async function uploadFile() {
            const fileInput = document.getElementById('file-upload');
            if(!fileInput.files.length) return;
            const formData = new FormData();
            formData.append('path', currentPath);
            formData.append('file', fileInput.files[0]);
            await fetch('/api/fs/upload', { method: 'POST', body: formData });
            fileInput.value = '';
            loadFiles(currentPath);
        }
    </script>
</body>
</html>
"""

# -----------------
# UTILITIES
# -----------------
def get_safe_path(subpath: str):
    subpath = (subpath or "").strip("/")
    target = os.path.abspath(os.path.join(BASE_DIR, subpath))
    if not target.startswith(BASE_DIR):
        raise HTTPException(status_code=403, detail="Access denied outside /app")
    return target

async def broadcast(message: str):
    output_history.append(message)
    dead_clients = set()
    for client in connected_clients:
        try:
            await client.send_text(message)
        except:
            dead_clients.add(client)
    connected_clients.difference_update(dead_clients)

# -----------------
# SERVER PROCESSES
# -----------------
async def read_stream(stream, prefix=""):
    while True:
        line = await stream.readline()
        if not line: break
        line_str = line.decode('utf-8', errors='replace').rstrip('\r\n')
        await broadcast(prefix + line_str)

async def start_minecraft():
    global mc_process
    java_args = [
        "java", "-server", "-Xmx8G", "-Xms8G", "-XX:+UseG1GC", "-XX:+ParallelRefProcEnabled",
        "-XX:ParallelGCThreads=2", "-XX:ConcGCThreads=1", "-XX:MaxGCPauseMillis=50",
        "-XX:+UnlockExperimentalVMOptions", "-XX:+DisableExplicitGC", "-XX:+AlwaysPreTouch",
        "-XX:G1NewSizePercent=30", "-XX:G1MaxNewSizePercent=50", "-XX:G1HeapRegionSize=16M",
        "-XX:G1ReservePercent=15", "-XX:G1HeapWastePercent=5", "-XX:G1MixedGCCountTarget=3",
        "-XX:InitiatingHeapOccupancyPercent=10", "-XX:G1MixedGCLiveThresholdPercent=90",
        "-XX:G1RSetUpdatingPauseTimePercent=5", "-XX:SurvivorRatio=32", "-XX:+PerfDisableSharedMem",
        "-XX:MaxTenuringThreshold=1", "-XX:G1SATBBufferEnqueueingThresholdPercent=30",
        "-XX:G1ConcMarkStepDurationMillis=5", "-XX:G1ConcRSHotCardLimit=16",
        "-XX:+UseStringDeduplication", "-Dfile.encoding=UTF-8", "-Dspring.output.ansi.enabled=ALWAYS",
        "-jar", "purpur.jar", "--nogui"
    ]
    mc_process = await asyncio.create_subprocess_exec(
        *java_args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=BASE_DIR
    )
    asyncio.create_task(read_stream(mc_process.stdout))

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(start_minecraft())

# -----------------
# API ROUTING
# -----------------
@app.get("/")
def get_panel():
    return HTMLResponse(content=HTML_CONTENT)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)
    for line in output_history:
        await websocket.send_text(line)
    try:
        while True:
            cmd = await websocket.receive_text()
            if mc_process and mc_process.stdin:
                mc_process.stdin.write((cmd + "\n").encode('utf-8'))
                await mc_process.stdin.drain()
    except:
        connected_clients.remove(websocket)

@app.get("/api/fs/list")
def fs_list(path: str = ""):
    target = get_safe_path(path)
    if not os.path.exists(target): return []
    items = []
    for f in os.listdir(target):
        fp = os.path.join(target, f)
        items.append({"name": f, "is_dir": os.path.isdir(fp), "size": os.path.getsize(fp) if not os.path.isdir(fp) else 0})
    return sorted(items, key=lambda x: (not x["is_dir"], x["name"].lower()))

@app.get("/api/fs/read")
def fs_read(path: str):
    target = get_safe_path(path)
    if not os.path.isfile(target): raise HTTPException(400, "Not a file")
    with open(target, 'r', encoding='utf-8', errors='ignore') as f:
        return Response(content=f.read(), media_type="text/plain")

@app.get("/api/fs/download")
def fs_download(path: str):
    target = get_safe_path(path)
    if not os.path.isfile(target): raise HTTPException(400, "Not a file")
    return FileResponse(target, filename=os.path.basename(target))

@app.post("/api/fs/write")
def fs_write(path: str = Form(...), content: str = Form(...)):
    target = get_safe_path(path)
    with open(target, 'w', encoding='utf-8') as f:
        f.write(content)
    return {"status": "ok"}

@app.post("/api/fs/upload")
async def fs_upload(path: str = Form(""), file: UploadFile = File(...)):
    target_dir = get_safe_path(path)
    target_file = os.path.join(target_dir, file.filename)
    with open(target_file, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"status": "ok"}

@app.post("/api/fs/delete")
def fs_delete(path: str = Form(...)):
    target = get_safe_path(path)
    if os.path.isdir(target): shutil.rmtree(target)
    else: os.remove(target)
    return {"status": "ok"}

if __name__ == "__main__":
    # Binds Web UI to Port 7860 to satisfy Hugging Face HTTP Health Checks!
    uvicorn.run(app, host="0.0.0.0", port=7860, log_level="warning")