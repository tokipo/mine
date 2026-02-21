import os
import asyncio
import collections
import shutil
from fastapi import FastAPI, WebSocket, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, Response, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

mc_process = None
output_history = collections.deque(maxlen=300)
connected_clients = set()
BASE_DIR = os.path.abspath("/app")

HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Server Engine</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/lucide@latest"></script>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;700&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #000000; --panel: #0a0a0a; --panel-hover: #111111;
            --border: #1a1a1a; --text: #a1a1aa; --text-light: #e4e4e7;
            --accent: #22c55e; --accent-hover: #16a34a; --accent-glow: rgba(34,197,94,0.15);
        }
        *, *::before, *::after { box-sizing: border-box; }
        html, body { height: 100%; overflow: hidden; margin: 0; }
        body { background: var(--bg); color: var(--text); font-family: 'Inter', sans-serif; -webkit-font-smoothing: antialiased; }
        .font-mono { font-family: 'JetBrains Mono', monospace; }

        ::-webkit-scrollbar { width: 4px; height: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #27272a; border-radius: 4px; }
        ::-webkit-scrollbar-thumb:hover { background: var(--accent); }

        /* Desktop sidebar nav indicator */
        .nav-btn { color: #52525b; transition: all 0.2s; position: relative; }
        .nav-btn:hover, .nav-btn.active { color: var(--accent); }
        .nav-btn.active::before { content:''; position:absolute; left:-12px; top:10%; height:80%; width:2px; background:var(--accent); border-radius:4px; box-shadow:0 0 8px var(--accent); }

        /* Mobile bottom nav */
        .bnav-btn { flex:1; display:flex; flex-direction:column; align-items:center; gap:3px; padding:8px 4px 6px; font-size:9px; color:#52525b; transition:color 0.2s; background:none; border:none; }
        .bnav-btn.active { color:var(--accent); }
        .bnav-dot { width:14px; height:2px; background:var(--accent); border-radius:2px; opacity:0; transition:opacity 0.2s; box-shadow:0 0 6px var(--accent); }
        .bnav-btn.active .bnav-dot { opacity:1; }

        /* Terminal */
        .term-mask { mask-image:linear-gradient(to bottom,transparent 0%,black 8%,black 100%); -webkit-mask-image:linear-gradient(to bottom,transparent 0%,black 8%,black 100%); }
        @keyframes fadeUpLine { from{opacity:0;transform:translateY(5px)} to{opacity:1;transform:translateY(0)} }
        .log-line { animation:fadeUpLine 0.2s cubic-bezier(0.16,1,0.3,1) forwards; word-break:break-all; padding:0.5px 0; }

        .file-row { border-bottom:1px solid var(--border); transition:background 0.15s; }
        .file-row:hover { background:var(--panel-hover); }
        .file-row:last-child { border-bottom:none; }

        input:focus, textarea:focus { outline:none; border-color:var(--accent); box-shadow:0 0 0 1px var(--accent-glow); }

        .modal-enter { animation:modalIn 0.3s cubic-bezier(0.16,1,0.3,1) forwards; }
        @keyframes modalIn { from{opacity:0;transform:scale(0.95) translateY(10px)} to{opacity:1;transform:scale(1) translateY(0)} }

        .loader { animation:spin 1s linear infinite; }
        @keyframes spin { 100%{transform:rotate(360deg)} }
        .hidden-tab { display:none !important; }
    </style>
</head>
<body style="display:flex;flex-direction:column;height:100dvh;">

    <!-- Main row: sidebar + content -->
    <div style="display:flex;flex:1;overflow:hidden;">

        <!-- Desktop sidebar (hidden on mobile) -->
        <aside class="hidden sm:flex" style="width:45px;background:#050505;border-right:1px solid #1a1a1a;flex-direction:column;align-items:center;padding:24px 0;gap:32px;z-index:40;flex-shrink:0;">
            <div style="color:#22c55e;filter:drop-shadow(0 0 8px rgba(34,197,94,0.4))"><i data-lucide="server" style="width:20px;height:20px;"></i></div>
            <nav style="display:flex;flex-direction:column;gap:24px;align-items:center;">
                <button onclick="switchTab('console')" id="nav-console" class="nav-btn active" title="Console"><i data-lucide="terminal-square" style="width:20px;height:20px;"></i></button>
                <button onclick="switchTab('files')" id="nav-files" class="nav-btn" title="Files"><i data-lucide="folder-tree" style="width:20px;height:20px;"></i></button>
                <button onclick="switchTab('config')" id="nav-config" class="nav-btn" title="Config"><i data-lucide="settings-2" style="width:20px;height:20px;"></i></button>
                <button onclick="switchTab('plugins')" id="nav-plugins" class="nav-btn" title="Plugins"><i data-lucide="puzzle" style="width:20px;height:20px;"></i></button>
            </nav>
        </aside>

        <!-- Content area -->
        <main style="flex:1;position:relative;background:#000;overflow:hidden;">

            <!-- CONSOLE TAB -->
            <div id="tab-console" style="position:absolute;inset:0;display:flex;flex-direction:column;padding:8px;" class="sm:p-5">
                <div style="flex:1;background:#0a0a0a;border:1px solid #1a1a1a;border-radius:12px;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 25px 50px -12px rgba(0,0,0,0.9)">
                    <!-- Status bar -->
                    <div style="height:36px;border-bottom:1px solid #1a1a1a;background:#050505;display:flex;align-items:center;padding:0 12px;justify-content:space-between;flex-shrink:0;">
                        <div style="display:flex;align-items:center;gap:8px;">
                            <div style="width:8px;height:8px;border-radius:50%;background:#22c55e;box-shadow:0 0 8px rgba(34,197,94,0.8);"></div>
                            <span style="font-size:10px;font-family:'JetBrains Mono',monospace;color:#71717a;">engine-live-stream</span>
                        </div>
                    </div>
                    <!-- Output — SMALLER TEXT -->
                    <div id="terminal-output" class="term-mask" style="flex:1;padding:8px 12px;overflow-y:auto;font-family:'JetBrains Mono',monospace;font-size:10px;line-height:1.6;color:#d4d4d8;" class="sm:text-[11px]"></div>
                    <!-- Input -->
                    <div style="height:46px;border-top:1px solid #1a1a1a;background:#050505;display:flex;align-items:center;padding:0 12px;gap:8px;flex-shrink:0;">
                        <i data-lucide="chevron-right" style="width:14px;height:14px;color:#22c55e;flex-shrink:0;"></i>
                        <input type="text" id="cmd-input" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false"
                            style="flex:1;background:transparent;border:none;color:#4ade80;font-family:'JetBrains Mono',monospace;font-size:11px;min-width:0;"
                            placeholder="Execute command...">
                    </div>
                </div>
            </div>

            <!-- FILES TAB -->
            <div id="tab-files" class="hidden-tab" style="position:absolute;inset:0;display:flex;flex-direction:column;padding:8px;" class="sm:p-5">
                <div style="flex:1;background:#0a0a0a;border:1px solid #1a1a1a;border-radius:12px;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 25px 50px -12px rgba(0,0,0,0.9)">
                    <!-- Header -->
                    <div style="background:#050505;border-bottom:1px solid #1a1a1a;padding:10px 12px;display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:8px;flex-shrink:0;">
                        <div id="breadcrumbs" style="display:flex;align-items:center;gap:4px;font-size:11px;font-family:'JetBrains Mono',monospace;color:#71717a;overflow-x:auto;max-width:60%;"></div>
                        <div style="display:flex;align-items:center;gap:4px;">
                            <input type="file" id="file-upload" class="hidden" onchange="uploadFile(event)">
                            <button onclick="showCreateModal('file')" title="New File" style="padding:6px;border-radius:6px;color:#71717a;background:none;border:none;cursor:pointer;transition:all 0.15s;" onmouseover="this.style.color='#22c55e'" onmouseout="this.style.color='#71717a'"><i data-lucide="file-plus" style="width:16px;height:16px;"></i></button>
                            <button onclick="showCreateModal('folder')" title="New Folder" style="padding:6px;border-radius:6px;color:#71717a;background:none;border:none;cursor:pointer;transition:all 0.15s;" onmouseover="this.style.color='#22c55e'" onmouseout="this.style.color='#71717a'"><i data-lucide="folder-plus" style="width:16px;height:16px;"></i></button>
                            <button onclick="document.getElementById('file-upload').click()" title="Upload" style="padding:6px;border-radius:6px;color:#71717a;background:none;border:none;cursor:pointer;transition:all 0.15s;" onmouseover="this.style.color='#22c55e'" onmouseout="this.style.color='#71717a'"><i data-lucide="upload" style="width:16px;height:16px;"></i></button>
                            <div style="width:1px;height:16px;background:#222;margin:0 2px;"></div>
                            <button onclick="loadFiles(currentPath)" style="padding:6px;border-radius:6px;color:#71717a;background:none;border:none;cursor:pointer;transition:all 0.15s;" onmouseover="this.style.color='#fff'" onmouseout="this.style.color='#71717a'"><i data-lucide="rotate-cw" style="width:16px;height:16px;"></i></button>
                        </div>
                    </div>
                    <!-- Column headers (desktop) -->
                    <div class="hidden sm:grid" style="grid-template-columns:1fr auto auto;gap:16px;padding:8px 16px;border-bottom:1px solid #1a1a1a;background:#080808;font-size:10px;font-weight:600;color:#3f3f46;text-transform:uppercase;letter-spacing:0.08em;flex-shrink:0;">
                        <div>Filename</div><div>Size</div><div></div>
                    </div>
                    <!-- List -->
                    <div id="file-list" style="flex:1;overflow-y:auto;"></div>
                </div>
            </div>

            <!-- CONFIG TAB -->
            <div id="tab-config" class="hidden-tab" style="position:absolute;inset:0;display:flex;flex-direction:column;padding:8px;" class="sm:p-5">
                <div style="flex:1;background:#0a0a0a;border:1px solid #1a1a1a;border-radius:12px;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 25px 50px -12px rgba(0,0,0,0.9)">
                    <div style="height:44px;border-bottom:1px solid #1a1a1a;background:#050505;display:flex;align-items:center;padding:0 12px;justify-content:space-between;flex-shrink:0;">
                        <div style="display:flex;align-items:center;gap:8px;font-size:12px;font-family:'JetBrains Mono',monospace;color:#d4d4d8;">
                            <i data-lucide="sliders" style="width:14px;height:14px;color:#22c55e;"></i> server.properties
                        </div>
                        <button onclick="saveConfig()" style="background:#16a34a;color:#000;padding:4px 12px;border-radius:6px;font-size:11px;font-weight:700;border:none;cursor:pointer;display:flex;align-items:center;gap:6px;transition:background 0.15s;" onmouseover="this.style.background='#22c55e'" onmouseout="this.style.background='#16a34a'">
                            <i data-lucide="save" style="width:12px;height:12px;"></i> Apply
                        </button>
                    </div>
                    <textarea id="config-editor" style="flex:1;background:transparent;padding:12px;color:#d4d4d8;font-family:'JetBrains Mono',monospace;font-size:11px;resize:none;border:none;outline:none;line-height:1.6;" spellcheck="false"></textarea>
                </div>
            </div>

            <!-- PLUGINS TAB -->
            <div id="tab-plugins" class="hidden-tab" style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;">
                <div style="text-align:center;opacity:0.5;display:flex;flex-direction:column;align-items:center;gap:16px;">
                    <div style="width:64px;height:64px;border-radius:16px;border:1px solid rgba(34,197,94,0.3);display:flex;align-items:center;justify-content:center;background:rgba(34,197,94,0.05);box-shadow:0 0 30px rgba(34,197,94,0.1);">
                        <i data-lucide="blocks" style="width:32px;height:32px;color:#22c55e;"></i>
                    </div>
                    <div>
                        <h2 style="font-size:20px;font-weight:700;color:#fff;margin:0 0 4px;">Plugin Manager</h2>
                        <p style="font-size:11px;color:#52525b;font-family:'JetBrains Mono',monospace;margin:0;">system.status = "COMING_SOON"</p>
                    </div>
                </div>
            </div>

        </main>
    </div>

    <!-- Mobile bottom nav (hidden on desktop) -->
    <nav class="flex sm:hidden" style="background:#050505;border-top:1px solid #1a1a1a;flex-shrink:0;padding-bottom:env(safe-area-inset-bottom,0);">
        <button onclick="switchTab('console')" id="mnav-console" class="bnav-btn active">
            <div class="bnav-dot"></div>
            <i data-lucide="terminal-square" style="width:20px;height:20px;"></i>
            <span>Console</span>
        </button>
        <button onclick="switchTab('files')" id="mnav-files" class="bnav-btn">
            <div class="bnav-dot"></div>
            <i data-lucide="folder-tree" style="width:20px;height:20px;"></i>
            <span>Files</span>
        </button>
        <button onclick="switchTab('config')" id="mnav-config" class="bnav-btn">
            <div class="bnav-dot"></div>
            <i data-lucide="settings-2" style="width:20px;height:20px;"></i>
            <span>Config</span>
        </button>
        <button onclick="switchTab('plugins')" id="mnav-plugins" class="bnav-btn">
            <div class="bnav-dot"></div>
            <i data-lucide="puzzle" style="width:20px;height:20px;"></i>
            <span>Plugins</span>
        </button>
    </nav>

    <!-- Context Menu -->
    <div id="context-menu" class="hidden" style="position:fixed;z-index:50;background:#0a0a0a;border:1px solid #222;border-radius:8px;box-shadow:0 20px 40px rgba(0,0,0,0.8);padding:4px 0;width:144px;overflow:hidden;"></div>

    <!-- Modal Overlay -->
    <div id="modal-overlay" class="hidden" style="position:fixed;inset:0;z-index:100;background:rgba(0,0,0,0.65);backdrop-filter:blur(4px);display:flex;align-items:flex-end;justify-content:center;opacity:0;transition:opacity 0.2s;" class="sm:items-center sm:p-4">

        <!-- Input Modal -->
        <div id="input-modal" class="hidden modal-enter" style="background:#0a0a0a;border:1px solid #222;border-radius:16px 16px 0 0;width:100%;max-width:400px;overflow:hidden;display:flex;flex-direction:column;">
            <div style="width:40px;height:4px;background:#333;border-radius:4px;margin:12px auto 4px;"></div>
            <div style="padding:16px 20px;border-bottom:1px solid #1a1a1a;">
                <h3 id="input-modal-title" style="color:#fff;font-size:14px;font-weight:500;margin:0 0 4px;">Action</h3>
                <p id="input-modal-desc" style="color:#71717a;font-size:11px;margin:0;"></p>
            </div>
            <div style="padding:16px 20px;">
                <input type="text" id="input-modal-field" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false"
                    style="width:100%;background:#050505;border:1px solid #222;color:#fff;font-size:13px;border-radius:8px;padding:10px 12px;font-family:'JetBrains Mono',monospace;transition:border-color 0.15s;">
            </div>
            <div style="padding:10px 20px;background:#050505;border-top:1px solid #1a1a1a;display:flex;justify-content:flex-end;gap:8px;">
                <button onclick="closeModal()" style="padding:6px 16px;font-size:11px;color:#71717a;background:none;border:none;cursor:pointer;transition:color 0.15s;" onmouseover="this.style.color='#fff'" onmouseout="this.style.color='#71717a'">Cancel</button>
                <button id="input-modal-submit" style="padding:6px 16px;background:#16a34a;color:#000;font-size:11px;font-weight:700;border-radius:6px;border:none;cursor:pointer;transition:background 0.15s;" onmouseover="this.style.background='#22c55e'" onmouseout="this.style.background='#16a34a'">Confirm</button>
            </div>
        </div>

        <!-- Confirm Modal -->
        <div id="confirm-modal" class="hidden modal-enter" style="background:#0a0a0a;border:1px solid #222;border-radius:16px 16px 0 0;width:100%;max-width:400px;overflow:hidden;display:flex;flex-direction:column;">
            <div style="width:40px;height:4px;background:#333;border-radius:4px;margin:12px auto 4px;"></div>
            <div style="padding:16px 20px;border-bottom:1px solid #1a1a1a;display:flex;gap:12px;">
                <i data-lucide="alert-triangle" style="width:20px;height:20px;color:#ef4444;flex-shrink:0;margin-top:2px;"></i>
                <div>
                    <h3 id="confirm-modal-title" style="color:#fff;font-size:14px;font-weight:500;margin:0 0 4px;">Delete</h3>
                    <p id="confirm-modal-msg" style="color:#a1a1aa;font-size:11px;margin:0;line-height:1.5;"></p>
                </div>
            </div>
            <div style="padding:10px 20px;background:#050505;display:flex;justify-content:flex-end;gap:8px;">
                <button onclick="closeModal()" style="padding:6px 16px;font-size:11px;color:#71717a;background:none;border:none;cursor:pointer;" onmouseover="this.style.color='#fff'" onmouseout="this.style.color='#71717a'">Cancel</button>
                <button id="confirm-modal-submit" style="padding:6px 16px;background:#dc2626;color:#fff;font-size:11px;font-weight:700;border-radius:6px;border:none;cursor:pointer;transition:background 0.15s;" onmouseover="this.style.background='#ef4444'" onmouseout="this.style.background='#dc2626'">Delete</button>
            </div>
        </div>

        <!-- Editor Modal -->
        <div id="editor-modal" class="hidden modal-enter" style="background:#0a0a0a;border:1px solid #222;border-radius:16px 16px 0 0;width:100%;max-width:800px;height:85vh;overflow:hidden;display:flex;flex-direction:column;">
            <div style="width:40px;height:4px;background:#333;border-radius:4px;margin:12px auto 4px;flex-shrink:0;"></div>
            <div style="padding:10px 16px;border-bottom:1px solid #1a1a1a;background:#050505;display:flex;justify-content:space-between;align-items:center;flex-shrink:0;">
                <span id="editor-modal-title" style="font-size:11px;font-family:'JetBrains Mono',monospace;color:#4ade80;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:60%;">editing...</span>
                <div style="display:flex;gap:8px;flex-shrink:0;">
                    <button onclick="closeModal()" style="padding:5px 12px;font-size:11px;color:#71717a;background:none;border:none;cursor:pointer;" onmouseover="this.style.color='#fff'" onmouseout="this.style.color='#71717a'">Discard</button>
                    <button id="editor-modal-submit" style="padding:5px 12px;background:#16a34a;color:#000;font-size:11px;font-weight:700;border-radius:6px;border:none;cursor:pointer;display:flex;align-items:center;gap:4px;" onmouseover="this.style.background='#22c55e'" onmouseout="this.style.background='#16a34a'">
                        <i data-lucide="save" style="width:12px;height:12px;"></i> Save
                    </button>
                </div>
            </div>
            <textarea id="editor-modal-content" style="flex:1;background:transparent;padding:12px;color:#d4d4d8;font-family:'JetBrains Mono',monospace;font-size:11px;resize:none;border:none;outline:none;line-height:1.6;" spellcheck="false"></textarea>
        </div>
    </div>

    <!-- Toasts -->
    <div id="toast-container" style="position:fixed;bottom:80px;right:16px;z-index:200;display:flex;flex-direction:column;gap:8px;pointer-events:none;" class="sm:bottom-5"></div>

    <script>
        lucide.createIcons();

        // Toast
        function showToast(msg, type = 'info') {
            const c = document.getElementById('toast-container');
            const t = document.createElement('div');
            const col = type==='error'?'#ef4444':type==='success'?'#22c55e':'#60a5fa';
            t.style.cssText = `display:flex;align-items:center;gap:8px;background:#0a0a0a;border:1px solid ${col}33;padding:10px 14px;border-radius:10px;box-shadow:0 10px 30px rgba(0,0,0,0.6);transform:translateY(12px);opacity:0;transition:all 0.3s;pointer-events:auto;max-width:280px;`;
            t.innerHTML = `<div style="width:6px;height:6px;border-radius:50%;background:${col};flex-shrink:0;"></div><span style="font-size:11px;font-family:'JetBrains Mono',monospace;color:#e4e4e7;">${msg}</span>`;
            c.appendChild(t);
            requestAnimationFrame(()=>{t.style.transform='translateY(0)';t.style.opacity='1';});
            setTimeout(()=>{t.style.transform='translateY(12px)';t.style.opacity='0';setTimeout(()=>t.remove(),300);},3000);
        }

        // Navigation
        function switchTab(tab) {
            document.querySelectorAll('[id^="tab-"]').forEach(el=>el.classList.add('hidden-tab'));
            document.querySelectorAll('.nav-btn').forEach(el=>el.classList.remove('active'));
            document.querySelectorAll('.bnav-btn').forEach(el=>el.classList.remove('active'));
            document.getElementById('tab-'+tab).classList.remove('hidden-tab');
            const d=document.getElementById('nav-'+tab); if(d) d.classList.add('active');
            const m=document.getElementById('mnav-'+tab); if(m) m.classList.add('active');
            if(tab==='files'&&!currentPathLoaded){loadFiles('');currentPathLoaded=true;}
            if(tab==='config') loadConfig();
            if(tab==='console') scrollToBottom();
        }

        // Modals
        const overlay = document.getElementById('modal-overlay');
        function openModalElement(id) {
            ['input-modal','confirm-modal','editor-modal'].forEach(m=>{
                const el=document.getElementById(m);
                el.classList.add('hidden');
                el.style.display='none';
            });
            overlay.classList.remove('hidden');
            overlay.style.display='flex';
            const el=document.getElementById(id);
            el.classList.remove('hidden');
            el.style.display='flex';
            requestAnimationFrame(()=>overlay.style.opacity='1');
        }
        function closeModal() {
            overlay.style.opacity='0';
            setTimeout(()=>{overlay.classList.add('hidden');overlay.style.display='';},200);
        }
        overlay.addEventListener('click', e=>{if(e.target===overlay)closeModal();});

        function showPrompt(title,desc,def,onConfirm) {
            document.getElementById('input-modal-title').innerText=title;
            document.getElementById('input-modal-desc').innerText=desc;
            const inp=document.getElementById('input-modal-field');
            inp.value=def;
            openModalElement('input-modal');
            setTimeout(()=>inp.focus(),150);
            const btn=document.getElementById('input-modal-submit');
            btn.onclick=()=>{onConfirm(inp.value);closeModal();};
            inp.onkeydown=e=>{if(e.key==='Enter')btn.click();};
        }
        function showConfirm(title,msg,onConfirm) {
            document.getElementById('confirm-modal-title').innerText=title;
            document.getElementById('confirm-modal-msg').innerText=msg;
            openModalElement('confirm-modal');
            document.getElementById('confirm-modal-submit').onclick=()=>{onConfirm();closeModal();};
        }

        // Terminal
        const termOut=document.getElementById('terminal-output');
        const cmdInput=document.getElementById('cmd-input');
        function parseANSI(str) {
            str=str.replace(/</g,'&lt;').replace(/>/g,'&gt;');
            let res='',styles=[];
            const chunks=str.split(/\\x1b\\[/);
            res+=chunks[0];
            for(let i=1;i<chunks.length;i++){
                const m=chunks[i].match(/^([0-9;]*)m(.*)/s);
                if(m){
                    const codes=m[1].split(';');
                    for(let c of codes){
                        if(c===''||c==='0')styles=[];
                        else if(c==='1')styles.push('font-weight:bold');
                        else if(c==='31'||c==='91')styles.push('color:#ef4444');
                        else if(c==='32'||c==='92')styles.push('color:#22c55e');
                        else if(c==='33'||c==='93')styles.push('color:#eab308');
                        else if(c==='34'||c==='94')styles.push('color:#3b82f6');
                        else if(c==='35'||c==='95')styles.push('color:#d946ef');
                        else if(c==='36'||c==='96')styles.push('color:#06b6d4');
                        else if(c==='37'||c==='97')styles.push('color:#fafafa');
                        else if(c==='90')styles.push('color:#71717a');
                    }
                    const s=styles.length?`style="${styles.join(';')}"`:'' ;
                    res+=styles.length?`<span ${s}>${m[2]}</span>`:m[2];
                } else { res+='\\x1b['+chunks[i]; }
            }
            return res||'&nbsp;';
        }
        function scrollToBottom(){termOut.scrollTop=termOut.scrollHeight;}
        function appendLog(text){
            const atBottom=termOut.scrollHeight-termOut.clientHeight<=termOut.scrollTop+10;
            const d=document.createElement('div');
            d.className='log-line';
            d.innerHTML=parseANSI(text);
            termOut.appendChild(d);
            if(termOut.childElementCount>400)termOut.removeChild(termOut.firstChild);
            if(atBottom)scrollToBottom();
        }
        const wsUrl=(location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws';
        let ws;
        function connectWS(){
            ws=new WebSocket(wsUrl);
            ws.onopen=()=>appendLog('\\x1b[32m\\x1b[1m[Panel]\\x1b[0m Stream connected.');
            ws.onmessage=e=>appendLog(e.data);
            ws.onclose=()=>{appendLog('\\x1b[31m\\x1b[1m[Panel]\\x1b[0m Connection lost. Reconnecting...');setTimeout(connectWS,3000);};
        }
        connectWS();
        cmdInput.addEventListener('keypress',e=>{
            if(e.key==='Enter'){
                const v=cmdInput.value.trim();
                if(v&&ws&&ws.readyState===WebSocket.OPEN){
                    appendLog(`\\x1b[90m> ${v}\\x1b[0m`);
                    ws.send(v);cmdInput.value='';
                }
            }
        });

        // Files
        let currentPath='',currentPathLoaded=false,menuTarget=null;
        document.addEventListener('click',()=>document.getElementById('context-menu').classList.add('hidden'));
        function openMenu(e,name,isDir){
            e.stopPropagation();
            menuTarget={name,isDir,path:(currentPath?currentPath+'/'+name:name)};
            const menu=document.getElementById('context-menu');
            const btnStyle=`style="width:100%;text-align:left;padding:10px 16px;font-size:11px;background:none;border:none;cursor:pointer;display:flex;align-items:center;gap:8px;color:#d4d4d8;transition:all 0.15s;"`;
            let html='';
            if(!isDir) html+=`<button ${btnStyle} onclick="editFile('${menuTarget.path}')" onmouseover="this.style.color='#22c55e';this.style.background='#1a1a1a'" onmouseout="this.style.color='#d4d4d8';this.style.background='none'"><i data-lucide="edit-3" style="width:14px;height:14px;"></i> Edit</button>`;
            html+=`<button ${btnStyle} onclick="initRename()" onmouseover="this.style.color='#22c55e';this.style.background='#1a1a1a'" onmouseout="this.style.color='#d4d4d8';this.style.background='none'"><i data-lucide="type" style="width:14px;height:14px;"></i> Rename</button>
                   <button ${btnStyle} onclick="initMove()" onmouseover="this.style.color='#22c55e';this.style.background='#1a1a1a'" onmouseout="this.style.color='#d4d4d8';this.style.background='none'"><i data-lucide="move" style="width:14px;height:14px;"></i> Move</button>`;
            if(!isDir) html+=`<button ${btnStyle} onclick="window.open('/api/fs/download?path='+encodeURIComponent('${menuTarget.path}'))" onmouseover="this.style.color='#22c55e';this.style.background='#1a1a1a'" onmouseout="this.style.color='#d4d4d8';this.style.background='none'"><i data-lucide="download" style="width:14px;height:14px;"></i> Download</button>`;
            html+=`<div style="height:1px;background:#1a1a1a;margin:4px 0;"></div>
                   <button style="width:100%;text-align:left;padding:10px 16px;font-size:11px;background:none;border:none;cursor:pointer;display:flex;align-items:center;gap:8px;color:#ef4444;transition:all 0.15s;" onclick="initDelete()" onmouseover="this.style.background='rgba(239,68,68,0.1)'" onmouseout="this.style.background='none'"><i data-lucide="trash-2" style="width:14px;height:14px;"></i> Delete</button>`;
            menu.innerHTML=html;
            lucide.createIcons();
            const mw=148,mh=180;
            menu.style.left=Math.min(e.pageX,window.innerWidth-mw-8)+'px';
            menu.style.top=Math.min(e.pageY,window.innerHeight-mh-8)+'px';
            menu.classList.remove('hidden');
        }
        async function loadFiles(path){
            currentPath=path;renderBreadcrumbs(path);
            const list=document.getElementById('file-list');
            list.innerHTML=`<div style="display:flex;justify-content:center;padding:40px;"><i data-lucide="loader-2" style="width:24px;height:24px;color:#22c55e;" class="loader"></i></div>`;
            lucide.createIcons();
            try {
                const res=await fetch(`/api/fs/list?path=${encodeURIComponent(path)}`);
                const files=await res.json();
                list.innerHTML='';
                if(path!==''){
                    const parent=path.split('/').slice(0,-1).join('/');
                    const row=document.createElement('div');
                    row.className='file-row';
                    row.style.cssText='display:flex;align-items:center;padding:10px 12px;cursor:pointer;gap:10px;';
                    row.onclick=()=>loadFiles(parent);
                    row.onmouseover=()=>row.style.background='#111';
                    row.onmouseout=()=>row.style.background='';
                    row.innerHTML=`<i data-lucide="corner-left-up" style="width:16px;height:16px;color:#3f3f46;flex-shrink:0;"></i><span style="font-size:11px;font-family:'JetBrains Mono',monospace;color:#52525b;">..</span>`;
                    list.appendChild(row);
                }
                if(files.length===0&&path==='') list.innerHTML+=`<div style="text-align:center;padding:40px;color:#3f3f46;font-size:11px;font-family:'JetBrains Mono',monospace;">Directory empty</div>`;
                files.forEach(f=>{
                    const icon=f.is_dir?'<i data-lucide="folder" style="width:16px;height:16px;color:#22c55e;flex-shrink:0;"></i>':'<i data-lucide="file" style="width:16px;height:16px;color:#52525b;flex-shrink:0;"></i>';
                    const sz=f.is_dir?'--':(f.size>1048576?(f.size/1048576).toFixed(1)+' MB':(f.size/1024).toFixed(1)+' KB');
                    const row=document.createElement('div');
                    row.className='file-row';
                    row.style.cssText='display:flex;align-items:center;padding:8px 12px;cursor:pointer;gap:8px;';
                    if(f.is_dir){row.onclick=()=>loadFiles(currentPath?currentPath+'/'+f.name:f.name);}
                    row.onmouseover=()=>row.style.background='#111';
                    row.onmouseout=()=>row.style.background='';
                    row.innerHTML=`
                        ${icon}
                        <span style="font-size:12px;font-family:'JetBrains Mono',monospace;color:#d4d4d8;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${f.name}</span>
                        <span style="font-size:10px;color:#52525b;font-family:'JetBrains Mono',monospace;flex-shrink:0;display:none;" class="sm:inline-block">${sz}</span>
                        <button onclick="openMenu(event,'${f.name}',${f.is_dir})" style="padding:4px;border-radius:4px;background:none;border:none;cursor:pointer;color:#52525b;flex-shrink:0;transition:all 0.15s;" onmouseover="this.style.color='#fff';this.style.background='#222'" onmouseout="this.style.color='#52525b';this.style.background='none'">
                            <i data-lucide="more-horizontal" style="width:16px;height:16px;"></i>
                        </button>`;
                    list.appendChild(row);
                });
                lucide.createIcons();
            } catch {showToast('Error loading files','error');}
        }
        function renderBreadcrumbs(path){
            const parts=path.split('/').filter(p=>p);
            let html=`<button onclick="loadFiles('')" style="background:none;border:none;cursor:pointer;color:#52525b;padding:2px;transition:color 0.15s;" onmouseover="this.style.color='#22c55e'" onmouseout="this.style.color='#52525b'"><i data-lucide="home" style="width:14px;height:14px;display:block;"></i></button>`;
            let build='';
            parts.forEach((p,i)=>{
                build+=(build?'/':'')+p;
                html+=`<span style="opacity:0.3;margin:0 2px;">/</span>`;
                if(i===parts.length-1) html+=`<span style="color:#22c55e;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${p}</span>`;
                else html+=`<button onclick="loadFiles('${build}')" style="background:none;border:none;cursor:pointer;color:#52525b;transition:color 0.15s;display:none;" class="sm:inline" onmouseover="this.style.color='#22c55e'" onmouseout="this.style.color='#52525b'">${p}</button>`;
            });
            document.getElementById('breadcrumbs').innerHTML=html;
            lucide.createIcons();
        }
        function showCreateModal(type){
            showPrompt(`New ${type==='folder'?'Folder':'File'}`,'Enter name:','',async(val)=>{
                if(!val)return;
                const path=currentPath?`${currentPath}/${val}`:val;
                const ep=type==='folder'?'/api/fs/create_dir':'/api/fs/create_file';
                const fd=new FormData();fd.append('path',path);
                try{const r=await fetch(ep,{method:'POST',body:fd});if(r.ok){showToast('Created','success');loadFiles(currentPath);}else showToast('Failed','error');}
                catch{showToast('Network error','error');}
            });
        }
        function initRename(){
            const t=menuTarget;
            showPrompt('Rename',`New name for ${t.name}:`,t.name,async(val)=>{
                if(!val||val===t.name)return;
                const fd=new FormData();fd.append('old_path',t.path);fd.append('new_name',val);
                try{const r=await fetch('/api/fs/rename',{method:'POST',body:fd});if(r.ok){showToast('Renamed','success');loadFiles(currentPath);}else showToast('Failed','error');}
                catch{showToast('Network error','error');}
            });
        }
        function initMove(){
            const t=menuTarget;
            showPrompt('Move',`Destination for "${t.name}" (blank = root):`, '',async(val)=>{
                const dest=(val.trim()?`${val.trim()}/${t.name}`:t.name);
                if(dest===t.path)return;
                const fd=new FormData();fd.append('source',t.path);fd.append('dest',dest);
                try{const r=await fetch('/api/fs/move',{method:'POST',body:fd});if(r.ok){showToast('Moved','success');loadFiles(currentPath);}else showToast('Failed','error');}
                catch{showToast('Network error','error');}
            });
        }
        function initDelete(){
            const t=menuTarget;
            showConfirm('Delete Permanently',`Delete "${t.name}"? Cannot be undone.`,async()=>{
                const fd=new FormData();fd.append('path',t.path);
                try{const r=await fetch('/api/fs/delete',{method:'POST',body:fd});if(r.ok){showToast('Deleted','success');loadFiles(currentPath);}else showToast('Failed','error');}
                catch{showToast('Network error','error');}
            });
        }
        async function uploadFile(e){
            const file=e.target.files[0];if(!file)return;
            showToast(`Uploading ${file.name}...`);
            const fd=new FormData();fd.append('path',currentPath);fd.append('file',file);
            try{const r=await fetch('/api/fs/upload',{method:'POST',body:fd});if(r.ok){showToast('Upload complete','success');loadFiles(currentPath);}else showToast('Failed','error');}
            catch{showToast('Network error','error');}
            e.target.value='';
        }
        let currentEditPath='';
        async function editFile(path){
            try{
                const r=await fetch(`/api/fs/read?path=${encodeURIComponent(path)}`);
                if(!r.ok)throw new Error();
                const text=await r.text();
                currentEditPath=path;
                document.getElementById('editor-modal-title').innerText=path;
                document.getElementById('editor-modal-content').value=text;
                openModalElement('editor-modal');
                document.getElementById('editor-modal-submit').onclick=async()=>{
                    const fd=new FormData();fd.append('path',currentEditPath);fd.append('content',document.getElementById('editor-modal-content').value);
                    const res=await fetch('/api/fs/write',{method:'POST',body:fd});
                    if(res.ok){showToast('Saved','success');closeModal();}else showToast('Save failed','error');
                };
            }catch{showToast('Cannot open file (binary?)','error');}
        }
        async function loadConfig(){
            try{
                const r=await fetch('/api/fs/read?path=server.properties');
                document.getElementById('config-editor').value=r.ok?await r.text():'# server.properties not found yet.';
            }catch{showToast('Failed to load config','error');}
        }
        async function saveConfig(){
            const fd=new FormData();fd.append('path','server.properties');fd.append('content',document.getElementById('config-editor').value);
            try{const r=await fetch('/api/fs/write',{method:'POST',body:fd});if(r.ok)showToast('Config applied','success');else showToast('Failed','error');}
            catch{showToast('Network error','error');}
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
    os.makedirs(BASE_DIR, exist_ok=True)
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
    os.makedirs(target_dir, exist_ok=True)
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

@app.post("/api/fs/create_dir")
def fs_create_dir(path: str = Form(...)):
    target = get_safe_path(path)
    try:
        os.makedirs(target, exist_ok=True)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(400, str(e))

@app.post("/api/fs/create_file")
def fs_create_file(path: str = Form(...)):
    target = get_safe_path(path)
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        open(target, 'a').close()
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(400, str(e))

@app.post("/api/fs/rename")
def fs_rename(old_path: str = Form(...), new_name: str = Form(...)):
    src = get_safe_path(old_path)
    base_dir = os.path.dirname(src)
    dst = os.path.join(base_dir, new_name)
    try:
        os.rename(src, dst)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(400, str(e))

@app.post("/api/fs/move")
def fs_move(source: str = Form(...), dest: str = Form(...)):
    src = get_safe_path(source)
    dst = get_safe_path(dest)
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(400, str(e))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860, log_level="warning")