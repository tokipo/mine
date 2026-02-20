import os
import asyncio
import collections
from fastapi import FastAPI, WebSocket, Request, Response, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import shutil

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

mc_process = None
output_history = collections.deque(maxlen=300)
connected_clients = set()
BASE_DIR = os.path.abspath("/app")

# -----------------
# HTML FRONTEND (Ultra-Modern UI)
# -----------------
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Server Console</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/lucide@latest"></script>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm/css/xterm.css" />
    <script src="https://cdn.jsdelivr.net/npm/xterm/lib/xterm.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit/lib/xterm-addon-fit.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root { --bg: #09090b; --surface: #18181b; --surface-hover: #27272a; --border: #27272a; --text: #fafafa; --text-muted: #a1a1aa; --accent: #3b82f6; }
        body { background-color: var(--bg); color: var(--text); font-family: 'Inter', sans-serif; overflow: hidden; -webkit-font-smoothing: antialiased; }
        .font-mono { font-family: 'JetBrains Mono', monospace; }
        
        /* Glass Navbar */
        .glass-nav { background: rgba(9, 9, 11, 0.8); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); border-bottom: 1px solid var(--border); z-index: 40; }
        
        /* Animations */
        .fade-in { animation: fadeIn 0.3s cubic-bezier(0.16, 1, 0.3, 1) forwards; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }
        
        /* Terminal Styling with Top Fade */
        .term-container { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; overflow: hidden; position: relative; }
        .term-wrapper { padding: 12px; height: calc(100vh - 180px); width: 100%; mask-image: linear-gradient(to bottom, transparent 0%, black 5%, black 100%); -webkit-mask-image: linear-gradient(to bottom, transparent 0%, black 5%, black 100%); }
        .xterm-viewport::-webkit-scrollbar { width: 8px; }
        .xterm-viewport::-webkit-scrollbar-thumb { background: #3f3f46; border-radius: 4px; }
        
        /* File Manager Layout */
        .file-row { transition: all 0.15s ease; border-bottom: 1px solid var(--border); }
        .file-row:hover { background: var(--surface-hover); }
        .file-row:last-child { border-bottom: none; }
        
        /* Custom Scrollbars */
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #3f3f46; border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: #52525b; }

        /* Loader */
        .loader { animation: spin 1s linear infinite; }
        @keyframes spin { 100% { transform: rotate(360deg); } }
        
        /* Utility */
        .hidden-tab { display: none !important; }
        input[type="text"]:focus, textarea:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
    </style>
</head>
<body class="flex flex-col h-screen w-full">

    <!-- Top Navigation -->
    <nav class="glass-nav w-full px-4 sm:px-6 py-3 flex justify-between items-center fixed top-0 left-0 right-0 h-[60px]">
        <div class="flex items-center gap-3">
            <div class="bg-blue-500/10 p-2 rounded-lg border border-blue-500/20">
                <i data-lucide="server" class="w-5 h-5 text-blue-400"></i>
            </div>
            <span class="font-semibold tracking-tight text-sm sm:text-base text-gray-100">Minecraft Engine</span>
            <span class="px-2 py-0.5 rounded-full bg-green-500/10 text-green-400 border border-green-500/20 text-[10px] font-bold tracking-wide uppercase hidden sm:block">Online</span>
        </div>
        
        <div class="flex gap-1 sm:gap-2 bg-zinc-900 p-1 rounded-lg border border-zinc-800">
            <button onclick="switchTab('console')" id="btn-console" class="flex items-center gap-2 px-3 py-1.5 sm:px-4 sm:py-2 bg-zinc-800 text-gray-100 rounded-md text-xs sm:text-sm font-medium transition-all shadow-sm">
                <i data-lucide="terminal" class="w-4 h-4"></i><span class="hidden sm:inline">Console</span>
            </button>
            <button onclick="switchTab('files')" id="btn-files" class="flex items-center gap-2 px-3 py-1.5 sm:px-4 sm:py-2 text-zinc-400 hover:text-gray-200 rounded-md text-xs sm:text-sm font-medium transition-all">
                <i data-lucide="folder-code" class="w-4 h-4"></i><span class="hidden sm:inline">Files</span>
            </button>
        </div>
    </nav>

    <!-- Main Content Area -->
    <main class="mt-[60px] flex-grow p-3 sm:p-4 overflow-hidden relative">
        
        <!-- Console Tab -->
        <div id="tab-console" class="h-full w-full max-w-7xl mx-auto flex flex-col fade-in">
            <div class="term-container shadow-2xl flex-grow flex flex-col">
                <div class="bg-zinc-900 border-b border-zinc-800 px-4 py-2 flex items-center gap-2 text-xs text-zinc-400 font-mono">
                    <div class="flex gap-1.5"><div class="w-2.5 h-2.5 rounded-full bg-red-500/80"></div><div class="w-2.5 h-2.5 rounded-full bg-yellow-500/80"></div><div class="w-2.5 h-2.5 rounded-full bg-green-500/80"></div></div>
                    <span class="ml-2">server-stdout</span>
                </div>
                <div id="terminal" class="term-wrapper"></div>
            </div>
            
            <div class="mt-3 sm:mt-4 relative">
                <div class="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none text-zinc-500">
                    <i data-lucide="chevron-right" class="w-5 h-5"></i>
                </div>
                <input type="text" id="cmd-input" class="w-full bg-zinc-900 border border-zinc-800 text-gray-200 rounded-lg pl-10 pr-12 py-3 text-sm font-mono transition-all shadow-inner placeholder-zinc-600" placeholder="Execute command...">
                <button onclick="sendCommand()" class="absolute inset-y-1 right-1 px-3 bg-blue-600 hover:bg-blue-500 text-white rounded-md transition-colors flex items-center justify-center">
                    <i data-lucide="send" class="w-4 h-4"></i>
                </button>
            </div>
        </div>

        <!-- File Manager Tab -->
        <div id="tab-files" class="hidden-tab h-full w-full max-w-7xl mx-auto flex flex-col bg-[#18181b] rounded-xl border border-zinc-800 shadow-2xl overflow-hidden">
            <!-- File Header / Breadcrumbs -->
            <div class="bg-zinc-900/50 px-4 py-3 border-b border-zinc-800 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-3">
                <div class="flex items-center text-sm font-mono text-zinc-400 overflow-x-auto whitespace-nowrap hide-scrollbar w-full sm:w-auto" id="breadcrumbs">
                    <!-- Injected via JS -->
                </div>
                <div class="flex items-center gap-2 shrink-0">
                    <input type="file" id="file-upload" class="hidden" onchange="uploadFile(event)">
                    <button onclick="document.getElementById('file-upload').click()" class="flex items-center gap-1.5 bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 px-3 py-1.5 rounded-md text-xs font-medium text-gray-200 transition-colors">
                        <i data-lucide="upload-cloud" class="w-4 h-4 text-blue-400"></i> Upload
                    </button>
                    <button onclick="loadFiles(currentPath)" class="flex items-center justify-center bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 w-8 h-8 rounded-md transition-colors">
                        <i data-lucide="refresh-cw" class="w-4 h-4 text-zinc-400"></i>
                    </button>
                </div>
            </div>
            
            <!-- File List Columns -->
            <div class="hidden sm:grid grid-cols-12 gap-4 px-5 py-2 border-b border-zinc-800 bg-zinc-900/80 text-xs font-semibold text-zinc-500 uppercase tracking-wider">
                <div class="col-span-7">Name</div>
                <div class="col-span-3 text-right">Size</div>
                <div class="col-span-2 text-right">Actions</div>
            </div>

            <!-- File List -->
            <div class="flex-grow overflow-y-auto" id="file-list">
                <!-- Injected via JS -->
            </div>
        </div>
    </main>

    <!-- Code Editor Modal -->
    <div id="editor-modal" class="fixed inset-0 bg-black/60 backdrop-blur-sm hidden items-center justify-center p-2 sm:p-6 z-50 opacity-0 transition-opacity duration-300">
        <div class="bg-[#18181b] rounded-xl border border-zinc-800 w-full max-w-5xl h-[90vh] sm:h-[85vh] flex flex-col shadow-2xl transform scale-95 transition-transform duration-300" id="editor-card">
            <div class="bg-zinc-900 px-4 py-3 flex justify-between items-center border-b border-zinc-800 rounded-t-xl">
                <div class="flex items-center gap-2 text-sm font-mono text-gray-300">
                    <i data-lucide="file-code" class="w-4 h-4 text-blue-400"></i>
                    <span id="editor-title">filename.txt</span>
                </div>
                <div class="flex items-center gap-2">
                    <button onclick="closeEditor()" class="px-3 py-1.5 hover:bg-zinc-800 rounded text-xs font-medium text-zinc-400 transition-colors">Cancel</button>
                    <button onclick="saveFile()" class="px-4 py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded text-xs font-semibold transition-colors flex items-center gap-1.5 shadow-lg shadow-blue-500/20">
                        <i data-lucide="save" class="w-3.5 h-3.5"></i> Save
                    </button>
                </div>
            </div>
            <textarea id="editor-content" class="flex-grow bg-[#0e0e11] text-zinc-300 p-4 font-mono text-xs sm:text-sm resize-none focus:outline-none w-full leading-relaxed" spellcheck="false"></textarea>
        </div>
    </div>

    <!-- Toast Notifications -->
    <div id="toast-container" class="fixed bottom-4 right-4 z-[100] flex flex-col gap-2"></div>

    <script>
        // Initialize Lucide Icons
        lucide.createIcons();

        // --- Toast System ---
        function showToast(message, type = 'info') {
            const container = document.getElementById('toast-container');
            const toast = document.createElement('div');
            
            let icon = '<i data-lucide="info" class="w-4 h-4 text-blue-400"></i>';
            let border = 'border-blue-500/20';
            if(type === 'success') { icon = '<i data-lucide="check-circle" class="w-4 h-4 text-green-400"></i>'; border = 'border-green-500/20'; }
            if(type === 'error') { icon = '<i data-lucide="alert-circle" class="w-4 h-4 text-red-400"></i>'; border = 'border-red-500/20'; }

            toast.className = `flex items-center gap-3 bg-zinc-900 border ${border} text-sm text-gray-200 px-4 py-3 rounded-lg shadow-xl translate-y-8 opacity-0 transition-all duration-300`;
            toast.innerHTML = `${icon} <span>${message}</span>`;
            
            container.appendChild(toast);
            lucide.createIcons();
            
            // Animate In
            requestAnimationFrame(() => {
                toast.classList.remove('translate-y-8', 'opacity-0');
            });

            // Animate Out
            setTimeout(() => {
                toast.classList.add('translate-y-8', 'opacity-0');
                setTimeout(() => toast.remove(), 300);
            }, 3000);
        }

        // --- UI Navigation ---
        function switchTab(tab) {
            document.getElementById('tab-console').classList.add('hidden-tab');
            document.getElementById('tab-files').classList.add('hidden-tab');
            
            document.getElementById('btn-console').className = "flex items-center gap-2 px-3 py-1.5 sm:px-4 sm:py-2 text-zinc-400 hover:text-gray-200 rounded-md text-xs sm:text-sm font-medium transition-all";
            document.getElementById('btn-files').className = "flex items-center gap-2 px-3 py-1.5 sm:px-4 sm:py-2 text-zinc-400 hover:text-gray-200 rounded-md text-xs sm:text-sm font-medium transition-all";
            
            document.getElementById('tab-' + tab).classList.remove('hidden-tab');
            document.getElementById('tab-' + tab).classList.add('fade-in');
            
            const activeBtn = document.getElementById('btn-' + tab);
            activeBtn.className = "flex items-center gap-2 px-3 py-1.5 sm:px-4 sm:py-2 bg-zinc-800 text-gray-100 rounded-md text-xs sm:text-sm font-medium transition-all shadow-sm";

            if(tab === 'console' && fitAddon) { setTimeout(() => fitAddon.fit(), 50); }
            if(tab === 'files' && !currentPathLoaded) { loadFiles(''); currentPathLoaded = true; }
        }

        // --- Terminal Logic ---
        const term = new Terminal({ 
            theme: { background: 'transparent', foreground: '#e4e4e7', cursor: '#3b82f6', selectionBackground: 'rgba(59, 130, 246, 0.3)' }, 
            convertEol: true, cursorBlink: true, fontFamily: "'JetBrains Mono', monospace", fontSize: 13, fontWeight: 400
        });
        const fitAddon = new FitAddon.FitAddon();
        term.loadAddon(fitAddon);
        term.open(document.getElementById('terminal'));
        
        // Wait slightly for DOM to render to fit exactly
        setTimeout(() => fitAddon.fit(), 100);
        window.addEventListener('resize', () => { if(!document.getElementById('tab-console').classList.contains('hidden-tab')) fitAddon.fit(); });

        const wsUrl = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws';
        let ws;
        
        function connectWS() {
            ws = new WebSocket(wsUrl);
            ws.onopen = () => term.write('\\x1b[32m\\x1b[1m[Panel]\\x1b[0m Connected to server stream.\\r\\n');
            ws.onmessage = e => term.write(e.data + '\\n');
            ws.onclose = () => { term.write('\\r\\n\\x1b[31m\\x1b[1m[Panel]\\x1b[0m Connection lost. Reconnecting in 3s...\\r\\n'); setTimeout(connectWS, 3000); };
        }
        connectWS();
        
        const cmdInput = document.getElementById('cmd-input');
        cmdInput.addEventListener('keypress', e => { if (e.key === 'Enter') sendCommand(); });

        function sendCommand() {
            const val = cmdInput.value.trim();
            if(val && ws && ws.readyState === WebSocket.OPEN) { 
                term.write(`\\x1b[90m> ${val}\\x1b[0m\\r\\n`);
                ws.send(val); 
                cmdInput.value = ''; 
            }
        }

        // --- File Manager Logic ---
        let currentPath = '';
        let currentPathLoaded = false;
        let editingFilePath = '';

        function renderBreadcrumbs(path) {
            const parts = path.split('/').filter(p => p);
            let html = `<button onclick="loadFiles('')" class="hover:text-gray-200 transition-colors"><i data-lucide="home" class="w-4 h-4"></i></button>`;
            let buildPath = '';
            
            if (parts.length > 0) {
                parts.forEach((part, index) => {
                    buildPath += (buildPath ? '/' : '') + part;
                    html += ` <i data-lucide="chevron-right" class="w-3.5 h-3.5 mx-1 opacity-50"></i> `;
                    if(index === parts.length - 1) {
                        html += `<span class="text-blue-400 font-medium">${part}</span>`;
                    } else {
                        html += `<button onclick="loadFiles('${buildPath}')" class="hover:text-gray-200 transition-colors">${part}</button>`;
                    }
                });
            }
            document.getElementById('breadcrumbs').innerHTML = html;
            lucide.createIcons();
        }

        async function loadFiles(path) {
            currentPath = path;
            renderBreadcrumbs(path);
            const list = document.getElementById('file-list');
            list.innerHTML = `<div class="flex justify-center py-8"><i data-lucide="loader-2" class="w-6 h-6 text-zinc-500 loader"></i></div>`;
            lucide.createIcons();

            try {
                const res = await fetch(`/api/fs/list?path=${encodeURIComponent(path)}`);
                if(!res.ok) throw new Error('Failed to load');
                const files = await res.json();
                list.innerHTML = '';
                
                if (path !== '') {
                    const parent = path.split('/').slice(0, -1).join('/');
                    list.innerHTML += `
                        <div class="file-row flex items-center px-5 py-3 cursor-pointer" onclick="loadFiles('${parent}')">
                            <div class="flex items-center gap-3 w-full">
                                <i data-lucide="corner-left-up" class="w-4 h-4 text-zinc-500"></i>
                                <span class="text-sm font-mono text-zinc-400">..</span>
                            </div>
                        </div>`;
                }

                if(files.length === 0 && path === '') {
                    list.innerHTML += `<div class="text-center py-8 text-zinc-500 text-sm">Directory is empty</div>`;
                }

                files.forEach(f => {
                    const icon = f.is_dir ? '<i data-lucide="folder" class="w-4 h-4 text-blue-400 fill-blue-400/10"></i>' : '<i data-lucide="file" class="w-4 h-4 text-zinc-400"></i>';
                    const sizeStr = f.is_dir ? '--' : (f.size > 1024*1024 ? (f.size/(1024*1024)).toFixed(1) + ' MB' : (f.size / 1024).toFixed(1) + ' KB');
                    const fullPath = path ? `${path}/${f.name}` : f.name;
                    const actionClick = f.is_dir ? `onclick="loadFiles('${fullPath}')"` : '';
                    const pointer = f.is_dir ? 'cursor-pointer' : '';

                    list.innerHTML += `
                        <div class="file-row flex flex-col sm:grid sm:grid-cols-12 items-start sm:items-center px-5 py-3 gap-2 sm:gap-4 group">
                            <div class="col-span-7 flex items-center gap-3 w-full ${pointer}" ${actionClick}>
                                ${icon}
                                <span class="text-sm font-mono text-gray-200 truncate group-hover:text-blue-400 transition-colors">${f.name}</span>
                            </div>
                            <div class="col-span-3 text-right text-xs text-zinc-500 font-mono hidden sm:block">${sizeStr}</div>
                            <div class="col-span-2 flex justify-end gap-1 sm:gap-2 w-full sm:w-auto mt-2 sm:mt-0 sm:opacity-0 group-hover:opacity-100 transition-opacity">
                                ${!f.is_dir ? `<button onclick="editFile('${fullPath}')" class="p-1.5 text-zinc-400 hover:text-blue-400 hover:bg-blue-500/10 rounded transition-colors" title="Edit"><i data-lucide="edit-3" class="w-4 h-4"></i></button>` : ''}
                                ${!f.is_dir ? `<a href="/api/fs/download?path=${encodeURIComponent(fullPath)}" class="p-1.5 text-zinc-400 hover:text-green-400 hover:bg-green-500/10 rounded transition-colors inline-block" title="Download"><i data-lucide="download" class="w-4 h-4"></i></a>` : ''}
                                <button onclick="deleteFile('${fullPath}')" class="p-1.5 text-zinc-400 hover:text-red-400 hover:bg-red-500/10 rounded transition-colors" title="Delete"><i data-lucide="trash-2" class="w-4 h-4"></i></button>
                            </div>
                        </div>`;
                });
                lucide.createIcons();
            } catch (err) {
                showToast("Failed to load directory", "error");
                list.innerHTML = `<div class="text-center py-8 text-red-400 text-sm">Error loading files</div>`;
            }
        }

        async function editFile(path) {
            try {
                const res = await fetch(`/api/fs/read?path=${encodeURIComponent(path)}`);
                if(res.ok) {
                    const text = await res.text();
                    editingFilePath = path;
                    document.getElementById('editor-content').value = text;
                    document.getElementById('editor-title').innerText = path.split('/').pop();
                    
                    const modal = document.getElementById('editor-modal');
                    const card = document.getElementById('editor-card');
                    modal.classList.remove('hidden');
                    modal.classList.add('flex');
                    
                    // Animate In
                    requestAnimationFrame(() => {
                        modal.classList.remove('opacity-0');
                        card.classList.remove('scale-95');
                    });
                } else {
                    showToast('Cannot open file (might be binary)', 'error');
                }
            } catch {
                showToast('Failed to open file', 'error');
            }
        }

        function closeEditor() {
            const modal = document.getElementById('editor-modal');
            const card = document.getElementById('editor-card');
            modal.classList.add('opacity-0');
            card.classList.add('scale-95');
            setTimeout(() => {
                modal.classList.add('hidden');
                modal.classList.remove('flex');
            }, 300);
        }

        async function saveFile() {
            const btn = document.querySelector('#editor-modal button.bg-blue-600');
            const originalHTML = btn.innerHTML;
            btn.innerHTML = `<i data-lucide="loader-2" class="w-3.5 h-3.5 loader"></i> Saving...`;
            lucide.createIcons();

            const content = document.getElementById('editor-content').value;
            const formData = new FormData();
            formData.append('path', editingFilePath);
            formData.append('content', content);
            
            try {
                const res = await fetch('/api/fs/write', { method: 'POST', body: formData });
                if(res.ok) { 
                    showToast('File saved successfully', 'success');
                    closeEditor(); 
                } else throw new Error();
            } catch {
                showToast('Failed to save file', 'error');
            } finally {
                btn.innerHTML = originalHTML;
                lucide.createIcons();
            }
        }

        async function deleteFile(path) {
            if(confirm('Are you sure you want to delete ' + path.split('/').pop() + '?')) {
                const formData = new FormData(); formData.append('path', path);
                try {
                    const res = await fetch('/api/fs/delete', { method: 'POST', body: formData });
                    if(res.ok) {
                        showToast('Deleted successfully', 'success');
                        loadFiles(currentPath);
                    } else throw new Error();
                } catch {
                    showToast('Failed to delete', 'error');
                }
            }
        }

        async function uploadFile(e) {
            const fileInput = e.target;
            if(!fileInput.files.length) return;
            
            showToast('Uploading ' + fileInput.files[0].name + '...', 'info');
            
            const formData = new FormData();
            formData.append('path', currentPath);
            formData.append('file', fileInput.files[0]);
            
            try {
                const res = await fetch('/api/fs/upload', { method: 'POST', body: formData });
                if(res.ok) {
                    showToast('Upload complete', 'success');
                    loadFiles(currentPath);
                } else throw new Error();
            } catch {
                showToast('Upload failed', 'error');
            }
            fileInput.value = '';
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
        try:
            line = await stream.readline()
            if not line: break
            line_str = line.decode('utf-8', errors='replace').rstrip('\r\n')
            await broadcast(prefix + line_str)
        except Exception:
            break

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
    try:
        with open(target, 'r', encoding='utf-8') as f:
            return Response(content=f.read(), media_type="text/plain")
    except UnicodeDecodeError:
        # Prevent binary files (like .jar or .world) from crashing the API/Frontend
        raise HTTPException(400, "File is binary or unsupported encoding")

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
    uvicorn.run(app, host="0.0.0.0", port=7860, log_level="warning")