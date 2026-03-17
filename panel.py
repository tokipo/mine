import os, asyncio, collections, shutil, urllib.request, json, time
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(PLUGINS_DIR, exist_ok=True)
    asyncio.create_task(boot_mc())
    yield

# --- CONFIG ---
app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
BASE_DIR = os.environ.get("SERVER_DIR", os.path.abspath("/app"))
PLUGINS_DIR = os.path.join(BASE_DIR, "plugins")
mc_process = None
output_history = collections.deque(maxlen=500)
connected_clients = set()

# ─────────────────────────────────────────────
# HTML GUI  —  macOS / Apple-style UI
# Raw string (r"""…""") so backslashes in JS
# regex patterns pass through unchanged.
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
:root{
  --f:-apple-system,BlinkMacSystemFont,'SF Pro Display','SF Pro Text',system-ui,sans-serif;
  --mono:'JetBrains Mono','SF Mono','Cascadia Code',monospace;
  --r:12px;--r-sm:8px;--r-lg:16px;--dur:0.18s
}
[data-theme=dark]{
  --bg:#000;--s1:#1C1C1E;--s2:#2C2C2E;--s3:#3A3A3C;
  --bd:rgba(255,255,255,.08);
  --t1:#fff;--t2:rgba(255,255,255,.55);--t3:rgba(255,255,255,.22);
  --acc:#32D74B;--acc-bg:rgba(50,215,75,.12);
  --red:#FF453A;--yel:#FFD60A;--blu:#0A84FF;
  --glass:rgba(28,28,30,.8);
  --sh:0 8px 40px rgba(0,0,0,.7),0 2px 8px rgba(0,0,0,.4);
  --sh-sm:0 2px 12px rgba(0,0,0,.5)
}
[data-theme=light]{
  --bg:#EBEBEB;--s1:#fff;--s2:#F5F5F7;--s3:#E5E5EA;
  --bd:rgba(0,0,0,.09);
  --t1:#1C1C1E;--t2:rgba(0,0,0,.5);--t3:rgba(0,0,0,.22);
  --acc:#28CD41;--acc-bg:rgba(40,205,65,.1);
  --red:#FF3B30;--yel:#FF9F0A;--blu:#007AFF;
  --glass:rgba(255,255,255,.85);
  --sh:0 8px 40px rgba(0,0,0,.12),0 2px 8px rgba(0,0,0,.06);
  --sh-sm:0 2px 12px rgba(0,0,0,.1)
}
html,body{height:100%;height:100dvh}
body{font-family:var(--f);background:var(--bg);color:var(--t1);
  display:flex;flex-direction:column;overflow:hidden;
  -webkit-font-smoothing:antialiased;transition:background var(--dur),color var(--dur)}
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--s3);border-radius:99px}
::-webkit-scrollbar-thumb:hover{background:var(--t3)}

/* TOOLBAR */
.toolbar{height:52px;min-height:52px;background:var(--glass);
  backdrop-filter:blur(24px) saturate(180%);-webkit-backdrop-filter:blur(24px) saturate(180%);
  border-bottom:1px solid var(--bd);display:flex;align-items:center;
  padding:0 16px;gap:14px;position:relative;z-index:100;flex-shrink:0;user-select:none}
.tl-wrap{display:flex;gap:6px;align-items:center;flex-shrink:0}
.tl{width:12px;height:12px;border-radius:50%;transition:filter var(--dur);cursor:default}
.tl:hover{filter:brightness(1.25)}
.tl-r{background:var(--red)}.tl-y{background:var(--yel)}.tl-g{background:var(--acc)}
.tb-title{position:absolute;left:50%;transform:translateX(-50%);
  font-size:13px;font-weight:600;letter-spacing:-.3px;color:var(--t1);
  pointer-events:none;display:flex;align-items:center;gap:7px;white-space:nowrap}
.pip{width:7px;height:7px;border-radius:50%;background:var(--acc);
  box-shadow:0 0 6px var(--acc);animation:pip 2.5s ease-in-out infinite}
@keyframes pip{0%,100%{opacity:1}50%{opacity:.3}}
.tb-actions{margin-left:auto;display:flex;align-items:center;gap:6px}
.icon-btn{width:30px;height:30px;border-radius:var(--r-sm);border:1px solid var(--bd);
  background:var(--s1);color:var(--t2);display:flex;align-items:center;justify-content:center;
  cursor:pointer;transition:all var(--dur)}
.icon-btn:hover{color:var(--t1);background:var(--s2)}
.icon-btn svg{width:15px;height:15px;pointer-events:none}

/* LAYOUT */
.app-body{flex:1;display:flex;overflow:hidden;min-height:0}

/* SIDEBAR */
.sidebar{width:192px;flex-shrink:0;background:var(--glass);
  backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px);
  border-right:1px solid var(--bd);display:flex;flex-direction:column;
  padding:10px 8px 16px;gap:2px}
@media(max-width:640px){.sidebar{display:none}}
.sb-label{font-size:10px;font-weight:700;text-transform:uppercase;
  letter-spacing:.6px;color:var(--t3);padding:10px 10px 4px}
.nav-item{display:flex;align-items:center;gap:9px;padding:8px 10px;
  border-radius:var(--r-sm);font-size:13px;font-weight:500;color:var(--t2);
  cursor:pointer;transition:all var(--dur);border:none;background:none;width:100%;text-align:left}
.nav-item:hover{background:var(--s2);color:var(--t1)}
.nav-item.active{background:var(--acc-bg);color:var(--acc)}
.nav-item svg{width:16px;height:16px;flex-shrink:0}

/* MAIN */
.main{flex:1;display:flex;flex-direction:column;overflow:hidden;min-height:0}
.tab-pane{display:none;flex:1;flex-direction:column;overflow:hidden;padding:14px;min-height:0}
.tab-pane.active{display:flex;animation:fu var(--dur) ease-out}
@keyframes fu{from{opacity:0;transform:translateY(5px)}to{opacity:1;transform:translateY(0)}}

/* WINDOW */
.win{flex:1;display:flex;flex-direction:column;background:var(--s1);
  border:1px solid var(--bd);border-radius:var(--r-lg);overflow:hidden;
  box-shadow:var(--sh);min-height:0;transition:background var(--dur),border-color var(--dur);
  position:relative}
.win-bar{height:40px;min-height:40px;background:var(--s2);border-bottom:1px solid var(--bd);
  display:flex;align-items:center;padding:0 14px;gap:10px;flex-shrink:0}
.win-bar-title{flex:1;text-align:center;font-size:12px;font-weight:600;color:var(--t2)}
.live-dot{width:6px;height:6px;border-radius:50%;background:var(--acc);box-shadow:0 0 5px var(--acc)}

/* CONSOLE */
.log-out{flex:1;overflow-y:auto;padding:12px 14px;font-family:var(--mono);
  font-size:11.5px;line-height:1.65;color:var(--t2);min-height:0}
.log-line{word-break:break-all;padding:.5px 0}
.cmd-bar{display:flex;align-items:center;gap:8px;padding:8px 10px;
  background:var(--s2);border-top:1px solid var(--bd);flex-shrink:0}
.cmd-prompt{font-family:var(--mono);font-size:13px;color:var(--acc);flex-shrink:0}
.cmd-in{flex:1;background:var(--s1);border:1px solid var(--bd);border-radius:var(--r-sm);
  padding:6px 12px;font-family:var(--mono);font-size:12px;color:var(--t1);
  outline:none;transition:border-color var(--dur),box-shadow var(--dur)}
.cmd-in:focus{border-color:var(--acc);box-shadow:0 0 0 3px var(--acc-bg)}
.cmd-in::placeholder{color:var(--t3)}
.send-btn{width:32px;height:32px;flex-shrink:0;background:var(--acc);border:none;
  border-radius:var(--r-sm);color:#fff;display:flex;align-items:center;justify-content:center;
  cursor:pointer;transition:opacity var(--dur),transform var(--dur)}
.send-btn:hover{opacity:.85;transform:scale(.95)}
.send-btn svg{width:14px;height:14px}

/* FILES */
.fm-bar{height:44px;min-height:44px;background:var(--s2);border-bottom:1px solid var(--bd);
  display:flex;align-items:center;padding:0 12px;gap:8px;flex-shrink:0}
.breadcrumb{flex:1;display:flex;align-items:center;gap:3px;font-size:12px;
  overflow-x:auto;white-space:nowrap}
.breadcrumb button{background:none;border:none;color:var(--t2);cursor:pointer;
  padding:3px 5px;border-radius:5px;font-size:12px;font-family:var(--f)}
.breadcrumb button:hover{color:var(--acc);background:var(--acc-bg)}
.breadcrumb .sep{color:var(--t3);font-size:10px;margin:0 1px}
.file-list{flex:1;overflow-y:auto}
.file-row{display:flex;align-items:center;gap:10px;padding:9px 16px;
  border-bottom:1px solid var(--bd);cursor:pointer;transition:background var(--dur)}
.file-row:hover{background:var(--s2)}
.file-row:last-child{border-bottom:none}
.file-name{flex:1;font-size:13px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.file-del{opacity:0;background:none;border:none;color:var(--red);cursor:pointer;padding:4px;
  border-radius:6px;display:flex;align-items:center;transition:opacity var(--dur),background var(--dur)}
.file-row:hover .file-del{opacity:1}
.file-del:hover{background:rgba(255,59,48,.1)}
.drag-ov{position:absolute;inset:0;background:rgba(50,215,75,.06);
  border:2px dashed var(--acc);border-radius:var(--r-lg);
  display:none;align-items:center;justify-content:center;
  font-size:15px;font-weight:600;color:var(--acc);z-index:50}
.drag-ov.on{display:flex}

/* PLUGINS */
.pl-hd{padding:12px 14px;background:var(--s2);border-bottom:1px solid var(--bd);
  flex-shrink:0;display:flex;flex-direction:column;gap:10px}
.segment{display:inline-flex;background:var(--s3);border-radius:var(--r-sm);padding:2px}
.seg-btn{padding:5px 16px;border-radius:6px;border:none;background:none;
  color:var(--t2);font-size:12px;font-weight:500;cursor:pointer;
  transition:all var(--dur);font-family:var(--f)}
.seg-btn.active{background:var(--s1);color:var(--t1);box-shadow:var(--sh-sm)}
.pl-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.sf-sel,.sf-ver{background:var(--s1);border:1px solid var(--bd);border-radius:var(--r-sm);
  padding:6px 10px;font-size:12px;color:var(--t1);outline:none;
  transition:border-color var(--dur);font-family:var(--f)}
.sf-sel:focus,.sf-ver:focus{border-color:var(--blu)}
.sf-ver{width:70px;text-align:center}
.srch-wrap{position:relative;flex:1;min-width:160px}
.srch-wrap svg{position:absolute;left:10px;top:50%;transform:translateY(-50%);
  width:13px;height:13px;color:var(--t3);pointer-events:none}
.sf-srch{width:100%;background:var(--s1);border:1px solid var(--bd);border-radius:var(--r-sm);
  padding:7px 10px 7px 32px;font-size:12px;color:var(--t1);outline:none;
  transition:border-color var(--dur),box-shadow var(--dur);font-family:var(--f)}
.sf-srch:focus{border-color:var(--blu);box-shadow:0 0 0 3px rgba(10,132,255,.15)}
.sf-srch::placeholder{color:var(--t3)}
.srch-btn{padding:7px 14px;background:var(--blu);border:none;border-radius:var(--r-sm);
  color:#fff;font-size:12px;font-weight:600;cursor:pointer;transition:opacity var(--dur);
  flex-shrink:0;font-family:var(--f)}
.srch-btn:hover{opacity:.85}
.pl-grid{flex:1;overflow-y:auto;padding:14px;
  display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px;align-content:start}
@media(max-width:640px){.pl-grid{grid-template-columns:1fr}}
.pl-card{background:var(--s2);border:1px solid var(--bd);border-radius:var(--r);padding:14px;
  display:flex;flex-direction:column;gap:10px;transition:border-color var(--dur),box-shadow var(--dur)}
.pl-card:hover{border-color:var(--acc);box-shadow:0 0 0 1px var(--acc-bg)}
.pl-head{display:flex;gap:10px}
.pl-ico{width:36px;height:36px;border-radius:8px;flex-shrink:0;object-fit:cover;background:var(--s3)}
.pl-meta{flex:1;min-width:0}
.pl-name{font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pl-desc{font-size:11px;color:var(--t2);line-height:1.5;overflow:hidden;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.pl-dl{font-size:10px;color:var(--t3);background:var(--s3);padding:2px 6px;
  border-radius:4px;white-space:nowrap;flex-shrink:0;align-self:flex-start}
.inst-btn{width:100%;padding:7px;border-radius:var(--r-sm);border:none;
  background:var(--acc);color:#fff;font-size:12px;font-weight:600;cursor:pointer;
  transition:opacity var(--dur);display:flex;align-items:center;justify-content:center;
  gap:5px;font-family:var(--f)}
.inst-btn:hover{opacity:.85}.inst-btn:disabled{opacity:.4;cursor:not-allowed}
.pl-empty{grid-column:1/-1;display:flex;flex-direction:column;align-items:center;
  justify-content:center;gap:10px;color:var(--t3);padding:60px 0}
.pl-empty svg{width:40px;height:40px;opacity:.25}
.pl-empty p{font-size:13px}

/* SPINNER */
.spin{width:16px;height:16px;border-radius:50%;border:2px solid var(--bd);
  border-top-color:var(--acc);animation:sp .6s linear infinite;flex-shrink:0}
@keyframes sp{to{transform:rotate(360deg)}}

/* TOAST */
.toasts{position:fixed;bottom:72px;right:14px;z-index:9999;
  display:flex;flex-direction:column;gap:8px;pointer-events:none}
@media(min-width:641px){.toasts{bottom:20px}}
.toast{background:var(--glass);backdrop-filter:blur(20px) saturate(180%);
  -webkit-backdrop-filter:blur(20px) saturate(180%);
  border:1px solid var(--bd);border-radius:var(--r);padding:10px 14px;
  display:flex;align-items:center;gap:9px;font-size:13px;font-weight:500;
  box-shadow:var(--sh);pointer-events:auto;
  transform:translateY(10px);opacity:0;transition:transform .3s ease,opacity .3s ease}
.toast.show{transform:translateY(0);opacity:1}

/* MOBILE NAV */
.mob-nav{display:none;background:var(--glass);
  backdrop-filter:blur(20px) saturate(180%);-webkit-backdrop-filter:blur(20px) saturate(180%);
  border-top:1px solid var(--bd);padding-bottom:env(safe-area-inset-bottom,0px);flex-shrink:0}
@media(max-width:640px){.mob-nav{display:block}}
.mob-inner{display:flex}
.mob-btn{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;
  gap:3px;padding:9px 4px;border:none;background:none;color:var(--t3);
  font-size:10px;font-weight:500;cursor:pointer;transition:color var(--dur);font-family:var(--f)}
.mob-btn.active{color:var(--acc)}
.mob-btn svg{width:22px;height:22px}
</style>
</head>
<body>

<!-- TOOLBAR -->
<header class="toolbar">
  <div class="tl-wrap">
    <div class="tl tl-r"></div>
    <div class="tl tl-y"></div>
    <div class="tl tl-g"></div>
  </div>
  <div class="tb-title">
    <div class="pip" id="pip"></div>
    <span>Minecraft Panel</span>
  </div>
  <div class="tb-actions">
    <button class="icon-btn" onclick="toggleTheme()" id="theme-btn" title="Toggle theme">
      <svg id="theme-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
      </svg>
    </button>
  </div>
</header>

<div class="app-body">
  <!-- SIDEBAR -->
  <aside class="sidebar">
    <div class="sb-label">Navigation</div>
    <button class="nav-item active" id="d-console" onclick="tab('console')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" x2="20" y1="19" y2="19"/></svg>
      Console
    </button>
    <button class="nav-item" id="d-files" onclick="tab('files')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
      Files
    </button>
    <button class="nav-item" id="d-plugins" onclick="tab('plugins')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2H2v10l9.29 9.29c.94.94 2.48.94 3.42 0l6.58-6.58c.94-.94.94-2.48 0-3.42L12 2Z"/><path d="M7 7h.01"/></svg>
      Plugins
    </button>
  </aside>

  <main class="main">
    <!-- CONSOLE -->
    <div class="tab-pane active" id="tab-console">
      <div class="win">
        <div class="win-bar">
          <div class="live-dot"></div>
          <div class="win-bar-title">Live Console</div>
          <button class="icon-btn" onclick="clearLog()" title="Clear log">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg>
          </button>
        </div>
        <div class="log-out" id="logs"></div>
        <div class="cmd-bar">
          <span class="cmd-prompt">→</span>
          <input class="cmd-in" id="cmd" type="text" placeholder="Type a command…" autocomplete="off"
                 onkeydown="if(event.key==='Enter')sendCmd()">
          <button class="send-btn" onclick="sendCmd()" title="Send">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
          </button>
        </div>
      </div>
    </div>

    <!-- FILES -->
    <div class="tab-pane" id="tab-files">
      <div class="win" id="drop-zone">
        <div class="drag-ov" id="drag-ov">Drop file to upload</div>
        <div class="fm-bar">
          <div class="breadcrumb" id="path-bread"></div>
          <button class="icon-btn" onclick="document.getElementById('up-in').click()" title="Upload">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/><path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/></svg>
          </button>
          <button class="icon-btn" onclick="refreshFiles()" title="Refresh">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
          </button>
          <input type="file" id="up-in" style="display:none" onchange="uploadFile()">
        </div>
        <div class="file-list" id="file-list"></div>
      </div>
    </div>

    <!-- PLUGINS -->
    <div class="tab-pane" id="tab-plugins">
      <div class="win">
        <div class="pl-hd">
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
            <div class="segment">
              <button class="seg-btn active" id="pv-browser" onclick="setPView('browser')">Browse</button>
              <button class="seg-btn" id="pv-installed" onclick="setPView('installed')">Installed</button>
            </div>
            <div class="pl-row" id="pl-ctrl">
              <select class="sf-sel" id="pl-loader">
                <option value="paper">Paper / Spigot</option>
                <option value="purpur">Purpur</option>
                <option value="velocity">Velocity</option>
                <option value="waterfall">Waterfall</option>
                <option value="fabric">Fabric</option>
              </select>
              <input class="sf-ver" id="pl-ver" type="text" value="1.20.4" placeholder="1.x.x">
            </div>
          </div>
          <div id="srch-row" style="display:flex;gap:8px">
            <div class="srch-wrap">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
              <input class="sf-srch" id="pl-q" type="text" placeholder="Search Modrinth (e.g. LuckPerms)…"
                     onkeydown="if(event.key==='Enter')searchPlugins()">
            </div>
            <button class="srch-btn" onclick="searchPlugins()">Search</button>
          </div>
        </div>
        <div class="pl-grid" id="pl-list">
          <div class="pl-empty">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
            <p>Select loader &amp; version, then search.</p>
          </div>
        </div>
      </div>
    </div>
  </main>
</div>

<!-- MOBILE NAV -->
<nav class="mob-nav">
  <div class="mob-inner">
    <button class="mob-btn active" id="m-console" onclick="tab('console')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" x2="20" y1="19" y2="19"/></svg>
      Console
    </button>
    <button class="mob-btn" id="m-files" onclick="tab('files')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
      Files
    </button>
    <button class="mob-btn" id="m-plugins" onclick="tab('plugins')">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2H2v10l9.29 9.29c.94.94 2.48.94 3.42 0l6.58-6.58c.94-.94.94-2.48 0-3.42L12 2Z"/><path d="M7 7h.01"/></svg>
      Plugins
    </button>
  </div>
</nav>

<div class="toasts" id="toasts"></div>

<script>
// ── THEME ──────────────────────────────────────────
const html=document.documentElement;
const MOON=`<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>`;
const SUN=`<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>`;
function applyTheme(t){
  html.dataset.theme=t;
  localStorage.setItem('mc-theme',t);
  document.querySelector('#theme-icon').innerHTML=t==='dark'?MOON:SUN;
}
function toggleTheme(){applyTheme(html.dataset.theme==='dark'?'light':'dark');}
(function(){
  const s=localStorage.getItem('mc-theme');
  if(s)applyTheme(s);
  else if(window.matchMedia&&window.matchMedia('(prefers-color-scheme:light)').matches)applyTheme('light');
  else applyTheme('dark');
})();

// ── TOAST ──────────────────────────────────────────
function toast(msg,err=false){
  const c=document.getElementById('toasts');
  const d=document.createElement('div');d.className='toast';
  const col=err?'var(--red)':'var(--acc)';
  const ic=err
    ?`<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="${col}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`
    :`<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="${col}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`;
  d.innerHTML=ic+`<span>${msg}</span>`;
  c.appendChild(d);
  requestAnimationFrame(()=>requestAnimationFrame(()=>d.classList.add('show')));
  setTimeout(()=>{d.classList.remove('show');setTimeout(()=>d.remove(),350);},3000);
}

// ── TABS ────────────────────────────────────────────
let curTab='console';
function tab(id){
  curTab=id;
  document.querySelectorAll('.tab-pane').forEach(e=>e.classList.remove('active'));
  document.querySelectorAll('.nav-item,.mob-btn').forEach(e=>e.classList.remove('active'));
  document.getElementById('tab-'+id).classList.add('active');
  ['d-','m-'].forEach(p=>{const el=document.getElementById(p+id);if(el)el.classList.add('active');});
  if(id==='files'&&!curPath)refreshFiles();
  if(id==='plugins'&&curView==='installed')loadInstalled();
}

// ── CONSOLE ─────────────────────────────────────────
const logs=document.getElementById('logs');
let ws,wsRetries=0;

function ansiToHtml(raw){
  let s=raw.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  // \x1b is the ESC character in JS — matches actual ANSI escape sequences
  s=s.replace(/\x1b\[(\d+(?:;\d+)*)m/g,(_,codes)=>{
    let o='';
    for(const n of codes.split(';').map(Number)){
      if(n===0)o+='</span>';
      else if(n===1)o+='<span style="font-weight:700">';
      else if(n===2)o+='<span style="opacity:.55">';
      else if(n===3)o+='<span style="font-style:italic">';
      else if(n===30)o+='<span style="color:#555">';
      else if(n===31)o+='<span style="color:#FF6B6B">';
      else if(n===32)o+='<span style="color:#51CF66">';
      else if(n===33)o+='<span style="color:#FFD43B">';
      else if(n===34)o+='<span style="color:#74C0FC">';
      else if(n===35)o+='<span style="color:#CC5DE8">';
      else if(n===36)o+='<span style="color:#22D3EE">';
      else if(n===37)o+='<span style="color:#F8F9FA">';
      else if(n===90)o+='<span style="color:#666">';
    }
    return o;
  });
  s=s.replace(/\x1b\[[^m]*m/g,'');  // strip unknown sequences
  return s;
}

function appendLog(text){
  const l=document.createElement('div');l.className='log-line';
  l.innerHTML=ansiToHtml(text);
  logs.appendChild(l);
  if(logs.children.length>500)logs.removeChild(logs.firstChild);
  if(logs.scrollHeight-logs.scrollTop<logs.clientHeight+80)logs.scrollTop=logs.scrollHeight;
}
function clearLog(){logs.innerHTML='';}

function connectWS(){
  const proto=location.protocol==='https:'?'wss:':'ws:';
  ws=new WebSocket(`${proto}//${location.host}/ws`);
  ws.onopen=()=>{
    wsRetries=0;
    document.getElementById('pip').style.background='var(--acc)';
    document.getElementById('pip').style.boxShadow='0 0 6px var(--acc)';
  };
  ws.onmessage=e=>appendLog(e.data);
  ws.onclose=()=>{
    document.getElementById('pip').style.background='var(--red)';
    document.getElementById('pip').style.boxShadow='none';
    const delay=Math.min(1000*(2**wsRetries),30000);wsRetries++;
    appendLog(`\x1b[33m[Panel] Disconnected — reconnecting in ${Math.round(delay/1000)}s\x1b[0m`);
    setTimeout(connectWS,delay);
  };
  ws.onerror=()=>ws.close();
}
connectWS();

function sendCmd(){
  const i=document.getElementById('cmd'),v=i.value.trim();if(!v)return;
  if(ws&&ws.readyState===WebSocket.OPEN){ws.send(v);i.value='';}
  else toast('Not connected to server',true);
}

// ── FILES ───────────────────────────────────────────
let curPath='';
function buildBread(p){
  const el=document.getElementById('path-bread');
  const parts=p.split('/').filter(Boolean);
  let h=`<button onclick="refreshFiles('')"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg></button>`;
  parts.forEach((x,i,a)=>{
    const p2=a.slice(0,i+1).join('/');
    h+=`<span class="sep">›</span><button onclick="refreshFiles('${p2}')">${x}</button>`;
  });
  el.innerHTML=h;
}
async function refreshFiles(p=curPath){
  curPath=p;buildBread(p);
  const l=document.getElementById('file-list');
  l.innerHTML=`<div style="display:flex;justify-content:center;padding:32px"><div class="spin"></div></div>`;
  try{
    const r=await fetch(`/api/fs/list?path=${encodeURIComponent(p)}`);
    const d=await r.json();l.innerHTML='';
    if(p)d.unshift({name:'..',is_dir:true,parent:true});
    if(!d.length){l.innerHTML=`<div style="padding:48px;text-align:center;font-size:13px;color:var(--t3)">Empty directory</div>`;return;}
    d.forEach(f=>{
      const row=document.createElement('div');row.className='file-row';
      const fp=(p?p+'/':'')+f.name;
      if(f.parent){
        row.onclick=()=>refreshFiles(p.split('/').slice(0,-1).join('/'));
        row.innerHTML=`<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--t3)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="15 18 9 12 15 6"/></svg><span class="file-name" style="color:var(--t2)">Back</span>`;
      }else{
        row.onclick=()=>f.is_dir?refreshFiles(fp):null;
        const ico=f.is_dir
          ?`<svg width="16" height="16" viewBox="0 0 24 24" fill="var(--acc)" stroke="none" opacity=".85"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>`
          :`<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--t3)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>`;
        row.innerHTML=`${ico}<span class="file-name">${f.name}</span>
          <button class="file-del" onclick="event.stopPropagation();delFile('${fp}')" title="Delete">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/></svg>
          </button>`;
      }
      l.appendChild(row);
    });
  }catch(e){toast('Failed to load files',true);}
}

async function uploadFile(){
  const f=document.getElementById('up-in').files[0];if(!f)return;
  const fd=new FormData();fd.append('path',curPath);fd.append('file',f);
  toast('Uploading…');
  const r=await fetch('/api/fs/upload',{method:'POST',body:fd});
  r.ok?(toast('Uploaded ✓'),refreshFiles()):toast('Upload failed',true);
  document.getElementById('up-in').value='';
}
async function delFile(p){
  if(!confirm('Delete '+p+'?'))return;
  const fd=new FormData();fd.append('path',p);
  const r=await fetch('/api/fs/delete',{method:'POST',body:fd});
  r.ok?(toast('Deleted'),refreshFiles()):toast('Delete failed',true);
}

// Drag & drop
const dz=document.getElementById('drop-zone'),dov=document.getElementById('drag-ov');
if(dz){
  dz.addEventListener('dragover',e=>{e.preventDefault();dov.classList.add('on');});
  dz.addEventListener('dragleave',()=>dov.classList.remove('on'));
  dz.addEventListener('drop',async e=>{
    e.preventDefault();dov.classList.remove('on');
    const file=e.dataTransfer.files[0];if(!file)return;
    const fd=new FormData();fd.append('path',curPath);fd.append('file',file);
    toast('Uploading…');
    const r=await fetch('/api/fs/upload',{method:'POST',body:fd});
    r.ok?(toast('Uploaded ✓'),refreshFiles()):toast('Upload failed',true);
  });
}

// ── PLUGINS ─────────────────────────────────────────
let curView='browser';
function setPView(v){
  curView=v;
  document.getElementById('pv-browser').className='seg-btn'+(v==='browser'?' active':'');
  document.getElementById('pv-installed').className='seg-btn'+(v==='installed'?' active':'');
  document.getElementById('srch-row').style.display=v==='browser'?'flex':'none';
  document.getElementById('pl-ctrl').style.display=v==='browser'?'flex':'none';
  if(v==='browser'){
    document.getElementById('pl-list').innerHTML=`<div class="pl-empty">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
      <p>Ready to search.</p></div>`;
  }else loadInstalled();
}

async function searchPlugins(){
  const q=document.getElementById('pl-q').value.trim();if(!q)return;
  const list=document.getElementById('pl-list');
  list.innerHTML=`<div style="grid-column:1/-1;display:flex;justify-content:center;padding:40px"><div class="spin"></div></div>`;
  try{
    const res=await fetch(`https://api.modrinth.com/v2/search?query=${encodeURIComponent(q)}&facets=[["project_type:plugin"]]&limit=20`);
    const data=await res.json();list.innerHTML='';
    if(!data.hits.length){list.innerHTML=`<div class="pl-empty"><p>No results on Modrinth.</p></div>`;return;}
    data.hits.forEach(p=>{
      const card=document.createElement('div');card.className='pl-card';
      card.innerHTML=`
        <div class="pl-head">
          <img class="pl-ico" src="${p.icon_url||''}" onerror="this.src='https://placehold.co/36x36/3A3A3C/888?text=?'" alt="">
          <div class="pl-meta">
            <div style="display:flex;justify-content:space-between;gap:4px;align-items:flex-start">
              <div class="pl-name" title="${p.title}">${p.title}</div>
              <div class="pl-dl">${p.downloads.toLocaleString()} dl</div>
            </div>
            <div class="pl-desc">${p.description}</div>
          </div>
        </div>
        <button class="inst-btn" id="btn-${p.project_id}"
                onclick="resolveInstall('${p.project_id}','${p.title.replace(/'/g,'')}')">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          Install
        </button>`;
      list.appendChild(card);
    });
  }catch(e){list.innerHTML=`<div class="pl-empty" style="color:var(--red)"><p>Error connecting to Modrinth.</p></div>`;}
}

async function resolveInstall(id,name){
  const loaderRaw=document.getElementById('pl-loader').value;
  const version=document.getElementById('pl-ver').value.trim();
  const btn=document.getElementById('btn-'+id);
  const ogHtml=btn.innerHTML;
  btn.innerHTML=`<div class="spin" style="border-top-color:#fff;width:13px;height:13px"></div> Checking…`;
  btn.disabled=true;
  let loaders=[loaderRaw];
  if(loaderRaw==='purpur')loaders=['paper','spigot','purpur'];
  if(loaderRaw==='paper')loaders=['paper','spigot'];
  if(loaderRaw==='waterfall')loaders=['bungeecord','waterfall'];
  try{
    const res=await fetch(`https://api.modrinth.com/v2/project/${id}/version?loaders=${JSON.stringify(loaders)}&game_versions=${JSON.stringify([version])}`);
    const versions=await res.json();
    if(!versions.length){toast(`No version for ${loaderRaw} ${version}`,true);setTimeout(()=>{btn.innerHTML=ogHtml;btn.disabled=false;},2000);return;}
    const file=versions[0].files.find(f=>f.primary)||versions[0].files[0];
    btn.innerHTML=`Downloading…`;
    const fd=new FormData();
    fd.append('url',file.url);fd.append('filename',file.filename);
    fd.append('project_id',id);fd.append('version_id',versions[0].id);fd.append('name',name);
    const dl=await fetch('/api/plugins/install',{method:'POST',body:fd});
    if(dl.ok){
      toast(`Installed ${name} ✓`);
      btn.style.cssText='background:var(--s3);color:var(--acc)';
      btn.innerHTML=`<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg> Installed`;
    }else throw new Error();
  }catch(e){toast('Installation failed',true);setTimeout(()=>{btn.innerHTML=ogHtml;btn.disabled=false;},2000);}
}

async function loadInstalled(){
  const l=document.getElementById('pl-list');
  l.innerHTML=`<div style="grid-column:1/-1;display:flex;justify-content:center;padding:40px"><div class="spin"></div></div>`;
  try{
    const r=await fetch('/api/fs/read?path=plugins/plugins.json');if(!r.ok)throw new Error();
    const data=await r.json();l.innerHTML='';
    if(!Object.keys(data).length){l.innerHTML=`<div class="pl-empty"><p>No plugins installed via Panel.</p></div>`;return;}
    for(const[pid,d]of Object.entries(data)){
      const card=document.createElement('div');card.className='pl-card';
      card.innerHTML=`
        <div style="display:flex;justify-content:space-between;align-items:flex-start">
          <div class="pl-name">${d.name}</div>
          <button onclick="delFile('plugins/${d.filename}')" style="background:none;border:none;color:var(--t3);cursor:pointer;padding:2px;border-radius:4px" title="Remove">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/></svg>
          </button>
        </div>
        <div style="font-family:var(--mono);font-size:10px;color:var(--t3);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${d.filename}</div>
        <div style="background:var(--s3);color:var(--t2);font-size:11px;padding:5px 10px;border-radius:var(--r-sm);text-align:center">Installed</div>`;
      l.appendChild(card);
    }
  }catch(e){l.innerHTML=`<div class="pl-empty"><p>No plugins.json record found.</p></div>`;}
}
</script>
</body>
</html>
"""

# ─────────────────────────────────────────────
# BACKEND
# ─────────────────────────────────────────────
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

    # ── Wait for background world download (started by start.sh) ──────────
    # start.sh runs: (python3 download_world.py; touch /tmp/world_dl_done) &
    # Without this wait, Minecraft would start before the world is copied in.
    if os.environ.get("FOLDER_URL"):
        output_history.append("\u23f3 [Panel] World download is running in background, waiting\u2026")
        for i in range(600):          # up to 10 min
            if os.path.exists("/tmp/world_dl_done"):
                output_history.append("\u2705 [Panel] World download finished! Starting Minecraft\u2026")
                break
            if i > 0 and i % 30 == 0:
                output_history.append(f"\u23f3 [Panel] Still waiting\u2026 ({i}s elapsed)")
            await asyncio.sleep(1)
        else:
            output_history.append("\u26a0 [Panel] Download wait timed out. Starting Minecraft anyway\u2026")
    else:
        open("/tmp/world_dl_done", "w").close()   # mark done immediately

    if not os.path.exists(jar):
        output_history.append("\u26a0 [Panel] purpur.jar not found in /app \u2014 upload it via the Files tab.")
        return

    output_history.append("\U0001f680 [Panel] Starting Minecraft server\u2026")
    mc_process = await asyncio.create_subprocess_exec(
        "java", "-Xmx4G", "-Xms1G",
        "-Dfile.encoding=UTF-8",
        "-XX:+UseG1GC", "-XX:+ParallelRefProcEnabled",
        "-XX:MaxGCPauseMillis=200",
        "-jar", jar, "--nogui",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=BASE_DIR
    )
    asyncio.create_task(stream_output(mc_process.stdout))

# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────
@app.get("/")
def index(): return HTMLResponse(HTML_CONTENT)

@app.websocket("/ws")
async def ws_end(ws: WebSocket):
    await ws.accept()
    connected_clients.add(ws)
    for line in output_history: await ws.send_text(line)
    try:
        while True:
            cmd = await ws.receive_text()
            if mc_process and mc_process.stdin:
                mc_process.stdin.write((cmd + "\n").encode())
                await mc_process.stdin.drain()
    except:
        connected_clients.discard(ws)

@app.get("/api/status")
def api_status():
    return {"running": mc_process is not None and mc_process.returncode is None}

@app.get("/api/fs/list")
def list_fs(path: str = ""):
    t = get_path(path)
    if not os.path.exists(t): return []
    res = [{"name": x, "is_dir": os.path.isdir(os.path.join(t, x))} for x in os.listdir(t)]
    return sorted(res, key=lambda k: (not k["is_dir"], k["name"].lower()))

@app.post("/api/fs/upload")
async def upload(path: str = Form(""), file: UploadFile = File(...)):
    t = get_path(path)
    os.makedirs(t, exist_ok=True)
    with open(os.path.join(t, file.filename), "wb") as f:
        shutil.copyfileobj(file.file, f)
    return "ok"

@app.post("/api/fs/delete")
def delete(path: str = Form(...)):
    t = get_path(path)
    if os.path.isdir(t): shutil.rmtree(t)
    else: os.remove(t)
    return "ok"

@app.get("/api/fs/read")
def read(path: str):
    try:
        with open(get_path(path), "r", encoding="utf-8") as f:
            return json.load(f) if path.endswith(".json") else Response(f.read())
    except:
        raise HTTPException(404)

@app.post("/api/plugins/install")
def install_pl(
    url: str = Form(...), filename: str = Form(...),
    project_id: str = Form(...), version_id: str = Form(...),
    name: str = Form(...)
):
    try:
        dest = os.path.join(PLUGINS_DIR, filename)
        req = urllib.request.Request(url, headers={"User-Agent": "HF-Panel/1.0"})
        with urllib.request.urlopen(req) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
        j_path = os.path.join(PLUGINS_DIR, "plugins.json")
        data = {}
        if os.path.exists(j_path):
            try:
                with open(j_path, "r") as f: data = json.load(f)
            except: pass
        data[project_id] = {
            "name": name, "filename": filename,
            "version_id": version_id, "installed_at": time.time()
        }
        with open(j_path, "w") as f: json.dump(data, f, indent=2)
        return "ok"
    except Exception as e:
        raise HTTPException(500, str(e))

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 7860)),
        log_level="error"
    )