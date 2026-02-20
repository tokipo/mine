import os
import asyncio
import collections
import shutil
from fastapi import FastAPI, WebSocket, Request, Response, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

mc_process = None
output_history = collections.deque(maxlen=300)
connected_clients = set()
BASE_DIR = os.path.abspath("/app")

# -----------------
# HTML FRONTEND (Web3 / Modern SaaS Dashboard)
# -----------------
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>ServerSpace | Dashboard</title>
    
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <script src="https://unpkg.com/@phosphor-icons/web"></script>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm/css/xterm.css" />
    <script src="https://cdn.jsdelivr.net/npm/xterm/lib/xterm.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit/lib/xterm-addon-fit.js"></script>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    fontFamily: { sans: ['Inter', 'sans-serif'], mono: ['JetBrains Mono', 'monospace'] },
                    colors: {
                        base: '#06080D',
                        surface: '#10141F',
                        surfaceHover: '#1A2133',
                        border: '#232B40',
                        primary: '#8B5CF6',     /* Violet */
                        secondary: '#D946EF',   /* Fuchsia */
                        accent: '#0EA5E9'       /* Cyan */
                    },
                    boxShadow: {
                        'neon': '0 0 20px rgba(139, 92, 246, 0.3)',
                        'neon-strong': '0 0 30px rgba(217, 70, 239, 0.4)'
                    }
                }
            }
        }
    </script>
    <style>
        body { background-color: theme('colors.base'); color: #F8FAFC; overflow: hidden; -webkit-font-smoothing: antialiased; }
        
        /* Ambient Background Glows */
        .ambient-glow-1 { position: absolute; top: -10%; left: -10%; width: 40vw; height: 40vw; background: radial-gradient(circle, rgba(139,92,246,0.15) 0%, rgba(0,0,0,0) 70%); border-radius: 50%; pointer-events: none; z-index: 0; filter: blur(60px); }
        .ambient-glow-2 { position: absolute; bottom: -20%; right: -10%; width: 50vw; height: 50vw; background: radial-gradient(circle, rgba(217,70,239,0.1) 0%, rgba(0,0,0,0) 70%); border-radius: 50%; pointer-events: none; z-index: 0; filter: blur(80px); }

        /* Dashboard Cards - Glassmorphism */
        .premium-card {
            background: rgba(16, 20, 31, 0.6);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 24px;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
            position: relative;
            overflow: hidden;
            z-index: 10;
        }

        /* Gradients & Buttons */
        .text-gradient { background: linear-gradient(135deg, theme('colors.primary'), theme('colors.secondary')); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .bg-gradient-btn { 
            background: linear-gradient(135deg, theme('colors.primary'), theme('colors.secondary')); 
            box-shadow: 0 4px 15px rgba(139, 92, 246, 0.3); 
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1); 
            position: relative;
            overflow: hidden;
        }
        .bg-gradient-btn::before {
            content: ''; position: absolute; top: 0; left: -100%; width: 100%; height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent);
            transition: all 0.5s ease;
        }
        .bg-gradient-btn:hover { transform: translateY(-2px); box-shadow: theme('boxShadow.neon-strong'); filter: brightness(1.1); }
        .bg-gradient-btn:hover::before { left: 100%; }
        
        /* Terminal Fixing for Mobile Wrapping */
        .term-container { flex: 1; min-width: 0; min-height: 0; width: 100%; height: 100%; overflow: hidden; position: relative; }
        .term-wrapper { padding: 16px; height: 100%; width: 100%; }
        .xterm .xterm-viewport { overflow-y: auto !important; width: 100% !important; background-color: transparent !important; }
        .xterm-screen { width: 100% !important; }
        
        /* Custom Scrollbar */
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: theme('colors.border'); border-radius: 10px; }
        ::-webkit-scrollbar-thumb:hover { background: theme('colors.primary'); }

        /* Navigation States */
        .nav-item { color: #64748B; transition: all 0.3s ease; position: relative; }
        .nav-item:hover { color: #F8FAFC; background: rgba(255,255,255,0.03); }
        .nav-item.active { color: #F8FAFC; background: linear-gradient(90deg, rgba(139, 92, 246, 0.15) 0%, transparent 100%); border-left: 3px solid theme('colors.primary'); }
        
        /* Mobile Nav Floating Glass */
        .mobile-nav-glass {
            background: rgba(16, 20, 31, 0.85);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            box-shadow: 0 -10px 40px rgba(0,0,0,0.5);
            margin: 0 16px 16px 16px;
            border-radius: 24px;
        }

        .mob-nav-item { color: #64748B; transition: color 0.3s; }
        .mob-nav-item.active { color: theme('colors.primary'); text-shadow: 0 0 15px rgba(139,92,246,0.5); }
        
        /* Animations */
        .fade-in { animation: fadeIn 0.4s cubic-bezier(0.16, 1, 0.3, 1) forwards; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px) scale(0.98); } to { opacity: 1; transform: translateY(0) scale(1); } }
        .hidden-tab { display: none !important; }
    </style>
</head>
<body class="flex flex-col md:flex-row h-[100dvh] w-full text-sm md:text-base relative">

    <div class="ambient-glow-1"></div>
    <div class="ambient-glow-2"></div>

    <aside class="hidden md:flex flex-col w-[280px] bg-surface/40 backdrop-blur-xl border-r border-white/5 shrink-0 z-20 shadow-2xl">
        <div class="p-8 pb-4">
            <div class="flex items-center gap-4">
                <div class="w-12 h-12 rounded-2xl bg-gradient-btn flex items-center justify-center shadow-neon">
                    <i class="ph ph-hexagon text-2xl text-white"></i>
                </div>
                <div>
                    <h1 class="font-bold text-xl text-white tracking-tight">Server<span class="text-gradient">Space</span></h1>
                    <p class="text-[11px] text-primary font-mono uppercase tracking-widest mt-0.5">Engine v2.0</p>
                </div>
            </div>
        </div>

        <div class="px-6 py-6 flex-grow">
            <div class="text-[11px] font-bold text-slate-500 uppercase tracking-widest mb-4 px-3">Dashboard</div>
            <nav class="flex flex-col gap-2">
                <button onclick="switchTab('console')" id="nav-console" class="nav-item active flex items-center gap-4 px-4 py-3.5 rounded-r-xl font-medium">
                    <i class="ph ph-terminal-window text-xl"></i> Console
                </button>
                <button onclick="switchTab('files')" id="nav-files" class="nav-item flex items-center gap-4 px-4 py-3.5 rounded-r-xl font-medium border-l-3 border-transparent">
                    <i class="ph ph-folder-notch text-xl"></i> File Explorer
                </button>
            </nav>
        </div>

        <div class="p-6">
            <div class="bg-black/30 border border-white/5 rounded-2xl p-4 flex items-center gap-4 backdrop-blur-md">
                <div class="relative flex h-4 w-4">
                  <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent opacity-60"></span>
                  <span class="relative inline-flex rounded-full h-4 w-4 bg-accent shadow-[0_0_10px_#0EA5E9]"></span>
                </div>
                <div>
                    <div class="text-sm font-semibold text-white">System Online</div>
                    <div class="text-xs font-mono text-slate-400 mt-0.5">Latency: 24ms</div>
                </div>
            </div>
        </div>
    </aside>

    <header class="md:hidden flex justify-between items-center px-6 py-5 bg-surface/80 backdrop-blur-md border-b border-white/5 shrink-0 z-20">
        <div class="flex items-center gap-3">
            <div class="w-10 h-10 rounded-xl bg-gradient-btn flex items-center justify-center">
                <i class="ph ph-hexagon text-xl text-white"></i>
            </div>
            <h1 class="font-bold text-lg text-white">Server<span class="text-gradient">Space</span></h1>
        </div>
        <div class="relative flex h-3 w-3">
          <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent opacity-60"></span>
          <span class="relative inline-flex rounded-full h-3 w-3 bg-accent"></span>
        </div>
    </header>

    <main class="flex-grow flex flex-col p-4 md:p-8 overflow-hidden min-w-0 relative z-10 pb-24 md:pb-8">
        
        <div id="tab-console" class="h-full flex flex-col fade-in min-w-0">
            <div class="mb-4 hidden md:flex justify-between items-end">
                <div>
                    <h2 class="text-2xl font-bold text-white">Live Terminal</h2>
                    <p class="text-slate-400 text-sm mt-1">Execute commands directly on the server container.</p>
                </div>
            </div>

            <div class="premium-card flex flex-col flex-grow min-h-0">
                <div class="bg-black/40 border-b border-white/5 px-5 py-4 flex items-center justify-between z-10 shrink-0">
                    <div class="flex gap-2">
                        <div class="w-3.5 h-3.5 rounded-full bg-red-500/80 shadow-[0_0_8px_rgba(239,68,68,0.5)]"></div>
                        <div class="w-3.5 h-3.5 rounded-full bg-yellow-500/80 shadow-[0_0_8px_rgba(234,179,8,0.5)]"></div>
                        <div class="w-3.5 h-3.5 rounded-full bg-green-500/80 shadow-[0_0_8px_rgba(34,197,94,0.5)]"></div>
                    </div>
                    <span class="text-xs font-mono text-slate-400 bg-white/5 px-3 py-1 rounded-full border border-white/5">root@serverspace:~</span>
                    <div class="w-14"></div> </div>
                
                <div class="term-container bg-transparent">
                    <div id="terminal" class="term-wrapper"></div>
                </div>

                <div class="p-3 md:p-5 bg-black/40 border-t border-white/5 z-10 shrink-0 backdrop-blur-xl">
                    <div class="relative flex items-center">
                        <i class="ph ph-caret-right text-primary absolute left-5 text-xl animate-pulse"></i>
                        <input type="text" id="cmd-input" class="w-full bg-surfaceHover/50 border border-white/10 focus:border-primary/50 focus:bg-surfaceHover text-white rounded-xl pl-12 pr-14 py-3.5 md:py-4 text-sm font-mono transition-all outline-none shadow-inner" placeholder="Enter command...">
                        <button onclick="sendCommand()" class="absolute right-2 p-2.5 bg-gradient-btn rounded-lg text-white">
                            <i class="ph-bold ph-paper-plane-right text-lg"></i>
                        </button>
                    </div>
                </div>
            </div>
        </div>

        <div id="tab-files" class="hidden-tab h-full flex flex-col min-w-0">
            
            <div class="mb-4 hidden md:flex justify-between items-end">
                <div>
                    <h2 class="text-2xl font-bold text-white">File Explorer</h2>
                    <p class="text-slate-400 text-sm mt-1">Manage, upload, and edit your server configurations.</p>
                </div>
            </div>

            <div class="flex flex-col flex-grow premium-card overflow-hidden min-w-0">
                <div class="bg-black/40 px-5 md:px-6 py-4 md:py-5 border-b border-white/5 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 shrink-0">
                    <div class="flex items-center gap-2 text-sm font-mono text-slate-300 overflow-x-auto whitespace-nowrap w-full sm:w-auto bg-surfaceHover/50 px-4 py-2 rounded-lg border border-white/5 shadow-inner" id="breadcrumbs">
                        </div>
                    <div class="flex gap-3 shrink-0">
                        <input type="file" id="file-upload" class="hidden" onchange="uploadFile(event)">
                        <button onclick="document.getElementById('file-upload').click()" class="bg-gradient-btn px-5 py-2.5 rounded-xl text-xs md:text-sm font-bold text-white flex items-center gap-2">
                            <i class="ph-bold ph-upload-simple text-lg"></i> Upload
                        </button>
                        <button onclick="loadFiles(currentPath)" class="bg-white/5 border border-white/10 px-4 py-2.5 rounded-xl text-slate-300 hover:text-white hover:bg-white/10 transition-all shadow-lg">
                            <i class="ph-bold ph-arrows-clockwise text-lg"></i>
                        </button>
                    </div>
                </div>
                
                <div class="hidden sm:grid grid-cols-12 gap-4 px-8 py-3 bg-white/[0.02] border-b border-white/5 text-[11px] font-bold text-slate-400 uppercase tracking-wider shrink-0">
                    <div class="col-span-7">Filename</div>
                    <div class="col-span-3 text-right">Size</div>
                    <div class="col-span-2 text-right">Actions</div>
                </div>

                <div class="flex-grow overflow-y-auto bg-transparent p-3 md:p-4" id="file-list">
                    </div>
            </div>
        </div>
    </main>

    <nav class="md:hidden mobile-nav-glass fixed bottom-0 left-0 right-0 py-3 px-8 flex justify-between items-center z-50">
        <button onclick="switchTab('console')" id="mob-console" class="mob-nav-item active flex flex-col items-center gap-1.5 w-20">
            <i class="ph-fill ph-terminal-window text-2xl"></i>
            <span class="text-[10px] font-semibold tracking-wide uppercase">Console</span>
        </button>
        <div class="w-12 h-12 bg-gradient-btn rounded-full flex items-center justify-center shadow-neon -mt-6 border-[4px] border-[#080B11]">
            <i class="ph ph-cube text-white text-xl"></i>
        </div>
        <button onclick="switchTab('files')" id="mob-files" class="mob-nav-item flex flex-col items-center gap-1.5 w-20">
            <i class="ph-fill ph-folder-notch text-2xl"></i>
            <span class="text-[10px] font-semibold tracking-wide uppercase">Files</span>
        </button>
    </nav>

    <div id="editor-modal" class="fixed inset-0 bg-black/60 backdrop-blur-md hidden items-center justify-center p-4 md:p-8 z-[100] opacity-0 transition-opacity duration-300">
        <div class="premium-card w-full max-w-5xl h-[90vh] flex flex-col transform scale-95 transition-transform duration-300 ring-1 ring-white/10 shadow-[0_0_50px_rgba(0,0,0,0.8)]" id="editor-card">
            <div class="bg-black/60 px-6 py-5 flex justify-between items-center border-b border-white/10 shrink-0 backdrop-blur-xl">
                <div class="flex items-center gap-3 text-sm font-mono text-white bg-white/5 px-4 py-2 rounded-lg">
                    <i class="ph-fill ph-file-code text-primary text-xl"></i>
                    <span id="editor-title">file.txt</span>
                </div>
                <div class="flex gap-3">
                    <button onclick="closeEditor()" class="px-5 py-2.5 bg-white/5 hover:bg-white/10 border border-white/10 rounded-xl text-xs md:text-sm font-bold text-slate-300 transition-colors">Close</button>
                    <button onclick="saveFile()" class="bg-gradient-btn px-6 py-2.5 rounded-xl text-xs md:text-sm font-bold text-white shadow-neon flex items-center gap-2">
                        <i class="ph-bold ph-floppy-disk text-lg"></i> Save Changes
                    </button>
                </div>
            </div>
            <textarea id="editor-content" class="flex-grow bg-[#06080D]/80 text-slate-200 p-6 font-mono text-sm md:text-base resize-none focus:outline-none w-full leading-relaxed" spellcheck="false"></textarea>
        </div>
    </div>

    <div id="toast-container" class="fixed top-6 right-6 md:top-8 md:right-8 z-[200] flex flex-col gap-4 pointer-events-none"></div>

    <script>
        // --- Tab Navigation ---
        function switchTab(tab) {
            document.getElementById('tab-console').classList.add('hidden-tab');
            document.getElementById('tab-files').classList.add('hidden-tab');
            
            // Reset Desktop
            document.getElementById('nav-console').className = "nav-item flex items-center gap-4 px-4 py-3.5 rounded-r-xl font-medium border-l-3 border-transparent";
            document.getElementById('nav-files').className = "nav-item flex items-center gap-4 px-4 py-3.5 rounded-r-xl font-medium border-l-3 border-transparent";
            
            // Reset Mobile
            document.getElementById('mob-console').classList.remove('active');
            document.getElementById('mob-files').classList.remove('active');
            
            // Activate
            document.getElementById('tab-' + tab).classList.remove('hidden-tab');
            document.getElementById('tab-' + tab).classList.add('fade-in');
            
            document.getElementById('nav-' + tab).className = "nav-item active flex items-center gap-4 px-4 py-3.5 rounded-r-xl font-medium";
            document.getElementById('mob-' + tab).classList.add('active');

            if(tab === 'console' && fitAddon) setTimeout(() => fitAddon.fit(), 100);
            if(tab === 'files' && !window.filesLoaded) { loadFiles(''); window.filesLoaded = true; }
        }

        // --- Terminal Engine ---
        const term = new Terminal({ 
            theme: { background: 'transparent', foreground: '#E2E8F0', cursor: '#8B5CF6', selectionBackground: 'rgba(139, 92, 246, 0.3)' }, 
            fontFamily: "'JetBrains Mono', monospace", fontSize: window.innerWidth < 768 ? 12 : 14, cursorBlink: true, convertEol: true 
        });
        const fitAddon = new FitAddon.FitAddon();
        term.loadAddon(fitAddon);
        term.open(document.getElementById('terminal'));
        
        const ro = new ResizeObserver(() => {
            if(!document.getElementById('tab-console').classList.contains('hidden-tab')) {
                requestAnimationFrame(() => fitAddon.fit());
            }
        });
        ro.observe(document.querySelector('.term-container'));
        setTimeout(() => fitAddon.fit(), 200);

        const ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws');
        ws.onopen = () => term.write('\\x1b[38;5;135m\\x1b[1m[System]\\x1b[0m Secure engine connection established.\\r\\n');
        ws.onmessage = e => term.write(e.data + '\\n');
        
        const cmdInput = document.getElementById('cmd-input');
        cmdInput.addEventListener('keypress', e => { if (e.key === 'Enter') sendCommand(); });
        function sendCommand() {
            if(cmdInput.value.trim() && ws.readyState === WebSocket.OPEN) { 
                term.write(`\\x1b[38;5;51m> ${cmdInput.value}\\x1b[0m\\r\\n`);
                ws.send(cmdInput.value); cmdInput.value = ''; 
            }
        }

        // --- File Manager ---
        let currentPath = '';
        let editPath = '';

        function showToast(msg, type='info') {
            const container = document.getElementById('toast-container');
            const el = document.createElement('div');
            let icon = '<i class="ph-fill ph-info text-accent text-2xl drop-shadow-[0_0_8px_#0EA5E9]"></i>';
            if(type==='success') icon = '<i class="ph-fill ph-check-circle text-green-400 text-2xl drop-shadow-[0_0_8px_#22C55E]"></i>';
            if(type==='error') icon = '<i class="ph-fill ph-warning-circle text-red-400 text-2xl drop-shadow-[0_0_8px_#EF4444]"></i>';

            el.className = `flex items-center gap-4 bg-surface/90 backdrop-blur-xl border border-white/10 text-white px-6 py-4 rounded-2xl shadow-[0_10px_40px_rgba(0,0,0,0.5)] translate-x-12 opacity-0 transition-all duration-300`;
            el.innerHTML = `${icon} <span class="font-medium text-sm tracking-wide">${msg}</span>`;
            container.appendChild(el);
            
            requestAnimationFrame(() => el.classList.remove('translate-x-12', 'opacity-0'));
            setTimeout(() => { el.classList.add('translate-x-12', 'opacity-0'); setTimeout(() => el.remove(), 300); }, 3500);
        }

        async function loadFiles(path) {
            currentPath = path;
            const parts = path.split('/').filter(p => p);
            let bc = `<button onclick="loadFiles('')" class="hover:text-primary transition"><i class="ph-fill ph-house text-lg"></i></button>`;
            let bp = '';
            parts.forEach((p, i) => {
                bp += (bp?'/':'') + p;
                bc += `<i class="ph-bold ph-caret-right text-xs mx-3 text-slate-600"></i>`;
                if(i === parts.length-1) bc += `<span class="text-primary font-bold bg-primary/10 px-2 py-0.5 rounded">${p}</span>`;
                else bc += `<button onclick="loadFiles('${bp}')" class="hover:text-primary transition">${p}</button>`;
            });
            document.getElementById('breadcrumbs').innerHTML = bc;

            const list = document.getElementById('file-list');
            list.innerHTML = `<div class="flex flex-col items-center justify-center py-20 gap-4"><i class="ph-bold ph-circle-notch animate-spin text-4xl text-primary"></i><span class="text-slate-500 font-mono text-sm">Syncing system files...</span></div>`;

            try {
                const res = await fetch(`/api/fs/list?path=${encodeURIComponent(path)}`);
                const files = await res.json();
                list.innerHTML = '';
                
                if (path !== '') {
                    const parent = path.split('/').slice(0, -1).join('/');
                    list.innerHTML += `
                        <div class="flex items-center px-5 py-4 cursor-pointer hover:bg-white/5 rounded-2xl transition-all mb-2 border border-transparent" onclick="loadFiles('${parent}')">
                            <div class="p-2 bg-white/5 rounded-lg mr-4"><i class="ph-bold ph-arrow-u-up-left text-slate-400 text-lg"></i></div>
                            <span class="text-sm font-mono text-slate-300 font-semibold tracking-wide">.. / Return</span>
                        </div>`;
                }

                files.forEach(f => {
                    const icon = f.is_dir ? '<div class="p-3 bg-primary/10 border border-primary/20 rounded-xl text-primary shadow-[0_0_15px_rgba(139,92,246,0.15)] group-hover:bg-primary group-hover:text-white transition-all duration-300"><i class="ph-fill ph-folder text-xl"></i></div>' : '<div class="p-3 bg-surface border border-white/5 rounded-xl text-slate-400 group-hover:bg-white/10 group-hover:text-white transition-all duration-300"><i class="ph-fill ph-file-text text-xl"></i></div>';
                    const sz = f.is_dir ? '<span class="px-2 py-1 bg-white/5 rounded text-[10px] text-slate-500">DIR</span>' : (f.size > 1048576 ? `<span class="px-2 py-1 bg-white/5 rounded text-[10px] text-slate-300">${(f.size/1048576).toFixed(1)} MB</span>` : `<span class="px-2 py-1 bg-white/5 rounded text-[10px] text-slate-400">${(f.size/1024).toFixed(1)} KB</span>`);
                    const fp = path ? `${path}/${f.name}` : f.name;
                    
                    list.innerHTML += `
                        <div class="flex flex-col sm:grid sm:grid-cols-12 items-start sm:items-center px-4 py-3 gap-3 group hover:bg-white/[0.03] rounded-2xl transition-all duration-300 mb-2 border border-transparent hover:border-white/5 hover:shadow-lg">
                            <div class="col-span-7 flex items-center gap-5 w-full ${f.is_dir?'cursor-pointer':''}" ${f.is_dir?`onclick="loadFiles('${fp}')"`:''}>
                                ${icon}
                                <span class="text-sm font-mono text-slate-200 truncate group-hover:text-white transition font-medium tracking-wide">${f.name}</span>
                            </div>
                            <div class="col-span-3 text-right font-mono hidden sm:block">${sz}</div>
                            <div class="col-span-2 flex justify-end gap-2 w-full sm:w-auto sm:opacity-0 group-hover:opacity-100 transition-opacity duration-300">
                                ${!f.is_dir ? `<button onclick="editFile('${fp}')" class="p-2.5 bg-surface border border-white/5 hover:border-primary hover:text-primary hover:shadow-[0_0_10px_rgba(139,92,246,0.2)] rounded-xl transition-all"><i class="ph-bold ph-pencil-simple text-base"></i></button>` : ''}
                                ${!f.is_dir ? `<a href="/api/fs/download?path=${encodeURIComponent(fp)}" class="p-2.5 bg-surface border border-white/5 hover:border-accent hover:text-accent hover:shadow-[0_0_10px_rgba(14,165,233,0.2)] rounded-xl transition-all"><i class="ph-bold ph-download-simple text-base"></i></a>` : ''}
                                <button onclick="deleteFile('${fp}')" class="p-2.5 bg-surface border border-white/5 hover:border-secondary hover:text-secondary hover:shadow-[0_0_10px_rgba(217,70,239,0.2)] rounded-xl transition-all"><i class="ph-bold ph-trash text-base"></i></button>
                            </div>
                        </div>`;
                });
            } catch (err) { list.innerHTML = `<div class="text-center py-10 text-red-400 text-sm font-mono bg-red-500/10 border border-red-500/20 rounded-2xl mx-4">System fault: Unable to access directory mapping.</div>`; }
        }

        async function editFile(path) {
            try {
                const res = await fetch(`/api/fs/read?path=${encodeURIComponent(path)}`);
                if(res.ok) {
                    editPath = path;
                    document.getElementById('editor-content').value = await res.text();
                    document.getElementById('editor-title').innerText = path.split('/').pop();
                    const m = document.getElementById('editor-modal'); const c = document.getElementById('editor-card');
                    m.classList.remove('hidden'); m.classList.add('flex');
                    requestAnimationFrame(() => { m.classList.remove('opacity-0'); c.classList.remove('scale-95'); });
                } else showToast('Binary file cannot be parsed', 'error');
            } catch { showToast('Error accessing data block', 'error'); }
        }

        function closeEditor() {
            const m = document.getElementById('editor-modal'); const c = document.getElementById('editor-card');
            m.classList.add('opacity-0'); c.classList.add('scale-95');
            setTimeout(() => { m.classList.add('hidden'); m.classList.remove('flex'); }, 300);
        }

        async function saveFile() {
            const fd = new FormData(); fd.append('path', editPath); fd.append('content', document.getElementById('editor-content').value);
            try {
                const res = await fetch('/api/fs/write', { method: 'POST', body: fd });
                if(res.ok) { showToast('Block verified and saved', 'success'); closeEditor(); } else throw new Error();
            } catch { showToast('Write operation failed', 'error'); }
        }

        async function deleteFile(path) {
            if(confirm(`WARNING: Erase ${path.split('/').pop()} from the filesystem? This cannot be undone.`)) {
                const fd = new FormData(); fd.append('path', path);
                try {
                    const res = await fetch('/api/fs/delete', { method: 'POST', body: fd });
                    if(res.ok) { showToast('Data block purged', 'success'); loadFiles(currentPath); } else throw new Error();
                } catch { showToast('Purge operation failed', 'error'); }
            }
        }

        async function uploadFile(e) {
            if(!e.target.files.length) return;
            showToast('Injecting payload...', 'info');
            const fd = new FormData(); fd.append('path', currentPath); fd.append('file', e.target.files[0]);
            try {
                const res = await fetch('/api/fs/upload', { method: 'POST', body: fd });
                if(res.ok) { showToast('Payload injected successfully', 'success'); loadFiles(currentPath); } else throw new Error();
            } catch { showToast('Injection failed', 'error'); }
            e.target.value = '';
        }
    </script>
</body>
</html>
"""

# -----------------
# UTILITIES & SERVER
# -----------------
def get_safe_path(subpath: str):
    subpath = (subpath or "").strip("/")
    target = os.path.abspath(os.path.join(BASE_DIR, subpath))
    if not target.startswith(BASE_DIR):
        raise HTTPException(status_code=403, detail="Access denied")
    return target

async def broadcast(message: str):
    output_history.append(message)
    dead = set()
    for client in connected_clients:
        try:
            await client.send_text(message)
        except:
            dead.add(client)
    connected_clients.difference_update(dead)

async def read_stream(stream, prefix=""):
    while True:
        try:
            line = await stream.readline()
            if not line: break
            await broadcast(prefix + line.decode('utf-8', errors='replace').rstrip('\r\n'))
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
        *java_args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, cwd=BASE_DIR
    )
    asyncio.create_task(read_stream(mc_process.stdout))

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(start_minecraft())

# -----------------
# API ROUTING
# -----------------
@app.get("/")
def get_panel(): return HTMLResponse(content=HTML_CONTENT)

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)
    for line in output_history: await websocket.send_text(line)
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
        with open(target, 'r', encoding='utf-8') as f: return Response(content=f.read(), media_type="text/plain")
    except: raise HTTPException(400, "File is binary")

@app.get("/api/fs/download")
def fs_download(path: str):
    target = get_safe_path(path)
    if not os.path.isfile(target): raise HTTPException(400, "Not a file")
    return FileResponse(target, filename=os.path.basename(target))

@app.post("/api/fs/write")
def fs_write(path: str = Form(...), content: str = Form(...)):
    with open(get_safe_path(path), 'w', encoding='utf-8') as f: f.write(content)
    return {"status": "ok"}

@app.post("/api/fs/upload")
async def fs_upload(path: str = Form(""), file: UploadFile = File(...)):
    with open(os.path.join(get_safe_path(path), file.filename), "wb") as buffer: shutil.copyfileobj(file.file, buffer)
    return {"status": "ok"}

@app.post("/api/fs/delete")
def fs_delete(path: str = Form(...)):
    t = get_safe_path(path)
    if os.path.isdir(t): shutil.rmtree(t)
    else: os.remove(t)
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860, log_level="warning")