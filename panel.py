import os
import asyncio
import collections
import shutil
import psutil
from fastapi import FastAPI, WebSocket, Request, Response, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

mc_process = None
output_history = collections.deque(maxlen=300)
connected_clients = set()
BASE_DIR = os.path.abspath("/app")

# -----------------
# HTML FRONTEND (Ultra-Modern Web3 SaaS UI)
# -----------------
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>DeProxy / MineSpace Engine</title>
    
    <!-- Fonts & Icons -->
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <script src="https://unpkg.com/@phosphor-icons/web"></script>
    
    <!-- Terminal -->
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm/css/xterm.css" />
    <script src="https://cdn.jsdelivr.net/npm/xterm/lib/xterm.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit/lib/xterm-addon-fit.js"></script>
    
    <!-- Tailwind CSS (Custom Web3 Config) -->
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    colors: {
                        dark: '#05050A',
                        panel: '#0F1017',
                        surface: '#181A24',
                        primary: '#9D4EDD',
                        secondary: '#FF79C6',
                        accent: '#8BE9FD',
                        border: '#2A2C3E'
                    },
                    fontFamily: {
                        sans: ['Outfit', 'sans-serif'],
                        mono: ['JetBrains Mono', 'monospace']
                    },
                    boxShadow: {
                        'neon': '0 0 20px rgba(157, 78, 221, 0.15)',
                        'neon-strong': '0 0 30px rgba(255, 121, 198, 0.3)',
                    }
                }
            }
        }
    </script>
    
    <style>
        body { background-color: theme('colors.dark'); color: #e2e8f0; overflow: hidden; -webkit-font-smoothing: antialiased; }
        
        /* Glassmorphism & Cards */
        .glass-card {
            background: rgba(15, 16, 23, 0.7);
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            border: 1px solid theme('colors.border');
            border-radius: 20px;
            box-shadow: 0 10px 30px -10px rgba(0,0,0,0.5);
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }
        
        /* Gradients */
        .text-gradient { background: linear-gradient(135deg, theme('colors.secondary'), theme('colors.primary')); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        .bg-gradient-btn { background: linear-gradient(135deg, theme('colors.primary'), theme('colors.secondary')); transition: opacity 0.3s ease; }
        .bg-gradient-btn:hover { opacity: 0.9; box-shadow: theme('boxShadow.neon-strong'); }

        /* Terminal Fixes - Crucial for Wrapping */
        .term-container { min-width: 0; width: 100%; height: 100%; border-radius: 16px; overflow: hidden; position: relative; }
        .term-wrapper { padding: 16px; height: 100%; width: 100%; }
        .xterm .xterm-viewport { overflow-y: auto !important; width: 100% !important; }
        .xterm-screen { width: 100% !important; }
        
        /* Custom Scrollbars */
        ::-webkit-scrollbar { width: 4px; height: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: theme('colors.border'); border-radius: 10px; }
        ::-webkit-scrollbar-thumb:hover { background: theme('colors.primary'); }

        /* SVG Circular Progress */
        .progress-ring__circle { transition: stroke-dashoffset 0.5s ease-in-out; transform: rotate(-90deg); transform-origin: 50% 50%; }
        
        /* Layout Transitions */
        .fade-in { animation: fadeIn 0.4s cubic-bezier(0.16, 1, 0.3, 1) forwards; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        .hidden-tab { display: none !important; }

        /* Pulse Animation */
        @keyframes pulse-glow { 0%, 100% { opacity: 1; box-shadow: 0 0 10px #8BE9FD; } 50% { opacity: 0.5; box-shadow: 0 0 2px #8BE9FD; } }
        .status-dot { width: 8px; height: 8px; background-color: theme('colors.accent'); border-radius: 50%; animation: pulse-glow 2s infinite; }
    </style>
</head>
<body class="flex flex-col md:flex-row h-[100dvh] w-full selection:bg-primary/30 selection:text-white">

    <!-- Mobile Top Header -->
    <header class="md:hidden glass-card mx-4 mt-4 mb-2 p-4 flex justify-between items-center z-20 shrink-0 border-white/5 rounded-2xl relative overflow-hidden">
        <div class="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-primary to-secondary opacity-50"></div>
        <div class="flex items-center gap-2">
            <i class="ph-fill ph-hexagon text-3xl text-secondary"></i>
            <h1 class="font-bold text-lg tracking-wide text-white">Mine<span class="text-gradient">Space</span></h1>
        </div>
        <div class="flex items-center gap-2 px-3 py-1 bg-accent/10 border border-accent/20 rounded-full">
            <div class="status-dot"></div>
            <span class="text-xs font-semibold text-accent uppercase tracking-wider">Online</span>
        </div>
    </header>

    <!-- Desktop Sidebar -->
    <aside class="hidden md:flex flex-col w-64 glass-card m-4 mr-0 p-6 z-20 shrink-0 border-white/5 rounded-3xl relative overflow-hidden shadow-neon">
        <div class="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-primary to-secondary"></div>
        
        <div class="flex items-center gap-3 mb-12">
            <i class="ph-fill ph-hexagon text-4xl text-secondary"></i>
            <div>
                <h1 class="font-bold text-xl tracking-wide text-white leading-tight">Mine<span class="text-gradient">Space</span></h1>
                <p class="text-[10px] text-gray-500 font-mono uppercase tracking-widest">Engine Server</p>
            </div>
        </div>

        <nav class="flex-grow flex flex-col gap-2">
            <button onclick="switchTab('dashboard')" id="btn-desktop-dashboard" class="flex items-center gap-3 w-full px-4 py-3 rounded-xl bg-gradient-to-r from-primary/20 to-secondary/10 text-white border border-white/10 font-medium transition-all shadow-[inset_0_1px_0_rgba(255,255,255,0.1)]">
                <i class="ph ph-squares-four text-xl text-secondary"></i> Dashboard
            </button>
            <button onclick="switchTab('files')" id="btn-desktop-files" class="flex items-center gap-3 w-full px-4 py-3 rounded-xl text-gray-400 hover:text-white hover:bg-surface border border-transparent transition-all">
                <i class="ph ph-folder text-xl"></i> File Manager
            </button>
        </nav>

        <div class="mt-auto bg-surface/50 border border-border p-4 rounded-2xl flex items-center justify-between">
            <div class="flex flex-col">
                <span class="text-xs text-gray-400">Status</span>
                <span class="text-sm font-semibold text-accent">Active Container</span>
            </div>
            <div class="status-dot"></div>
        </div>
    </aside>

    <!-- Main Content Area -->
    <main class="flex-grow flex flex-col p-4 overflow-hidden min-w-0">
        
        <!-- DASHBOARD TAB -->
        <div id="tab-dashboard" class="h-full flex flex-col gap-4 fade-in min-w-0">
            
            <!-- Top Stats Row -->
            <div class="grid grid-cols-2 md:grid-cols-4 gap-4 shrink-0">
                <!-- Data Usage (RAM) Card -->
                <div class="glass-card p-4 md:p-5 flex items-center gap-4 col-span-1 md:col-span-2 relative overflow-hidden group">
                    <div class="absolute -right-10 -top-10 w-32 h-32 bg-primary/10 rounded-full blur-2xl group-hover:bg-primary/20 transition-all"></div>
                    <div class="relative w-16 h-16 shrink-0">
                        <svg class="w-full h-full" viewBox="0 0 100 100">
                            <circle class="text-surface stroke-current" stroke-width="8" cx="50" cy="50" r="40" fill="transparent"></circle>
                            <circle id="ram-ring" class="text-primary stroke-current progress-ring__circle" stroke-width="8" stroke-linecap="round" cx="50" cy="50" r="40" fill="transparent" stroke-dasharray="251.2" stroke-dashoffset="251.2"></circle>
                        </svg>
                        <div class="absolute inset-0 flex items-center justify-center"><i class="ph ph-memory text-primary text-xl"></i></div>
                    </div>
                    <div>
                        <p class="text-xs text-gray-400 uppercase tracking-wider font-semibold">Memory Usage</p>
                        <div class="flex items-baseline gap-1 mt-1">
                            <h2 class="text-2xl font-bold text-white font-mono" id="ram-text">0.0</h2>
                            <span class="text-sm text-gray-500 font-mono">/ 16 GB</span>
                        </div>
                    </div>
                </div>

                <!-- CPU Card -->
                <div class="glass-card p-4 md:p-5 flex items-center gap-4 col-span-1 md:col-span-2 relative overflow-hidden group">
                    <div class="absolute -right-10 -top-10 w-32 h-32 bg-secondary/10 rounded-full blur-2xl group-hover:bg-secondary/20 transition-all"></div>
                    <div class="relative w-16 h-16 shrink-0">
                        <svg class="w-full h-full" viewBox="0 0 100 100">
                            <circle class="text-surface stroke-current" stroke-width="8" cx="50" cy="50" r="40" fill="transparent"></circle>
                            <circle id="cpu-ring" class="text-secondary stroke-current progress-ring__circle" stroke-width="8" stroke-linecap="round" cx="50" cy="50" r="40" fill="transparent" stroke-dasharray="251.2" stroke-dashoffset="251.2"></circle>
                        </svg>
                        <div class="absolute inset-0 flex items-center justify-center"><i class="ph ph-cpu text-secondary text-xl"></i></div>
                    </div>
                    <div>
                        <p class="text-xs text-gray-400 uppercase tracking-wider font-semibold">Processor</p>
                        <div class="flex items-baseline gap-1 mt-1">
                            <h2 class="text-2xl font-bold text-white font-mono" id="cpu-text">0%</h2>
                            <span class="text-sm text-gray-500 font-mono">of 2 Cores</span>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Terminal Area -->
            <div class="glass-card flex-grow flex flex-col overflow-hidden shadow-neon relative border-white/10">
                <!-- Terminal Header -->
                <div class="bg-surface/80 px-4 py-3 flex justify-between items-center border-b border-border z-10">
                    <div class="flex items-center gap-2">
                        <i class="ph ph-terminal-window text-gray-400"></i>
                        <span class="text-sm font-semibold text-gray-200">Live Console</span>
                    </div>
                    <div class="flex gap-1.5">
                        <div class="w-3 h-3 rounded-full bg-red-500/80"></div>
                        <div class="w-3 h-3 rounded-full bg-yellow-500/80"></div>
                        <div class="w-3 h-3 rounded-full bg-green-500/80"></div>
                    </div>
                </div>
                
                <!-- Actual Terminal -->
                <div class="term-container bg-[#08080C] flex-grow">
                    <div id="terminal" class="term-wrapper"></div>
                </div>

                <!-- Input Box -->
                <div class="p-3 bg-surface/50 border-t border-border z-10 flex gap-2">
                    <div class="relative flex-grow">
                        <i class="ph ph-caret-right absolute left-3 top-1/2 -translate-y-1/2 text-primary text-lg"></i>
                        <input type="text" id="cmd-input" class="w-full bg-[#0B0C10] border border-border focus:border-primary text-gray-200 rounded-xl pl-9 pr-4 py-2.5 text-sm font-mono transition-all outline-none" placeholder="Enter server command...">
                    </div>
                    <button onclick="sendCommand()" class="bg-gradient-btn px-4 rounded-xl text-white shadow-lg flex items-center justify-center shrink-0">
                        <i class="ph ph-paper-plane-right text-lg"></i>
                    </button>
                </div>
            </div>
        </div>

        <!-- FILES TAB -->
        <div id="tab-files" class="hidden-tab h-full flex flex-col glass-card border-white/10 overflow-hidden shadow-neon">
            
            <!-- File Header / Actions -->
            <div class="bg-surface/80 p-4 border-b border-border flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                <div class="flex items-center gap-2 text-sm font-mono text-gray-400 overflow-x-auto whitespace-nowrap w-full sm:w-auto" id="breadcrumbs">
                    <!-- Injected via JS -->
                </div>
                
                <div class="flex items-center gap-2 shrink-0 self-end sm:self-auto">
                    <input type="file" id="file-upload" class="hidden" onchange="uploadFile(event)">
                    <button onclick="document.getElementById('file-upload').click()" class="bg-gradient-btn flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold text-white transition-all shadow-lg">
                        <i class="ph ph-upload-simple text-base"></i> Upload
                    </button>
                    <button onclick="loadFiles(currentPath)" class="bg-surface hover:bg-border border border-border px-3 py-2 rounded-xl text-gray-300 transition-colors">
                        <i class="ph ph-arrows-clockwise text-base"></i>
                    </button>
                </div>
            </div>
            
            <!-- List Headers -->
            <div class="hidden sm:grid grid-cols-12 gap-4 px-6 py-3 bg-[#0B0C10]/50 border-b border-border text-xs font-bold text-gray-500 uppercase tracking-wider">
                <div class="col-span-7">File Name</div>
                <div class="col-span-3 text-right">Size</div>
                <div class="col-span-2 text-right">Actions</div>
            </div>

            <!-- File List Items -->
            <div class="flex-grow overflow-y-auto bg-[#08080C] p-2" id="file-list">
                <!-- Injected via JS -->
            </div>
        </div>

    </main>

    <!-- Mobile Bottom Navigation -->
    <nav class="md:hidden glass-card mx-4 mb-4 mt-0 p-2 flex justify-around items-center z-20 shrink-0 border-white/5 rounded-2xl">
        <button onclick="switchTab('dashboard')" id="btn-mobile-dashboard" class="flex flex-col items-center gap-1 p-2 w-16 rounded-xl text-primary transition-all">
            <i class="ph-fill ph-squares-four text-2xl"></i>
            <span class="text-[10px] font-semibold">Panel</span>
        </button>
        <button onclick="switchTab('files')" id="btn-mobile-files" class="flex flex-col items-center gap-1 p-2 w-16 rounded-xl text-gray-500 transition-all">
            <i class="ph-fill ph-folder text-2xl"></i>
            <span class="text-[10px] font-semibold">Files</span>
        </button>
    </nav>

    <!-- Code Editor Modal -->
    <div id="editor-modal" class="fixed inset-0 bg-black/80 backdrop-blur-md hidden items-center justify-center p-4 z-50 opacity-0 transition-opacity duration-300">
        <div class="glass-card border-white/10 w-full max-w-4xl h-[85vh] flex flex-col shadow-[0_0_50px_rgba(0,0,0,0.8)] transform scale-95 transition-transform duration-300" id="editor-card">
            <div class="bg-surface/80 px-4 py-3 flex justify-between items-center border-b border-border">
                <div class="flex items-center gap-2 text-sm font-mono text-gray-300">
                    <i class="ph ph-file-code text-secondary text-lg"></i>
                    <span id="editor-title">filename.txt</span>
                </div>
                <div class="flex items-center gap-2">
                    <button onclick="closeEditor()" class="px-3 py-1.5 hover:bg-border rounded-lg text-xs font-medium text-gray-400 transition-colors">Cancel</button>
                    <button onclick="saveFile()" class="bg-gradient-btn px-4 py-1.5 text-white rounded-lg text-xs font-bold transition-all shadow-neon flex items-center gap-1.5">
                        <i class="ph ph-floppy-disk"></i> Save
                    </button>
                </div>
            </div>
            <textarea id="editor-content" class="flex-grow bg-[#05050A] text-gray-300 p-4 font-mono text-xs sm:text-sm resize-none focus:outline-none w-full leading-relaxed" spellcheck="false"></textarea>
        </div>
    </div>

    <!-- Modern Toast Notifications -->
    <div id="toast-container" class="fixed top-4 right-4 z-[100] flex flex-col gap-2 pointer-events-none"></div>

    <script>
        // --- Toast System ---
        function showToast(message, type = 'info') {
            const container = document.getElementById('toast-container');
            const toast = document.createElement('div');
            
            let icon = '<i class="ph-fill ph-info text-blue-400 text-lg"></i>';
            if(type === 'success') icon = '<i class="ph-fill ph-check-circle text-green-400 text-lg"></i>';
            if(type === 'error') icon = '<i class="ph-fill ph-warning-circle text-red-400 text-lg"></i>';

            toast.className = `flex items-center gap-3 bg-surface border border-border text-sm text-white px-4 py-3 rounded-xl shadow-2xl translate-x-10 opacity-0 transition-all duration-300`;
            toast.innerHTML = `${icon} <span class="font-medium">${message}</span>`;
            
            container.appendChild(toast);
            
            requestAnimationFrame(() => toast.classList.remove('translate-x-10', 'opacity-0'));
            setTimeout(() => {
                toast.classList.add('translate-x-10', 'opacity-0');
                setTimeout(() => toast.remove(), 300);
            }, 3000);
        }

        // --- Navigation Logic ---
        function switchTab(tab) {
            // Hide all
            document.getElementById('tab-dashboard').classList.add('hidden-tab');
            document.getElementById('tab-files').classList.add('hidden-tab');
            
            // Reset Desktop Nav
            document.getElementById('btn-desktop-dashboard').className = "flex items-center gap-3 w-full px-4 py-3 rounded-xl text-gray-400 hover:text-white hover:bg-surface border border-transparent transition-all";
            document.getElementById('btn-desktop-files').className = "flex items-center gap-3 w-full px-4 py-3 rounded-xl text-gray-400 hover:text-white hover:bg-surface border border-transparent transition-all";
            
            // Reset Mobile Nav
            document.getElementById('btn-mobile-dashboard').className = "flex flex-col items-center gap-1 p-2 w-16 rounded-xl text-gray-500 transition-all";
            document.getElementById('btn-mobile-files').className = "flex flex-col items-center gap-1 p-2 w-16 rounded-xl text-gray-500 transition-all";
            
            // Activate Tab
            document.getElementById('tab-' + tab).classList.remove('hidden-tab');
            document.getElementById('tab-' + tab).classList.add('fade-in');
            
            // Activate Buttons
            document.getElementById('btn-desktop-' + tab).className = "flex items-center gap-3 w-full px-4 py-3 rounded-xl bg-gradient-to-r from-primary/20 to-secondary/10 text-white border border-white/10 font-medium transition-all shadow-[inset_0_1px_0_rgba(255,255,255,0.1)]";
            document.getElementById('btn-mobile-' + tab).className = "flex flex-col items-center gap-1 p-2 w-16 rounded-xl text-primary transition-all";

            // Fit terminal if dashboard is opened
            if(tab === 'dashboard' && fitAddon) { setTimeout(() => fitAddon.fit(), 100); }
            if(tab === 'files' && !currentPathLoaded) { loadFiles(''); currentPathLoaded = true; }
        }

        // --- Terminal Logic (Wrapped heavily) ---
        const term = new Terminal({ 
            theme: { background: 'transparent', foreground: '#f8f8f2', cursor: '#9D4EDD', selectionBackground: 'rgba(157, 78, 221, 0.4)' }, 
            convertEol: true, cursorBlink: true, fontFamily: "'JetBrains Mono', monospace", fontSize: 13, fontWeight: 400,
            disableStdin: false
        });
        const fitAddon = new FitAddon.FitAddon();
        term.loadAddon(fitAddon);
        term.open(document.getElementById('terminal'));
        
        // Ensure resizing works properly
        const resizeObserver = new ResizeObserver(() => {
            if(!document.getElementById('tab-dashboard').classList.contains('hidden-tab')) {
                requestAnimationFrame(() => fitAddon.fit());
            }
        });
        resizeObserver.observe(document.querySelector('.term-container'));
        setTimeout(() => fitAddon.fit(), 200);

        const wsUrl = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws';
        let ws;
        
        function connectWS() {
            ws = new WebSocket(wsUrl);
            ws.onopen = () => term.write('\\x1b[35m\\x1b[1m[System]\\x1b[0m Connected to secure datastream.\\r\\n');
            ws.onmessage = e => term.write(e.data + '\\n');
            ws.onclose = () => { term.write('\\r\\n\\x1b[31m\\x1b[1m[System]\\x1b[0m Link severed. Reconnecting...\\r\\n'); setTimeout(connectWS, 3000); };
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

        // --- System Stats Polling ---
        function setProgress(id, percent) {
            const circle = document.getElementById(id);
            const radius = circle.r.baseVal.value;
            const circumference = radius * 2 * Math.PI;
            const offset = circumference - (percent / 100) * circumference;
            circle.style.strokeDasharray = `${circumference} ${circumference}`;
            circle.style.strokeDashoffset = offset;
        }

        async function fetchStats() {
            try {
                const res = await fetch('/api/stats');
                const data = await res.json();
                
                // Update RAM
                const ramPercent = Math.min(100, (data.ram_used_mb / 1024 / 16) * 100);
                document.getElementById('ram-text').innerText = (data.ram_used_mb / 1024).toFixed(1);
                setProgress('ram-ring', ramPercent);

                // Update CPU (data.cpu_percent is 0 to 100 relative to 2 cores)
                document.getElementById('cpu-text').innerText = data.cpu_percent.toFixed(0) + '%';
                setProgress('cpu-ring', data.cpu_percent);
                
            } catch (e) { console.error('Stats error:', e); }
        }
        setInterval(fetchStats, 2000);
        fetchStats();

        // --- File Manager Logic ---
        let currentPath = '';
        let currentPathLoaded = false;
        let editingFilePath = '';

        function renderBreadcrumbs(path) {
            const parts = path.split('/').filter(p => p);
            let html = `<button onclick="loadFiles('')" class="hover:text-white transition-colors"><i class="ph-fill ph-house text-lg"></i></button>`;
            let buildPath = '';
            
            if (parts.length > 0) {
                parts.forEach((part, index) => {
                    buildPath += (buildPath ? '/' : '') + part;
                    html += ` <i class="ph ph-caret-right text-xs mx-2 opacity-50"></i> `;
                    if(index === parts.length - 1) {
                        html += `<span class="text-secondary font-semibold">${part}</span>`;
                    } else {
                        html += `<button onclick="loadFiles('${buildPath}')" class="hover:text-white transition-colors">${part}</button>`;
                    }
                });
            }
            document.getElementById('breadcrumbs').innerHTML = html;
        }

        async function loadFiles(path) {
            currentPath = path;
            renderBreadcrumbs(path);
            const list = document.getElementById('file-list');
            list.innerHTML = `<div class="flex justify-center py-10"><i class="ph ph-spinner-gap animate-spin text-3xl text-primary"></i></div>`;

            try {
                const res = await fetch(`/api/fs/list?path=${encodeURIComponent(path)}`);
                if(!res.ok) throw new Error('Failed to load');
                const files = await res.json();
                list.innerHTML = '';
                
                if (path !== '') {
                    const parent = path.split('/').slice(0, -1).join('/');
                    list.innerHTML += `
                        <div class="flex items-center px-4 py-3 cursor-pointer hover:bg-surface/80 rounded-xl transition-all mb-1 border border-transparent hover:border-border" onclick="loadFiles('${parent}')">
                            <i class="ph ph-arrow-u-up-left text-gray-500 mr-3 text-lg"></i>
                            <span class="text-sm font-mono text-gray-400">Return to parent directory</span>
                        </div>`;
                }

                if(files.length === 0 && path === '') {
                    list.innerHTML += `<div class="text-center py-12 text-gray-600 text-sm">Space is empty</div>`;
                }

                files.forEach(f => {
                    const icon = f.is_dir ? '<div class="p-2 bg-blue-500/10 rounded-lg text-blue-400"><i class="ph-fill ph-folder text-xl"></i></div>' : '<div class="p-2 bg-surface border border-border rounded-lg text-gray-400"><i class="ph-fill ph-file text-xl"></i></div>';
                    const sizeStr = f.is_dir ? '--' : (f.size > 1024*1024 ? (f.size/(1024*1024)).toFixed(1) + ' MB' : (f.size / 1024).toFixed(1) + ' KB');
                    const fullPath = path ? `${path}/${f.name}` : f.name;
                    const actionClick = f.is_dir ? `onclick="loadFiles('${fullPath}')"` : '';
                    const pointer = f.is_dir ? 'cursor-pointer' : '';

                    list.innerHTML += `
                        <div class="flex flex-col sm:grid sm:grid-cols-12 items-start sm:items-center px-4 py-3 gap-3 group hover:bg-surface/50 rounded-xl transition-all mb-1 border border-transparent hover:border-border">
                            <div class="col-span-7 flex items-center gap-3 w-full ${pointer}" ${actionClick}>
                                ${icon}
                                <span class="text-sm font-mono text-gray-300 truncate group-hover:text-primary transition-colors">${f.name}</span>
                            </div>
                            <div class="col-span-3 text-right text-xs text-gray-500 font-mono hidden sm:block">${sizeStr}</div>
                            <div class="col-span-2 flex justify-end gap-2 w-full sm:w-auto mt-2 sm:mt-0 sm:opacity-0 group-hover:opacity-100 transition-opacity">
                                ${!f.is_dir ? `<button onclick="editFile('${fullPath}')" class="p-2 bg-surface border border-border text-gray-400 hover:text-accent hover:border-accent/50 rounded-lg transition-colors" title="Edit"><i class="ph ph-pencil-simple text-sm"></i></button>` : ''}
                                ${!f.is_dir ? `<a href="/api/fs/download?path=${encodeURIComponent(fullPath)}" class="p-2 bg-surface border border-border text-gray-400 hover:text-green-400 hover:border-green-400/50 rounded-lg transition-colors inline-block" title="Download"><i class="ph ph-download-simple text-sm"></i></a>` : ''}
                                <button onclick="deleteFile('${fullPath}')" class="p-2 bg-surface border border-border text-gray-400 hover:text-red-400 hover:border-red-400/50 rounded-lg transition-colors" title="Delete"><i class="ph ph-trash text-sm"></i></button>
                            </div>
                        </div>`;
                });
            } catch (err) {
                showToast("Failed to load directory", "error");
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
                    
                    requestAnimationFrame(() => {
                        modal.classList.remove('opacity-0');
                        card.classList.remove('scale-95');
                    });
                } else { showToast('Cannot open file (might be binary)', 'error'); }
            } catch { showToast('Failed to open file', 'error'); }
        }

        function closeEditor() {
            const modal = document.getElementById('editor-modal');
            const card = document.getElementById('editor-card');
            modal.classList.add('opacity-0');
            card.classList.add('scale-95');
            setTimeout(() => { modal.classList.add('hidden'); modal.classList.remove('flex'); }, 300);
        }

        async function saveFile() {
            const content = document.getElementById('editor-content').value;
            const formData = new FormData();
            formData.append('path', editingFilePath);
            formData.append('content', content);
            try {
                const res = await fetch('/api/fs/write', { method: 'POST', body: formData });
                if(res.ok) { showToast('File saved securely', 'success'); closeEditor(); } 
                else throw new Error();
            } catch { showToast('Failed to save file', 'error'); }
        }

        async function deleteFile(path) {
            if(confirm('Delete ' + path.split('/').pop() + ' permanently?')) {
                const formData = new FormData(); formData.append('path', path);
                try {
                    const res = await fetch('/api/fs/delete', { method: 'POST', body: formData });
                    if(res.ok) { showToast('Data purged', 'success'); loadFiles(currentPath); } 
                    else throw new Error();
                } catch { showToast('Failed to delete', 'error'); }
            }
        }

        async function uploadFile(e) {
            const fileInput = e.target;
            if(!fileInput.files.length) return;
            
            showToast('Encrypting & Uploading...', 'info');
            const formData = new FormData();
            formData.append('path', currentPath);
            formData.append('file', fileInput.files[0]);
            
            try {
                const res = await fetch('/api/fs/upload', { method: 'POST', body: formData });
                if(res.ok) { showToast('Upload complete', 'success'); loadFiles(currentPath); } 
                else throw new Error();
            } catch { showToast('Upload failed', 'error'); }
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

@app.get("/api/stats")
def get_stats():
    """ 
    Calculates CPU & RAM only for the Python Panel and its Minecraft Child Process.
    Limits visual CPU percentage to 2 Cores (HuggingFace free limit).
    """
    try:
        current_process = psutil.Process(os.getpid())
        mem_usage = current_process.memory_info().rss
        cpu_percent = current_process.cpu_percent()

        # Add all children (The Java Minecraft Process)
        for child in current_process.children(recursive=True):
            try:
                mem_usage += child.memory_info().rss
                cpu_percent += child.cpu_percent()
            except psutil.NoSuchProcess:
                pass
        
        # CPU returned by psutil can be 200% for 2 cores. 
        # We divide by 2 to get a standard 0-100% representation for 2 cores.
        normalized_cpu = min(100.0, cpu_percent / 2.0)
        
        return {
            "ram_used_mb": mem_usage / (1024 * 1024),
            "cpu_percent": normalized_cpu
        }
    except Exception:
        # Fallback if psutil fails entirely to not crash UI
        return {"ram_used_mb": 0, "cpu_percent": 0}

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
        raise HTTPException(400, "File is binary")

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