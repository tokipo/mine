import os, asyncio, collections, shutil, urllib.request, json, time, re, threading
from pathlib import Path
from fastapi import FastAPI, WebSocket, Form, UploadFile, File, HTTPException, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ─── CONFIG ──────────────────────────────────────────────────────────────────
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])

BASE_DIR     = os.environ.get("SERVER_DIR", os.path.abspath("/app"))
PLUGINS_DIR  = os.path.join(BASE_DIR, "plugins")
PANEL_CFG    = os.path.join(BASE_DIR, ".panel_config.json")

mc_process       = None
output_history   = collections.deque(maxlen=500)
connected_clients: set = set()
server_start_time: float | None = None

# ─── HTML FRONTEND ────────────────────────────────────────────────────────────
HTML_CONTENT = r"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>Orbit Panel</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent}
:root{--bg:#0a0a0a;--bg2:#111;--bg3:#161616;--bg4:#1e1e1e;--bg5:#2a2a2a;--g:#00ff88;--gd:#00cc6a;--ga:rgba(0,255,136,.08);--ga2:rgba(0,255,136,.16);--t:#eaeaea;--t2:#888;--t3:#555;--r:#ff4757;--y:#ffa502;--b:#5b9aff;--brd:#1c1c1c;--rad:10px;--font:'Inter',sans-serif;--mono:'JetBrains Mono',monospace;--tsz:14px;--ease:cubic-bezier(.4,0,.2,1)}
html,body{height:100%;font-family:var(--font);background:var(--bg);color:var(--t);overflow:hidden;font-size:var(--tsz);line-height:1.5}
::-webkit-scrollbar{width:5px;height:5px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:#333;border-radius:3px}::-webkit-scrollbar-thumb:hover{background:#444}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
@keyframes fadeUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
@keyframes scaleIn{from{opacity:0;transform:scale(.96)}to{opacity:1;transform:scale(1)}}
@keyframes circleIn{from{stroke-dashoffset:283}to{stroke-dashoffset:var(--offset)}}
@keyframes spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}
.layout{display:flex;height:100vh}
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:200;opacity:0;pointer-events:none;transition:opacity .25s var(--ease);backdrop-filter:blur(2px)}
.overlay.on{opacity:1;pointer-events:auto}
.sb{width:230px;min-width:230px;height:100vh;background:var(--bg2);border-right:1px solid var(--brd);display:flex;flex-direction:column;z-index:300;overflow-y:auto}
.sb-logo{padding:18px 20px;font-size:17px;font-weight:700;color:var(--g);display:flex;align-items:center;gap:10px;border-bottom:1px solid var(--brd);letter-spacing:-.3px}
.sb-logo i{font-size:18px}
.sb nav{flex:1;padding:10px}
.nav-item{display:flex;align-items:center;gap:11px;padding:9px 14px;border-radius:8px;color:var(--t2);cursor:pointer;transition:all .15s var(--ease);font-size:13px;font-weight:500;margin-bottom:1px;user-select:none;position:relative}
.nav-item:hover{background:var(--ga);color:var(--t)}
.nav-item.on{background:var(--ga2);color:var(--g)}
.nav-item.on::before{content:'';position:absolute;left:0;top:50%;transform:translateY(-50%);width:3px;height:20px;background:var(--g);border-radius:0 3px 3px 0}
.nav-item i{width:18px;text-align:center;font-size:14px}
.sb-footer{padding:14px 16px;border-top:1px solid var(--brd);font-size:11px;color:var(--t3)}
.sb-status{display:flex;align-items:center;gap:6px;margin-bottom:4px}
.sb-status .dot{width:8px;height:8px;border-radius:50%;background:var(--g);box-shadow:0 0 8px var(--g)}
.main{flex:1;display:flex;flex-direction:column;overflow:hidden}
.m-header{display:none}
.content{flex:1;overflow-y:auto;overflow-x:hidden}
.tab{display:none;padding:24px;animation:fadeIn .2s var(--ease)}
.tab.on{display:block}
.tab-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;gap:12px;flex-wrap:wrap}
.tab-title{font-size:18px;font-weight:600;letter-spacing:-.3px}
.badge{display:inline-flex;align-items:center;gap:5px;padding:4px 10px;border-radius:20px;font-size:11px;font-weight:600}
.badge-green{background:rgba(0,255,136,.12);color:var(--g)}
.badge-red{background:rgba(255,71,87,.12);color:var(--r)}
.card{background:var(--bg3);border:1px solid var(--brd);border-radius:var(--rad);padding:20px;transition:border-color .15s var(--ease)}
.card:hover{border-color:var(--bg5)}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.grid2{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}
.gauge-card{text-align:center;padding:24px 16px}
.gauge-card svg{width:110px;height:110px;margin-bottom:12px}
.gauge-card .gauge-bg{fill:none;stroke:var(--bg4);stroke-width:7}
.gauge-card .gauge-fill{fill:none;stroke:url(#gg);stroke-width:7;stroke-linecap:round;transform-origin:center;transform:rotate(-90deg);stroke-dasharray:283;transition:stroke-dashoffset .8s var(--ease);animation:circleIn .8s var(--ease) forwards}
.gauge-val{font-size:22px;font-weight:700;margin-bottom:2px}
.gauge-label{font-size:12px;color:var(--t2);font-weight:500}
.gauge-sub{font-size:11px;color:var(--t3);margin-top:2px}
.info-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:16px}
.info-card{padding:16px}
.info-card .ic-label{font-size:11px;color:var(--t3);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px;font-weight:600}
.info-card .ic-val{font-size:16px;font-weight:600}
.info-card .ic-val.green{color:var(--g)}
.graph-section{margin-top:16px}
.graph-section h3{font-size:14px;font-weight:600;margin-bottom:12px;display:flex;align-items:center;gap:8px}
.graph-row{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}
.graph-card{padding:16px}
.graph-card .g-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.graph-card .g-title{font-size:12px;color:var(--t2);font-weight:500}
.graph-card .g-val{font-size:14px;font-weight:600;color:var(--g)}
.graph-card canvas{width:100%;height:60px;display:block}
.console-wrap{display:flex;flex-direction:column;height:calc(100vh - 130px)}
.console-controls{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}
.console-output{flex:1;background:#0c0c0c;border:1px solid var(--brd);border-radius:var(--rad);overflow-y:auto;position:relative;font-family:var(--mono);font-size:11.5px;line-height:1.7;min-height:0}
.console-scroll{padding:14px;padding-top:30px}
.console-output::before{content:'';position:absolute;top:0;left:0;right:0;height:30px;background:linear-gradient(#0c0c0c,transparent);z-index:2;pointer-events:none;border-radius:var(--rad) var(--rad) 0 0}
.c-line{animation:fadeUp .15s var(--ease);white-space:pre-wrap;word-break:break-all}
.c-line .c-time{color:var(--t3)}.c-line .c-info{color:#5b9aff}.c-line .c-warn{color:var(--y)}.c-line .c-error{color:var(--r)}.c-line .c-green{color:var(--g)}
.console-input{display:flex;gap:8px;margin-top:10px}
.console-input input{flex:1;background:#0c0c0c;border:1px solid var(--brd);border-radius:8px;padding:10px 14px;color:var(--t);font-family:var(--mono);font-size:12px;outline:none;transition:border-color .15s}
.console-input input:focus{border-color:var(--g)}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:7px;padding:8px 16px;border-radius:8px;border:none;cursor:pointer;font-family:var(--font);font-size:13px;font-weight:500;transition:all .15s var(--ease);white-space:nowrap;user-select:none}
.btn:active{transform:scale(.97)}
.btn-p{background:var(--g);color:#000}.btn-p:hover{background:var(--gd)}
.btn-r{background:var(--r);color:#fff}.btn-r:hover{background:#e83e4e}
.btn-y{background:var(--y);color:#000}.btn-y:hover{background:#e69500}
.btn-g{background:var(--bg4);color:var(--t2);border:1px solid var(--brd)}.btn-g:hover{background:var(--bg5);color:var(--t)}
.btn-s{padding:6px 12px;font-size:12px}
.btn i{font-size:12px}
.btn:disabled{opacity:.5;cursor:not-allowed;transform:none}
.spin{animation:spin .7s linear infinite}
.fm-toolbar{display:flex;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap}
.breadcrumbs{display:flex;align-items:center;gap:4px;flex:1;min-width:0;overflow-x:auto;font-size:13px}
.crumb{color:var(--t2);cursor:pointer;padding:4px 6px;border-radius:4px;transition:all .1s;white-space:nowrap}
.crumb:hover{color:var(--g);background:var(--ga)}.crumb.now{color:var(--t);cursor:default}.crumb.now:hover{background:none}
.breadcrumbs .sep{color:var(--t3);font-size:10px}
.fm-list{border:1px solid var(--brd);border-radius:var(--rad);overflow:hidden}
.fm-header{display:grid;grid-template-columns:1fr 90px 120px 40px;padding:8px 14px;background:var(--bg3);border-bottom:1px solid var(--brd);font-size:11px;color:var(--t3);font-weight:600;text-transform:uppercase;letter-spacing:.5px}
.fm-row{display:grid;grid-template-columns:1fr 90px 120px 40px;padding:9px 14px;border-bottom:1px solid var(--brd);align-items:center;transition:background .1s;cursor:pointer;animation:fadeUp .15s var(--ease)}
.fm-row:last-child{border-bottom:none}.fm-row:hover{background:var(--ga)}
.fm-name{display:flex;align-items:center;gap:10px;min-width:0}
.fm-name i{width:18px;text-align:center;font-size:14px;flex-shrink:0}
.fm-name span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px}
.fm-size,.fm-date{font-size:12px;color:var(--t2)}
.fm-actions{text-align:center}
.fm-dot{width:28px;height:28px;border-radius:6px;border:none;background:transparent;color:var(--t2);cursor:pointer;font-size:14px;display:flex;align-items:center;justify-content:center;transition:all .1s}
.fm-dot:hover{background:var(--bg5);color:var(--t)}
.paste-btn{position:fixed;bottom:24px;right:24px;z-index:100;padding:12px 24px;border-radius:12px;background:var(--g);color:#000;font-weight:600;font-size:14px;border:none;cursor:pointer;box-shadow:0 4px 20px rgba(0,255,136,.3);animation:fadeUp .2s var(--ease);display:flex;align-items:center;gap:8px;font-family:var(--font)}
.paste-btn:hover{background:var(--gd)}
.paste-btn .paste-cancel{margin-left:8px;width:24px;height:24px;border-radius:6px;background:rgba(0,0,0,.2);display:flex;align-items:center;justify-content:center;font-size:10px}
.ctx-menu{position:fixed;background:var(--bg3);border:1px solid var(--brd);border-radius:10px;padding:6px;min-width:170px;z-index:500;animation:scaleIn .12s var(--ease);box-shadow:0 8px 30px rgba(0,0,0,.5)}
.ctx-item{display:flex;align-items:center;gap:10px;padding:8px 12px;border-radius:6px;cursor:pointer;font-size:13px;color:var(--t2);transition:all .1s}
.ctx-item:hover{background:var(--ga);color:var(--t)}
.ctx-item.danger{color:var(--r)}.ctx-item.danger:hover{background:rgba(255,71,87,.1)}
.ctx-item i{width:16px;text-align:center;font-size:12px}
.ctx-sep{height:1px;background:var(--brd);margin:4px 8px}
.sub-tabs{display:flex;gap:2px;background:var(--bg3);border-radius:8px;padding:3px;margin-bottom:16px;border:1px solid var(--brd)}
.sub-tab{padding:7px 16px;border-radius:6px;cursor:pointer;font-size:13px;font-weight:500;color:var(--t2);transition:all .15s;user-select:none;text-align:center}
.sub-tab.on{background:var(--bg5);color:var(--t)}.sub-tab:hover:not(.on){color:var(--t)}
.search-box{position:relative;margin-bottom:14px}
.search-box i{position:absolute;left:12px;top:50%;transform:translateY(-50%);color:var(--t3);font-size:13px}
.search-box input{width:100%;background:var(--bg4);border:1px solid var(--brd);border-radius:8px;padding:9px 14px 9px 36px;color:var(--t);font-family:var(--font);font-size:13px;outline:none;transition:border-color .15s}
.search-box input:focus{border-color:var(--g)}
.filter-row{display:flex;gap:6px;margin-bottom:14px;flex-wrap:wrap}
.filter-btn{padding:5px 12px;border-radius:6px;border:1px solid var(--brd);background:transparent;color:var(--t2);cursor:pointer;font-size:12px;font-weight:500;transition:all .15s}
.filter-btn:hover{border-color:var(--bg5);color:var(--t)}
.filter-btn.on{border-color:var(--g);color:var(--g);background:var(--ga)}
.plugin-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.pg-card{padding:16px;display:flex;flex-direction:column;gap:10px;animation:fadeUp .2s var(--ease)}
.pg-top{display:flex;gap:12px;align-items:flex-start}
.pg-icon{width:44px;height:44px;border-radius:10px;background:var(--bg5);display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0;overflow:hidden}
.pg-icon img{width:100%;height:100%;object-fit:cover;border-radius:10px}
.pg-info{flex:1;min-width:0}
.pg-name{font-size:13px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pg-author{font-size:11px;color:var(--t3)}
.pg-desc{font-size:11.5px;color:var(--t2);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;line-height:1.5}
.pg-bottom{display:flex;align-items:center;justify-content:space-between;gap:8px}
.pg-meta{display:flex;gap:10px;font-size:10.5px;color:var(--t3)}
.pg-meta i{margin-right:2px}
.inst-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}
.inst-card{padding:14px;animation:fadeUp .2s var(--ease)}
.inst-top{display:flex;gap:12px;align-items:center;margin-bottom:10px}
.inst-icon{width:38px;height:38px;border-radius:8px;background:var(--bg5);display:flex;align-items:center;justify-content:center;font-size:17px;flex-shrink:0;overflow:hidden}
.inst-icon img{width:100%;height:100%;object-fit:cover;border-radius:8px}
.inst-info{flex:1;min-width:0}
.inst-name{font-size:13px;font-weight:600;display:flex;align-items:center;gap:6px}
.inst-ver{font-size:11px;color:var(--t3)}
.inst-bottom{display:flex;align-items:center;gap:8px;justify-content:space-between}
.inst-bottom .toggle{flex-shrink:0}
.inst-btns{display:flex;gap:6px}
.update-badge{font-size:9px;padding:2px 6px;border-radius:4px;background:rgba(255,165,2,.12);color:var(--y);font-weight:600;white-space:nowrap}
.toggle{position:relative;width:38px;height:21px;background:var(--bg5);border-radius:11px;cursor:pointer;transition:background .2s;flex-shrink:0}
.toggle::after{content:'';position:absolute;top:2.5px;left:2.5px;width:16px;height:16px;background:#666;border-radius:50%;transition:all .2s var(--ease)}
.toggle.on{background:var(--g)}.toggle.on::after{transform:translateX(17px);background:#000}
.prop-group{margin-bottom:20px}
.prop-group-title{font-size:13px;font-weight:600;color:var(--g);margin-bottom:10px;text-transform:uppercase;letter-spacing:.5px;padding-bottom:6px;border-bottom:1px solid var(--brd)}
.prop-row{display:flex;align-items:center;justify-content:space-between;padding:10px 0;border-bottom:1px solid var(--brd);gap:12px}
.prop-row:last-child{border-bottom:none}
.prop-label{font-size:13px;font-weight:500;min-width:0;flex:1}
.prop-desc{font-size:11px;color:var(--t3);margin-top:1px}
.prop-input{width:200px;flex-shrink:0}
.prop-input input,.prop-input select{width:100%;background:var(--bg4);border:1px solid var(--brd);border-radius:6px;padding:6px 10px;color:var(--t);font-family:var(--font);font-size:12px;outline:none;transition:border-color .15s}
.prop-input input:focus,.prop-input select:focus{border-color:var(--g)}
.custom-select{position:relative;cursor:pointer}
.custom-select .cs-display{display:flex;align-items:center;justify-content:space-between;width:100%;background:var(--bg4);border:1px solid var(--brd);border-radius:6px;padding:6px 10px;color:var(--t);font-size:12px;transition:border-color .15s;user-select:none}
.custom-select.open .cs-display{border-color:var(--g)}
.cs-display i{font-size:10px;color:var(--t3);transition:transform .15s}
.custom-select.open .cs-display i{transform:rotate(180deg)}
.cs-options{position:absolute;top:calc(100% + 4px);left:0;right:0;background:var(--bg3);border:1px solid var(--brd);border-radius:8px;padding:4px;z-index:50;animation:scaleIn .12s var(--ease);box-shadow:0 8px 24px rgba(0,0,0,.5);display:none;max-height:200px;overflow-y:auto}
.custom-select.open .cs-options{display:block}
.cs-opt{padding:6px 10px;border-radius:5px;font-size:12px;color:var(--t2);transition:all .1s;cursor:pointer}
.cs-opt:hover{background:var(--ga);color:var(--t)}
.cs-opt.on{color:var(--g);background:var(--ga2)}
.color-input-wrap{display:flex;gap:8px;align-items:center}
.color-input-wrap input[type=text]{flex:1}
.color-preview{width:32px;height:32px;border-radius:6px;border:2px solid var(--brd);flex-shrink:0;cursor:pointer;position:relative;overflow:hidden}
.color-preview input[type=color]{position:absolute;inset:-4px;width:calc(100% + 8px);height:calc(100% + 8px);border:none;cursor:pointer;opacity:0}
.sw-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px}
.sw-card{padding:16px;text-align:center;animation:fadeUp .2s var(--ease)}
.sw-icon{width:56px;height:56px;border-radius:14px;background:var(--bg5);display:flex;align-items:center;justify-content:center;font-size:26px;margin:0 auto 10px}
.sw-name{font-size:14px;font-weight:600;margin-bottom:2px}
.sw-desc{font-size:11px;color:var(--t3);margin-bottom:10px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.sw-ver-list{display:flex;flex-direction:column;gap:4px;max-height:180px;overflow-y:auto;margin-bottom:10px}
.sw-ver{display:flex;align-items:center;justify-content:space-between;padding:5px 8px;border-radius:6px;font-size:11px;color:var(--t2);cursor:pointer;transition:all .1s}
.sw-ver:hover{background:var(--ga);color:var(--t)}
.sw-ver.active{background:var(--ga2);color:var(--g)}
.sw-ver .sv-tag{font-size:10px;padding:1px 6px;border-radius:3px;background:var(--ga);color:var(--g)}
.sw-loader{display:flex;justify-content:center;padding:20px}
.sw-spinner{width:20px;height:20px;border:2px solid var(--brd);border-top-color:var(--g);border-radius:50%;animation:spin .7s linear infinite}
.coming-soon{display:flex;flex-direction:column;align-items:center;justify-content:center;height:60vh;color:var(--t3);gap:16px}
.coming-soon i{font-size:48px;color:var(--bg5)}
.coming-soon h2{font-size:20px;font-weight:600;color:var(--t2)}
.modal-wrap{position:fixed;inset:0;z-index:400;display:flex;align-items:center;justify-content:center;padding:16px;opacity:0;pointer-events:none;transition:opacity .2s var(--ease)}
.modal-wrap.on{opacity:1;pointer-events:auto}
.modal-bg{position:absolute;inset:0;background:rgba(0,0,0,.7);backdrop-filter:blur(4px)}
.modal{position:relative;background:var(--bg2);border:1px solid var(--brd);border-radius:14px;width:100%;max-width:500px;max-height:90vh;display:flex;flex-direction:column;animation:scaleIn .2s var(--ease);box-shadow:0 20px 60px rgba(0,0,0,.5)}
.modal-head{display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid var(--brd)}
.modal-head h3{font-size:15px;font-weight:600}
.modal-close{width:30px;height:30px;border-radius:6px;border:none;background:transparent;color:var(--t2);cursor:pointer;font-size:14px;display:flex;align-items:center;justify-content:center;transition:all .1s}
.modal-close:hover{background:var(--bg4);color:var(--t)}
.modal-body{padding:20px;overflow-y:auto;flex:1}
.modal-foot{padding:14px 20px;border-top:1px solid var(--brd);display:flex;justify-content:flex-end;gap:8px}
.modal-body label{display:block;font-size:12px;font-weight:500;color:var(--t2);margin-bottom:6px}
.modal-body input,.modal-body textarea,.modal-body select{width:100%;background:var(--bg4);border:1px solid var(--brd);border-radius:8px;padding:9px 12px;color:var(--t);font-family:var(--font);font-size:13px;outline:none;transition:border-color .15s}
.modal-body input:focus,.modal-body textarea:focus,.modal-body select:focus{border-color:var(--g)}
.modal-body select{cursor:pointer}
.modal-body select option{background:var(--bg3)}
.modal-body textarea{font-family:var(--mono);font-size:12px;line-height:1.6;resize:vertical}
.editor-modal .modal{max-width:900px;height:80vh}
.editor-modal .modal-body{padding:0;display:flex;flex-direction:column}
.editor-modal textarea{flex:1;border:none;border-radius:0;resize:none;padding:16px;background:#0c0c0c;min-height:200px}
.img-preview{display:flex;align-items:center;justify-content:center;padding:20px;min-height:200px}
.img-preview img{max-width:100%;max-height:60vh;border-radius:8px;box-shadow:0 4px 20px rgba(0,0,0,.4)}
.toast-wrap{position:fixed;top:16px;right:16px;z-index:600;display:flex;flex-direction:column;gap:8px;pointer-events:none}
.toast{display:flex;align-items:center;gap:10px;padding:12px 16px;background:var(--bg2);border:1px solid var(--brd);border-radius:10px;font-size:13px;pointer-events:auto;animation:fadeUp .2s var(--ease);box-shadow:0 8px 24px rgba(0,0,0,.4);max-width:340px}
.toast i{font-size:14px;flex-shrink:0}
.toast.success i{color:var(--g)}.toast.error i{color:var(--r)}.toast.warn i{color:var(--y)}
.upload-zone{border:2px dashed var(--brd);border-radius:var(--rad);padding:40px;text-align:center;color:var(--t3);cursor:pointer;transition:all .2s}
.upload-zone:hover,.upload-zone.drag{border-color:var(--g);background:var(--ga);color:var(--t2)}
.upload-zone i{font-size:32px;margin-bottom:10px;display:block}
.warn-icon{width:48px;height:48px;border-radius:50%;background:rgba(255,71,87,.1);display:flex;align-items:center;justify-content:center;margin:0 auto 14px;font-size:20px;color:var(--r)}
.warn-text{text-align:center;font-size:14px;margin-bottom:6px}
.warn-sub{text-align:center;font-size:12px;color:var(--t3)}
.ver-select-wrap{margin-top:16px}
.ver-select-wrap label{display:block;font-size:12px;font-weight:500;color:var(--t2);margin-bottom:8px}
.ver-loading{text-align:center;padding:20px;color:var(--t3);font-size:12px}
.ver-option{display:flex;align-items:center;justify-content:space-between;padding:8px 12px;border:1px solid var(--brd);border-radius:6px;margin-bottom:4px;cursor:pointer;transition:all .15s;font-size:12px}
.ver-option:hover{border-color:var(--g);background:var(--ga)}
.ver-option.selected{border-color:var(--g);background:var(--ga2);color:var(--g)}
.ver-option-left{display:flex;flex-direction:column;gap:2px}
.ver-option-num{font-weight:600}
.ver-option-meta{font-size:10.5px;color:var(--t3)}
.ver-option.selected .ver-option-meta{color:var(--g);opacity:.7}
@media(max-width:768px){
.sb{position:fixed;left:0;top:0;bottom:0;transform:translateX(-100%);transition:transform .3s var(--ease);width:260px;min-width:260px}
.sb.open{transform:translateX(0)}
.m-header{display:flex;height:52px;background:var(--bg2);border-bottom:1px solid var(--brd);align-items:center;padding:0 14px;gap:12px;flex-shrink:0}
.m-header .ham{width:36px;height:36px;border-radius:8px;border:none;background:transparent;color:var(--t);cursor:pointer;font-size:16px;display:flex;align-items:center;justify-content:center}
.m-header .m-logo{font-size:15px;font-weight:700;color:var(--g);flex:1}
.m-header .m-status{width:8px;height:8px;border-radius:50%;background:var(--g);box-shadow:0 0 8px var(--g)}
.tab{padding:14px}
.grid3{grid-template-columns:repeat(3,1fr);gap:8px}
.gauge-card{padding:12px 6px}
.gauge-card svg{width:64px;height:64px;margin-bottom:6px}
.gauge-val{font-size:15px}
.gauge-label{font-size:9.5px}
.gauge-sub{font-size:8.5px}
.info-grid{grid-template-columns:repeat(2,1fr);gap:8px}
.info-card{padding:12px}
.info-card .ic-val{font-size:13px}
.graph-row{grid-template-columns:1fr}
.console-wrap{height:calc(100vh - 116px)}
.console-output{font-size:10px}
.c-line{font-size:10px}
.fm-header{grid-template-columns:1fr 40px}.fm-header .h-size,.fm-header .h-date{display:none}
.fm-row{grid-template-columns:1fr 40px}.fm-size,.fm-date{display:none}
.plugin-grid{grid-template-columns:1fr 1fr;gap:8px}
.pg-card{padding:12px}
.pg-top{gap:8px}
.pg-icon{width:36px;height:36px;font-size:16px;border-radius:8px}
.pg-name{font-size:12px}
.pg-desc{font-size:10.5px;-webkit-line-clamp:2}
.pg-meta{font-size:9.5px}
.inst-grid{grid-template-columns:1fr}
.prop-row{flex-direction:column;align-items:flex-start;gap:6px}
.prop-input{width:100%}
.modal{max-width:calc(100vw - 32px);max-height:85vh}
.editor-modal .modal{height:80vh}
.toast-wrap{top:auto;bottom:16px;right:8px;left:8px}
.toast{max-width:100%}
.console-controls{gap:6px}.console-controls .btn{padding:7px 10px;font-size:12px}
.tab-head{margin-bottom:14px}
.sw-grid{grid-template-columns:1fr 1fr;gap:8px}
.sw-card{padding:12px}
.sw-icon{width:44px;height:44px;font-size:20px;border-radius:10px;margin-bottom:8px}
.paste-btn{bottom:16px;right:16px;padding:10px 18px;font-size:13px;border-radius:10px}
}
@media(max-width:400px){
.plugin-grid{grid-template-columns:1fr}
.sw-grid{grid-template-columns:1fr}
.grid3{gap:6px}
.gauge-card svg{width:56px;height:56px}.gauge-val{font-size:13px}
}
</style></head>
<body>
<div class="layout">
<div class="overlay" id="overlay" onclick="closeSb()"></div>
<aside class="sb" id="sidebar">
<div class="sb-logo"><i class="fa-solid fa-circle-nodes"></i>Orbit Panel</div>
<nav id="nav"></nav>
<div class="sb-footer">
  <div class="sb-status"><div class="dot" id="sb-dot"></div><span id="sb-status-txt" style="color:var(--g);font-weight:600">Connecting...</span></div>
  <div id="sb-server-info">Loading...</div>
</div>
</aside>
<div class="main">
<div class="m-header"><button class="ham" onclick="toggleSb()"><i class="fa-solid fa-bars"></i></button><div class="m-logo"><i class="fa-solid fa-circle-nodes" style="margin-right:6px"></i>Orbit Panel</div><div class="m-status" id="m-dot" style="width:8px;height:8px;border-radius:50%;background:var(--g);box-shadow:0 0 8px var(--g)"></div></div>
<div class="content" id="content"></div>
</div>
</div>
<div id="paste-container"></div>
<div class="modal-wrap" id="modal-wrap" onclick="modalBgClick(event)"><div class="modal-bg"></div><div class="modal" id="modal-box"></div></div>
<div class="ctx-menu" id="ctx-menu" style="display:none"></div>
<div class="toast-wrap" id="toast-wrap"></div>
<svg style="position:absolute;width:0;height:0"><defs><linearGradient id="gg" x1="0%" y1="0%" x2="100%" y2="0%"><stop offset="0%" stop-color="var(--g)"/><stop offset="100%" stop-color="var(--gd)"/></linearGradient></defs></svg>

<script>
// ─── GLOBAL STATE ──────────────────────────────────────────────────────────
const tabs=[
  {id:'server',icon:'fa-server',label:'Dashboard'},
  {id:'console',icon:'fa-terminal',label:'Console'},
  {id:'files',icon:'fa-folder',label:'Files'},
  {id:'plugins',icon:'fa-puzzle-piece',label:'Plugins'},
  {id:'software',icon:'fa-box',label:'Software'},
  {id:'settings',icon:'fa-gear',label:'Settings'},
  {id:'profile',icon:'fa-user',label:'Profile'}
];
let currentTab='server',serverRunning=false,currentPath='/',pluginSubTab='browse',softwareSubTab='browse';
let clipboardItem=null,clipboardAction=null;
let graphData={cpu:[],ram:[],net:[]};
for(let i=0;i<30;i++){graphData.cpu.push(0);graphData.ram.push(0);graphData.net.push(0)}
let pluginFilter='all',pluginSearch='',settingsSearch='',settingsSubTab='server';
let serverProps={};
let panelConfig={serverAddress:'',accentColor:'#00ff88',bgColor:'#0a0a0a',textSize:'14'};
let currentFiles=[];
let selectedInstallVer=null;

// ─── WEBSOCKET CONSOLE ─────────────────────────────────────────────────────
const ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws');
ws.onopen=()=>{updateConnStatus(true)};
ws.onclose=()=>{updateConnStatus(false);setTimeout(()=>location.reload(),5000)};
ws.onmessage=e=>{
  if(currentTab==='console'){
    const el=document.getElementById('console-scroll');
    if(el){addLineEl(el,e.data);const out=document.getElementById('console-out');if(out)out.scrollTop=99999;}
  }
};

function updateConnStatus(on){
  serverRunning=on;
  const dot=document.getElementById('sb-dot');
  const txt=document.getElementById('sb-status-txt');
  const mdot=document.getElementById('m-dot');
  if(dot){dot.style.background=on?'var(--g)':'var(--r)';dot.style.boxShadow=on?'0 0 8px var(--g)':'0 0 8px var(--r)'}
  if(txt){txt.textContent=on?'Online':'Offline';txt.style.color=on?'var(--g)':'var(--r)'}
  if(mdot){mdot.style.background=on?'var(--g)':'var(--r)';mdot.style.boxShadow=on?'0 0 8px var(--g)':'0 0 8px var(--r)'}
}

// ─── NAV ──────────────────────────────────────────────────────────────────
function renderNav(){
  document.getElementById('nav').innerHTML=tabs.map(t=>`<div class="nav-item${t.id===currentTab?' on':''}" onclick="switchTab('${t.id}')"><i class="fa-solid ${t.icon}"></i>${t.label}</div>`).join('');
}

function switchTab(id){
  currentTab=id;renderNav();
  const c=document.getElementById('content');
  const r={server:renderServer,console:renderConsole,files:renderFiles,plugins:renderPlugins,software:renderSoftware,settings:renderSettings,profile:renderProfile};
  c.innerHTML=`<div class="tab on">${(r[id]||renderProfile)()}</div>`;
  c.scrollTop=0; // FIX: always reset scroll on tab switch
  if(id==='console')initConsole();
  if(id==='server'){initGraphs();fetchServerStatus();}
  if(id==='files')fetchFiles(currentPath);
  if(id==='plugins'&&pluginSubTab==='installed')loadInstalledPlugins();
  if(id==='software')initSoftware();
  if(id==='settings'&&settingsSubTab==='server')fetchServerProps();
  updatePasteBtn();closeSb();hideCtx();
}

// ─── UTILS ─────────────────────────────────────────────────────────────────
function circle(pct){const off=283*(1-pct/100);return`<svg viewBox="0 0 100 100"><circle class="gauge-bg" cx="50" cy="50" r="45"/><circle class="gauge-fill" cx="50" cy="50" r="45" style="--offset:${off};stroke-dashoffset:${off}"/></svg>`}

function escHtml(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}

function fileIcon(name,type){
  if(type==='folder')return'<i class="fa-solid fa-folder" style="color:#ffa502"></i>';
  const ext=name.split('.').pop().toLowerCase();
  const m={jar:'<i class="fa-solid fa-coffee" style="color:#e67e22"></i>',yml:'<i class="fa-solid fa-file-code" style="color:#5b9aff"></i>',yaml:'<i class="fa-solid fa-file-code" style="color:#5b9aff"></i>',properties:'<i class="fa-solid fa-file-lines" style="color:#a29bfe"></i>',json:'<i class="fa-solid fa-file-code" style="color:#ffd43b"></i>',txt:'<i class="fa-solid fa-file-lines" style="color:#888"></i>',log:'<i class="fa-solid fa-file-lines" style="color:#888"></i>',gz:'<i class="fa-solid fa-file-zipper" style="color:#e17055"></i>',png:'<i class="fa-solid fa-file-image" style="color:#00b894"></i>',jpg:'<i class="fa-solid fa-file-image" style="color:#00b894"></i>',jpeg:'<i class="fa-solid fa-file-image" style="color:#00b894"></i>'};
  return m[ext]||'<i class="fa-solid fa-file" style="color:#636e72"></i>';
}
function isImage(n){return/\.(png|jpg|jpeg|gif|bmp|svg|webp)$/i.test(n)}
function isEditable(n){return/\.(txt|yml|yaml|properties|json|cfg|conf|log|xml|toml|ini|md|sh)$/i.test(n)}
function fmtSize(bytes){if(!bytes||bytes<0)return'-';if(bytes<1024)return bytes+'B';if(bytes<1048576)return(bytes/1024).toFixed(1)+' KB';return(bytes/1048576).toFixed(1)+' MB'}
function fmtDate(ts){if(!ts)return'-';const d=new Date(ts*1000);return d.toLocaleDateString('en',{month:'short',day:'numeric',year:'numeric'})}
function formatNum(n){if(n>=1e6)return(n/1e6).toFixed(1)+'M';if(n>=1e3)return(n/1e3).toFixed(0)+'K';return n}

// ─── DASHBOARD ─────────────────────────────────────────────────────────────
function renderServer(){
  return`<div class="tab-head"><div class="tab-title">Dashboard</div><span class="badge" id="srv-badge" style="background:rgba(85,85,85,.2);color:var(--t3)"><i class="fa-solid fa-circle" style="font-size:7px"></i> Loading</span></div>
<div class="grid3" id="gauge-grid">
<div class="card gauge-card">${circle(0)}<div class="gauge-val" id="g-cpu">0%</div><div class="gauge-label">CPU Usage</div><div class="gauge-sub" id="g-cpu-sub">—</div></div>
<div class="card gauge-card">${circle(0)}<div class="gauge-val" id="g-ram">0%</div><div class="gauge-label">Memory</div><div class="gauge-sub" id="g-ram-sub">—</div></div>
<div class="card gauge-card">${circle(0)}<div class="gauge-val" id="g-disk">0%</div><div class="gauge-label">Storage</div><div class="gauge-sub" id="g-disk-sub">—</div></div>
</div>
<div class="info-grid">
<div class="card info-card"><div class="ic-label">Uptime</div><div class="ic-val" id="inf-uptime">—</div></div>
<div class="card info-card"><div class="ic-label">TPS</div><div class="ic-val green" id="inf-tps">—</div></div>
<div class="card info-card"><div class="ic-label">Players</div><div class="ic-val" id="inf-players">—</div></div>
<div class="card info-card"><div class="ic-label">Address</div><div class="ic-val" id="inf-addr" style="font-size:11px">—</div></div>
</div>
<div class="graph-section"><h3><i class="fa-solid fa-chart-line" style="color:var(--g);font-size:13px"></i>Live Performance</h3>
<div class="graph-row">
<div class="card graph-card"><div class="g-head"><span class="g-title">CPU</span><span class="g-val" id="gc-cpu-lbl">0%</span></div><canvas id="gc-cpu" height="60"></canvas></div>
<div class="card graph-card"><div class="g-head"><span class="g-title">Memory</span><span class="g-val" id="gc-ram-lbl">0 MB</span></div><canvas id="gc-ram" height="60"></canvas></div>
<div class="card graph-card"><div class="g-head"><span class="g-title">Disk</span><span class="g-val" id="gc-disk-lbl">0 GB</span></div><canvas id="gc-net" height="60"></canvas></div>
</div></div>
<div style="margin-top:16px"><div class="card"><h3 style="font-size:14px;font-weight:600;display:flex;align-items:center;gap:8px;margin-bottom:14px"><i class="fa-solid fa-power-off" style="color:var(--g);font-size:13px"></i>Server Control</h3>
<div style="display:flex;gap:10px;flex-wrap:wrap">
<button class="btn btn-p" id="btn-start" onclick="controlServer('start')"><i class="fa-solid fa-play"></i>Start</button>
<button class="btn btn-r" id="btn-stop" onclick="controlServer('stop')"><i class="fa-solid fa-stop"></i>Stop</button>
<button class="btn btn-y" onclick="controlServer('restart')"><i class="fa-solid fa-rotate-right"></i>Restart</button>
</div></div></div>`;
}

async function fetchServerStatus(){
  try{
    const r=await fetch('/api/server/status');const d=await r.json();
    const badge=document.getElementById('srv-badge');
    if(badge){badge.innerHTML=`<i class="fa-solid fa-circle" style="font-size:7px"></i> ${d.running?'Online':'Offline'}`;badge.className='badge '+(d.running?'badge-green':'badge-red')}
    setEl('g-cpu',d.cpu_pct+'%');setEl('g-ram',d.ram_pct+'%');setEl('g-disk',d.disk_pct+'%');
    setEl('g-cpu-sub',d.cpu_sub||'—');setEl('g-ram-sub',d.ram_sub||'—');setEl('g-disk-sub',d.disk_sub||'—');
    setEl('inf-uptime',d.uptime||'—');setEl('inf-tps',d.tps||'—');setEl('inf-players',d.players||'—');
    setEl('inf-addr',panelConfig.serverAddress||d.address||'Not configured');
    graphData.cpu.push(parseFloat(d.cpu_pct)||0);graphData.cpu.shift();
    graphData.ram.push(parseFloat(d.ram_pct)||0);graphData.ram.shift();
    graphData.net.push(parseFloat(d.disk_pct)||0);graphData.net.shift();
    drawGraph('gc-cpu',graphData.cpu,'#00ff88');drawGraph('gc-ram',graphData.ram,'#5b9aff');drawGraph('gc-net',graphData.net,'#ffa502');
    setEl('gc-cpu-lbl',d.cpu_pct+'%');setEl('gc-ram-lbl',d.ram_sub||'—');setEl('gc-disk-lbl',d.disk_sub||'—');
    serverRunning=d.running;updateConnStatus(d.running);
  }catch(e){}
}

function setEl(id,val){const e=document.getElementById(id);if(e)e.textContent=val}

function drawGraph(id,data,color){
  const c=document.getElementById(id);if(!c)return;
  const ctx=c.getContext('2d');const dpr=window.devicePixelRatio||1;
  c.width=c.offsetWidth*dpr;c.height=c.offsetHeight*dpr;ctx.scale(dpr,dpr);
  const w=c.offsetWidth,h=c.offsetHeight,max=Math.max(...data)*1.2||1;
  ctx.clearRect(0,0,w,h);
  const grad=ctx.createLinearGradient(0,0,0,h);grad.addColorStop(0,color+'44');grad.addColorStop(1,color+'05');
  ctx.beginPath();ctx.moveTo(0,h);
  data.forEach((v,i)=>{const x=(i/(data.length-1))*w;const y=h-(v/max)*h*.85;i===0?ctx.lineTo(x,y):ctx.lineTo(x,y)});
  ctx.lineTo(w,h);ctx.closePath();ctx.fillStyle=grad;ctx.fill();
  ctx.beginPath();
  data.forEach((v,i)=>{const x=(i/(data.length-1))*w;const y=h-(v/max)*h*.85;i===0?ctx.moveTo(x,y):ctx.lineTo(x,y)});
  ctx.strokeStyle=color;ctx.lineWidth=1.5;ctx.stroke();
}

function initGraphs(){
  setTimeout(()=>{
    drawGraph('gc-cpu',graphData.cpu,'#00ff88');
    drawGraph('gc-ram',graphData.ram,'#5b9aff');
    drawGraph('gc-net',graphData.net,'#ffa502');
  },50);
  setInterval(()=>{if(currentTab==='server')fetchServerStatus()},15000);
}

async function controlServer(action){
  try{
    const r=await fetch(`/api/server/${action}`,{method:'POST'});
    if(r.ok){toast(action==='start'?'Starting server...':action==='stop'?'Stopping server...':'Restarting...','success');}
    else toast('Action failed','error');
    setTimeout(fetchServerStatus,2000);
  }catch(e){toast('Request failed','error')}
}

// ─── CONSOLE ──────────────────────────────────────────────────────────────
function renderConsole(){
  return`<div class="tab-head"><div class="tab-title">Console</div></div>
<div class="console-wrap">
<div class="console-controls">
<button class="btn btn-r btn-s" onclick="controlServer('stop')"><i class="fa-solid fa-stop"></i>Stop</button>
<button class="btn btn-y btn-s" onclick="controlServer('restart')"><i class="fa-solid fa-rotate-right"></i>Restart</button>
<div style="flex:1"></div>
<button class="btn btn-g btn-s" onclick="clearConsole()"><i class="fa-solid fa-trash"></i>Clear</button>
</div>
<div class="console-output" id="console-out"><div class="console-scroll" id="console-scroll"></div></div>
<div class="console-input"><input type="text" id="cmd-input" placeholder="Enter command..." onkeydown="if(event.key==='Enter')sendCmd()"><button class="btn btn-p btn-s" onclick="sendCmd()"><i class="fa-solid fa-paper-plane"></i></button></div>
</div>`;
}

function initConsole(){
  const el=document.getElementById('console-scroll');if(!el)return;
  el.innerHTML='';
  // Request history replay
  fetch('/api/console/history').then(r=>r.json()).then(lines=>{
    lines.forEach(l=>addLineEl(el,l));
    const out=document.getElementById('console-out');if(out)out.scrollTop=99999;
  }).catch(()=>{});
}

function addLineEl(container,text){
  const d=document.createElement('div');d.className='c-line';
  let cls='c-info';
  if(text.includes('WARN'))cls='c-warn';
  else if(text.includes('ERROR')||text.includes('SEVERE'))cls='c-error';
  else if(text.includes('Done')||text.includes('started'))cls='c-green';
  const m=text.match(/^\[[\d:]+/);
  if(m){d.innerHTML=`<span class="c-time">${escHtml(m[0])}</span><span class="${cls}">${escHtml(text.slice(m[0].length))}</span>`}
  else d.innerHTML=`<span class="${cls}">${escHtml(text)}</span>`;
  container.appendChild(d);
  if(container.children.length>500)container.removeChild(container.firstChild);
}

function addLine(text){
  const el=document.getElementById('console-scroll');if(!el)return;
  addLineEl(el,text);
  const out=document.getElementById('console-out');if(out)out.scrollTop=99999;
}

function sendCmd(){
  const inp=document.getElementById('cmd-input');if(!inp||!inp.value.trim())return;
  const cmd=inp.value.trim();inp.value='';
  if(ws.readyState===1){ws.send(cmd);}
  else toast('Not connected to server','error');
}

function clearConsole(){const el=document.getElementById('console-scroll');if(el)el.innerHTML='';toast('Console cleared','success')}

// ─── FILE MANAGER ─────────────────────────────────────────────────────────
function renderFiles(){
  const pathParts=currentPath.split('/').filter(Boolean);
  let crumbs=`<span class="crumb${currentPath==='/'?' now':''}" onclick="fetchFiles('/')"><i class="fa-solid fa-server" style="font-size:11px"></i></span>`;
  let bp='';pathParts.forEach((p,i)=>{bp+='/'+p;const last=i===pathParts.length-1;
    crumbs+=`<span class="sep"><i class="fa-solid fa-chevron-right"></i></span><span class="crumb${last?' now':''}" ${last?'':`onclick="fetchFiles('${bp}')"`}>${p}</span>`;});
  return`<div class="tab-head"><div class="tab-title">Files</div></div>
<div class="fm-toolbar">
${currentPath!=='/'?`<button class="btn btn-g btn-s" onclick="fetchFiles('${'/'+pathParts.slice(0,-1).join('/')}')"><i class="fa-solid fa-arrow-left"></i></button>`:''}
<div class="breadcrumbs">${crumbs}</div>
<button class="btn btn-g btn-s" onclick="startUpload()"><i class="fa-solid fa-upload"></i></button>
<button class="btn btn-p btn-s" onclick="startCreate()"><i class="fa-solid fa-plus"></i></button>
</div>
<div class="fm-list" id="fm-list-box">
<div class="fm-header"><span>Name</span><span class="h-size">Size</span><span class="h-date">Modified</span><span></span></div>
<div id="fm-body" style="min-height:80px"><div style="text-align:center;padding:30px;color:var(--t3)"><i class="fa-solid fa-spinner spin"></i> Loading...</div></div>
</div>`;
}

async function fetchFiles(path){
  currentPath=path||'/';
  if(currentTab!=='files'){switchTab('files');return}
  // Update breadcrumbs
  const pathParts=currentPath.split('/').filter(Boolean);
  let crumbs=`<span class="crumb${currentPath==='/'?' now':''}" onclick="fetchFiles('/')"><i class="fa-solid fa-server" style="font-size:11px"></i></span>`;
  let bp='';pathParts.forEach((p,i)=>{bp+='/'+p;const last=i===pathParts.length-1;
    crumbs+=`<span class="sep"><i class="fa-solid fa-chevron-right"></i></span><span class="crumb${last?' now':''}" ${last?'':`onclick="fetchFiles('${bp}')"`}>${p}</span>`;});
  const bc=document.querySelector('.breadcrumbs');if(bc)bc.innerHTML=crumbs;
  const back=document.querySelector('.fm-toolbar .btn-g');
  if(back){if(currentPath!=='/')back.style.display='';else back.style.display='none';}
  const body=document.getElementById('fm-body');
  if(!body)return;
  body.innerHTML=`<div style="text-align:center;padding:30px;color:var(--t3)"><i class="fa-solid fa-spinner spin"></i></div>`;
  try{
    const r=await fetch('/api/fs/list?path='+encodeURIComponent(currentPath.replace(/^\//,'')));
    const files=await r.json();currentFiles=files;
    if(!files.length){body.innerHTML=`<div style="padding:40px;text-align:center;color:var(--t3)">Empty directory</div>`;return}
    body.innerHTML=files.map((f,i)=>`<div class="fm-row" ondblclick="${f.is_dir?`fetchFiles('${(currentPath==='/'?'':currentPath)}/${f.name}')`:`openFileEditor('${escHtml(f.name)}')`}">
<div class="fm-name">${fileIcon(f.name,f.is_dir?'folder':'file')}<span>${escHtml(f.name)}</span></div>
<div class="fm-size">${fmtSize(f.size)}</div>
<div class="fm-date">${fmtDate(f.mtime)}</div>
<div class="fm-actions"><button class="fm-dot" onclick="event.stopPropagation();showFileCtx(${i},this)"><i class="fa-solid fa-ellipsis"></i></button></div>
</div>`).join('');
  }catch(e){body.innerHTML=`<div style="padding:40px;text-align:center;color:var(--r)">Failed to load directory</div>`}
}

function showFileCtx(idx,btn){
  const f=currentFiles[idx];if(!f)return;
  const filePath=(currentPath==='/'?'':currentPath)+'/'+f.name;
  const rect=btn.getBoundingClientRect();const menu=document.getElementById('ctx-menu');
  let h='';
  if(f.is_dir)h+=`<div class="ctx-item" onclick="fetchFiles('${(currentPath==='/'?'':currentPath)}/${f.name}');hideCtx()"><i class="fa-solid fa-folder-open"></i>Open</div>`;
  if(isEditable(f.name))h+=`<div class="ctx-item" onclick="openFileEditor('${escHtml(f.name)}');hideCtx()"><i class="fa-solid fa-pen-to-square"></i>Edit</div>`;
  if(isImage(f.name))h+=`<div class="ctx-item" onclick="previewImage('${escHtml(f.name)}');hideCtx()"><i class="fa-solid fa-eye"></i>Preview</div>`;
  h+=`<div class="ctx-item" onclick="showRename('${escHtml(f.name)}');hideCtx()"><i class="fa-solid fa-i-cursor"></i>Rename</div>`;
  h+=`<div class="ctx-item" onclick="downloadFile('${encodeURIComponent(filePath.replace(/^\//,''))}');hideCtx()"><i class="fa-solid fa-download"></i>Download</div>`;
  h+=`<div class="ctx-item" onclick="startMove('${escHtml(f.name)}');hideCtx()"><i class="fa-solid fa-arrow-right-arrow-left"></i>Move</div>`;
  h+=`<div class="ctx-sep"></div>`;
  h+=`<div class="ctx-item danger" onclick="showDelete('${escHtml(f.name)}');hideCtx()"><i class="fa-solid fa-trash"></i>Delete</div>`;
  menu.innerHTML=h;menu.style.display='block';
  const mw=menu.offsetWidth,mh=menu.offsetHeight;
  let x=rect.right-mw,y=rect.bottom+4;
  if(x<8)x=8;if(y+mh>window.innerHeight)y=rect.top-mh-4;
  menu.style.left=x+'px';menu.style.top=y+'px';
  setTimeout(()=>document.addEventListener('click',hideCtx,{once:true}),10);
}

function downloadFile(path){window.open('/api/fs/download?path='+path,'_blank')}

async function openFileEditor(name){
  if(isImage(name)){previewImage(name);return}
  const path=(currentPath==='/'?'':currentPath)+'/'+name;
  showModal({title:`Editing: ${name}`,cls:'editor-modal',body:`<textarea id="editor-area" spellcheck="false">Loading...</textarea>`,foot:`<button class="btn btn-g" onclick="closeModal()">Cancel</button><button class="btn btn-p" onclick="saveFile('${escHtml(path.replace(/^\//,''))}')"><i class="fa-solid fa-save"></i>Save</button>`});
  try{
    const r=await fetch('/api/fs/read?path='+encodeURIComponent(path.replace(/^\//,'')));
    const text=await r.text();
    const ta=document.getElementById('editor-area');if(ta)ta.value=text;
  }catch(e){const ta=document.getElementById('editor-area');if(ta)ta.value='// Failed to load file';}
}

async function saveFile(path){
  const ta=document.getElementById('editor-area');if(!ta)return;
  const fd=new FormData();fd.append('path',path);fd.append('content',ta.value);
  const r=await fetch('/api/fs/write',{method:'POST',body:fd});
  if(r.ok){toast('File saved','success');closeModal();}else toast('Save failed','error');
}

function previewImage(name){
  const path=(currentPath==='/'?'':currentPath)+'/'+name;
  showModal({title:name,body:`<div class="img-preview"><img src="/api/fs/download?path=${encodeURIComponent(path.replace(/^\//,''))}" alt="${escHtml(name)}" onerror="this.src='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%22200%22 height=%22200%22%3E%3Crect width=%22200%22 height=%22200%22 fill=%22%23222%22/%3E%3Ctext x=%2250%25%22 y=%2250%25%22 dominant-baseline=%22middle%22 text-anchor=%22middle%22 fill=%22%23555%22 font-family=%22monospace%22%3ENo preview%3C/text%3E%3C/svg%3E'"></div>`,foot:`<button class="btn btn-g" onclick="closeModal()">Close</button>`});
}

function showRename(name){
  showModal({title:'Rename',body:`<label>New name</label><input type="text" id="rename-input" value="${escHtml(name)}">`,
    foot:`<button class="btn btn-g" onclick="closeModal()">Cancel</button><button class="btn btn-p" onclick="doRename('${escHtml(name)}')">Rename</button>`});
  setTimeout(()=>{const i=document.getElementById('rename-input');if(i){i.focus();i.select()}},100);
}

async function doRename(oldName){
  const inp=document.getElementById('rename-input');if(!inp||!inp.value.trim())return;
  const fd=new FormData();
  fd.append('old_path',(currentPath==='/'?'':currentPath)+'/'+oldName);
  fd.append('new_path',(currentPath==='/'?'':currentPath)+'/'+inp.value.trim());
  const r=await fetch('/api/fs/rename',{method:'POST',body:fd});
  if(r.ok){toast('Renamed','success');closeModal();fetchFiles(currentPath);}else toast('Rename failed','error');
}

function showDelete(name){
  const path=(currentPath==='/'?'':currentPath)+'/'+name;
  showModal({title:'Delete',body:`<div class="warn-icon"><i class="fa-solid fa-triangle-exclamation"></i></div><div class="warn-text">Delete "${escHtml(name)}"?</div><div class="warn-sub">This cannot be undone.</div>`,
    foot:`<button class="btn btn-g" onclick="closeModal()">Cancel</button><button class="btn btn-r" onclick="doDelete('${escHtml(path.replace(/^\//,''))}')">Delete</button>`});
}

async function doDelete(path){
  const fd=new FormData();fd.append('path',path);
  const r=await fetch('/api/fs/delete',{method:'POST',body:fd});
  if(r.ok){toast('Deleted','success');closeModal();fetchFiles(currentPath);}else toast('Delete failed','error');
}

function startUpload(){
  showModal({title:'Upload Files',body:`<div class="upload-zone" id="drop-zone" onclick="document.getElementById('file-up-inp').click()" ondragover="event.preventDefault();this.classList.add('drag')" ondragleave="this.classList.remove('drag')" ondrop="handleDrop(event)"><i class="fa-solid fa-cloud-arrow-up"></i><div>Drop files or click to browse</div><div style="font-size:11px;margin-top:6px;color:var(--t3)">Uploading to: ${escHtml(currentPath)}</div></div><input type="file" id="file-up-inp" style="display:none" onchange="doUpload(this.files)" multiple>`,
    foot:`<button class="btn btn-g" onclick="closeModal()">Cancel</button>`});
}

async function handleDrop(e){
  e.preventDefault();document.getElementById('drop-zone').classList.remove('drag');
  await doUpload(e.dataTransfer.files);
}

async function doUpload(files){
  if(!files||!files.length)return;
  closeModal();
  for(const file of files){
    toast(`Uploading ${file.name}...`,'success');
    const fd=new FormData();fd.append('path',currentPath.replace(/^\//,''));fd.append('file',file);
    const r=await fetch('/api/fs/upload',{method:'POST',body:fd});
    if(r.ok)toast(`Uploaded ${file.name}`,'success');else toast(`Failed: ${file.name}`,'error');
  }
  fetchFiles(currentPath);
}

function startCreate(){
  let createType='file';
  showModal({title:'Create New',body:`<div style="display:flex;gap:8px;margin-bottom:14px">
<button class="btn btn-g" style="flex:1;border-color:var(--g);color:var(--g)" id="cb-file" onclick="createType='file';document.getElementById('cb-file').style.borderColor='var(--g)';document.getElementById('cb-dir').style.borderColor='var(--brd)'"><i class="fa-solid fa-file"></i>File</button>
<button class="btn btn-g" style="flex:1" id="cb-dir" onclick="createType='folder';document.getElementById('cb-dir').style.borderColor='var(--g)';document.getElementById('cb-file').style.borderColor='var(--brd)'"><i class="fa-solid fa-folder"></i>Folder</button>
</div><label>Name</label><input type="text" id="create-name" placeholder="Enter name..." autofocus>`,
  foot:`<button class="btn btn-g" onclick="closeModal()">Cancel</button><button class="btn btn-p" onclick="doCreate()">Create</button>`});
}

async function doCreate(){
  const name=document.getElementById('create-name')?.value?.trim();if(!name)return;
  const fd=new FormData();
  const isDir=document.getElementById('cb-dir')?.style.borderColor==='var(--g)';
  fd.append('path',(currentPath==='/'?'':currentPath)+'/'+name);
  fd.append('is_dir',isDir?'1':'0');
  const r=await fetch('/api/fs/create',{method:'POST',body:fd});
  if(r.ok){toast('Created '+name,'success');closeModal();fetchFiles(currentPath);}else toast('Create failed','error');
}

function startMove(name){clipboardItem={name,from:currentPath};clipboardAction='move';updatePasteBtn();toast(`Navigate to destination and paste`,'success')}

async function doPaste(){
  if(clipboardAction==='move'&&clipboardItem){
    const fd=new FormData();
    fd.append('old_path',(clipboardItem.from==='/'?'':clipboardItem.from)+'/'+clipboardItem.name);
    fd.append('new_path',(currentPath==='/'?'':currentPath)+'/'+clipboardItem.name);
    const r=await fetch('/api/fs/rename',{method:'POST',body:fd});
    if(r.ok)toast(`Moved "${clipboardItem.name}" to ${currentPath}`,'success');else toast('Move failed','error');
  }
  cancelClip();fetchFiles(currentPath);
}

function cancelClip(){clipboardItem=null;clipboardAction=null;updatePasteBtn()}
function updatePasteBtn(){
  const c=document.getElementById('paste-container');
  if(clipboardAction==='move'&&clipboardItem){
    c.innerHTML=`<button class="paste-btn" onclick="doPaste()"><i class="fa-solid fa-paste"></i>Paste "${clipboardItem.name}" here<span class="paste-cancel" onclick="event.stopPropagation();cancelClip()"><i class="fa-solid fa-xmark"></i></span></button>`;
  }else c.innerHTML='';
}

// ─── PLUGINS ──────────────────────────────────────────────────────────────
function renderPlugins(){
  return`<div class="tab-head"><div class="tab-title">Plugins</div></div>
<div class="sub-tabs"><div class="sub-tab${pluginSubTab==='browse'?' on':''}" onclick="pluginSubTab='browse';switchTab('plugins')">Browse</div><div class="sub-tab${pluginSubTab==='installed'?' on':''}" onclick="pluginSubTab='installed';switchTab('plugins')">Installed</div></div>
${pluginSubTab==='browse'?renderPluginBrowse():renderPluginInstalled()}`;
}

function renderPluginBrowse(){
  const loaders=['all','paper','spigot','purpur','fabric','velocity'];
  return`<div style="display:flex;gap:10px;margin-bottom:12px;flex-wrap:wrap">
<div class="search-box" style="flex:1;min-width:200px;margin-bottom:0"><i class="fa-solid fa-search"></i><input type="text" id="pl-search" placeholder="Search plugins on Modrinth..." value="${escHtml(pluginSearch)}" onkeydown="if(event.key==='Enter')searchModrinth()"></div>
<button class="btn btn-p btn-s" onclick="searchModrinth()"><i class="fa-solid fa-search"></i>Search</button>
</div>
<div class="filter-row">${loaders.map(l=>`<button class="filter-btn${pluginFilter===l?' on':''}" onclick="setPluginFilter('${l}')">${l==='all'?'All Loaders':l.charAt(0).toUpperCase()+l.slice(1)}</button>`).join('')}</div>
<div class="plugin-grid" id="plugin-grid"><div style="grid-column:1/-1;text-align:center;padding:60px;color:var(--t3)"><i class="fa-solid fa-puzzle-piece" style="font-size:32px;margin-bottom:12px;display:block;opacity:.3"></i>Search for plugins above</div></div>`;
}

function renderPluginInstalled(){
  return`<div class="inst-grid" id="inst-grid"><div style="text-align:center;padding:40px;color:var(--t3)"><i class="fa-solid fa-spinner spin"></i></div></div>`;
}

function setPluginFilter(f){
  pluginFilter=f;
  if(document.getElementById('plugin-grid'))switchTab('plugins');
}

async function searchModrinth(){
  const q=document.getElementById('pl-search')?.value?.trim();
  if(!q){toast('Enter a search term','error');return}
  pluginSearch=q;
  const grid=document.getElementById('plugin-grid');if(!grid)return;
  grid.innerHTML=`<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--t3)"><i class="fa-solid fa-spinner spin" style="font-size:20px"></i></div>`;
  try{
    let facets=`[["project_type:plugin"]]`;
    if(pluginFilter!=='all')facets=`[["project_type:plugin"],["categories:${pluginFilter}"]]`;
    const r=await fetch(`https://api.modrinth.com/v2/search?query=${encodeURIComponent(q)}&facets=${encodeURIComponent(facets)}&limit=24`);
    const data=await r.json();
    if(!data.hits||!data.hits.length){grid.innerHTML=`<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--t3)">No results found</div>`;return}
    grid.innerHTML=data.hits.map(p=>`<div class="card pg-card">
<div class="pg-top">
<div class="pg-icon"><img src="${p.icon_url||'https://cdn.modrinth.com/assets/unknown_icon.png'}" alt="${escHtml(p.title)}" onerror="this.parentElement.innerHTML='<i class=\'fa-solid fa-puzzle-piece\'></i>'"></div>
<div class="pg-info"><div class="pg-name">${escHtml(p.title)}</div><div class="pg-author">by ${escHtml(p.author)}</div></div>
</div>
<div class="pg-desc">${escHtml(p.description)}</div>
<div class="pg-bottom">
<div class="pg-meta"><span><i class="fa-solid fa-download"></i>${formatNum(p.downloads)}</span><span><i class="fa-solid fa-tag"></i>${escHtml(p.latest_version||'—')}</span></div>
<button class="btn btn-p btn-s" id="install-btn-${p.project_id}" onclick="showInstallModal('${p.project_id}','${escHtml(p.title).replace(/'/g,'\\\'')}')" ><i class="fa-solid fa-download"></i></button>
</div></div>`).join('');
  }catch(e){grid.innerHTML=`<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--r)">Failed to reach Modrinth API</div>`}
}

async function showInstallModal(projectId,name){
  showModal({title:`Install: ${name}`,body:`<div id="install-modal-body"><div style="text-align:center;padding:20px;color:var(--t3)"><i class="fa-solid fa-spinner spin" style="font-size:20px"></i><div style="margin-top:10px">Fetching versions...</div></div></div>`,
    foot:`<button class="btn btn-g" onclick="closeModal()">Cancel</button><button class="btn btn-p" id="confirm-install-btn" disabled onclick="confirmInstall('${projectId}','${escHtml(name).replace(/'/g,'\\\'')}')" ><i class="fa-solid fa-download"></i>Install Selected</button>`});
  selectedInstallVer=null;
  try{
    const r=await fetch(`https://api.modrinth.com/v2/project/${projectId}/version`);
    const versions=await r.json();
    if(!versions.length){document.getElementById('install-modal-body').innerHTML=`<p style="color:var(--r);text-align:center">No versions available</p>`;return}
    const html=`<div style="font-size:12px;color:var(--t2);margin-bottom:12px">Select a version to install:</div>
<div style="max-height:320px;overflow-y:auto;display:flex;flex-direction:column;gap:4px">${versions.slice(0,30).map(v=>{
  const file=v.files.find(f=>f.primary)||v.files[0];
  const loaders=v.loaders.join(', ');
  const mcvers=(v.game_versions||[]).slice(-3).join(', ')+(v.game_versions&&v.game_versions.length>3?` +${v.game_versions.length-3}`:'');
  return`<div class="ver-option" onclick="selectVersion('${v.id}','${file?.url||''}','${escHtml(file?.filename||'')}','${escHtml(v.version_number)}')">
<div class="ver-option-left"><div class="ver-option-num">${escHtml(v.version_number)}</div><div class="ver-option-meta">${escHtml(loaders)} • ${escHtml(mcvers)}</div></div>
<div style="font-size:10px;padding:2px 8px;border-radius:4px;background:${v.version_type==='release'?'rgba(0,255,136,.12)':v.version_type==='beta'?'rgba(255,165,2,.12)':'rgba(255,71,87,.12)'};color:${v.version_type==='release'?'var(--g)':v.version_type==='beta'?'var(--y)':'var(--r)'}">${v.version_type}</div>
</div>`;}).join('')}</div>`;
    document.getElementById('install-modal-body').innerHTML=html;
  }catch(e){document.getElementById('install-modal-body').innerHTML=`<p style="color:var(--r);text-align:center">Failed to fetch versions</p>`}
}

function selectVersion(versionId,url,filename,num){
  selectedInstallVer={versionId,url,filename,num};
  document.querySelectorAll('.ver-option').forEach(el=>el.classList.remove('selected'));
  event.currentTarget.classList.add('selected');
  const btn=document.getElementById('confirm-install-btn');if(btn)btn.disabled=false;
}

async function confirmInstall(projectId,name){
  if(!selectedInstallVer){toast('Select a version first','error');return}
  const btn=document.getElementById('confirm-install-btn');if(btn){btn.disabled=true;btn.innerHTML='<i class="fa-solid fa-spinner spin"></i> Installing...';}
  const fd=new FormData();
  fd.append('url',selectedInstallVer.url);
  fd.append('filename',selectedInstallVer.filename);
  fd.append('project_id',projectId);
  fd.append('version_id',selectedInstallVer.versionId);
  fd.append('name',name);
  try{
    const r=await fetch('/api/plugins/install',{method:'POST',body:fd});
    if(r.ok){toast(`Installed ${name}`,'success');closeModal();const ibtn=document.getElementById(`install-btn-${projectId}`);if(ibtn){ibtn.className='btn btn-g btn-s';ibtn.innerHTML='<i class="fa-solid fa-check"></i>';ibtn.disabled=true;}}
    else{const err=await r.text();toast('Install failed: '+err,'error');if(btn){btn.disabled=false;btn.innerHTML='<i class="fa-solid fa-download"></i> Install Selected';}}
  }catch(e){toast('Network error','error')}
}

async function loadInstalledPlugins(){
  const grid=document.getElementById('inst-grid');if(!grid)return;
  grid.innerHTML=`<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--t3)"><i class="fa-solid fa-spinner spin"></i></div>`;
  try{
    const r=await fetch('/api/fs/read?path=plugins/plugins.json');
    if(!r.ok)throw new Error();
    const data=await r.json();
    const entries=Object.entries(data);
    if(!entries.length){grid.innerHTML=`<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--t3)">No plugins installed via panel</div>`;return}
    // Fetch project info for icons
    const cards=await Promise.all(entries.map(async([pid,info])=>{
      let iconUrl='';
      try{const pr=await fetch(`https://api.modrinth.com/v2/project/${pid}`);const pd=await pr.json();iconUrl=pd.icon_url||'';}catch(e){}
      return{pid,info,iconUrl};
    }));
    grid.innerHTML=cards.map(({pid,info,iconUrl})=>`<div class="card inst-card">
<div class="inst-top">
<div class="inst-icon">${iconUrl?`<img src="${iconUrl}" alt="${escHtml(info.name)}" onerror="this.parentElement.innerHTML='<i class=\'fa-solid fa-puzzle-piece\'></i>'">`:'<i class="fa-solid fa-puzzle-piece"></i>'}</div>
<div class="inst-info"><div class="inst-name">${escHtml(info.name)}</div><div class="inst-ver">v${escHtml(info.version_id||'?')} • ${escHtml(info.filename||'')}</div></div>
</div>
<div class="inst-bottom">
<div style="font-size:11px;color:var(--t3)">${info.installed_at?new Date(info.installed_at*1000).toLocaleDateString():''}</div>
<div class="inst-btns"><button class="btn btn-r btn-s" onclick="showDelete('plugins/${escHtml(info.filename)}')"><i class="fa-solid fa-trash"></i></button></div>
</div></div>`).join('');
  }catch(e){grid.innerHTML=`<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--t3)">No plugins record found</div>`}
}

// ─── SOFTWARE ─────────────────────────────────────────────────────────────
const SOFTWARE_DEFS=[
  {id:'paper',name:'PaperMC',icon:'📄',desc:'High performance fork of Spigot with patches, optimizations, and extra APIs.',color:'#00ff88'},
  {id:'purpur',name:'Purpur',icon:'🟣',desc:'Drop-in replacement for Paper with extra features and configuration options.',color:'#a855f7'},
  {id:'fabric',name:'Fabric',icon:'🧵',desc:'Lightweight, modular modding toolchain for Minecraft.',color:'#f59e0b'},
  {id:'vanilla',name:'Vanilla',icon:'🟢',desc:'Official Mojang Minecraft server software, unmodified.',color:'#22c55e'},
  {id:'spigot',name:'Spigot',icon:'🔶',desc:'Modified Minecraft server with Bukkit plugin API and optimizations.',color:'#f97316'}
];
let swVersions={};
let activeJar=null;

function renderSoftware(){
  return`<div class="tab-head"><div class="tab-title">Software</div></div>
<div class="sub-tabs">
<div class="sub-tab${softwareSubTab==='browse'?' on':''}" onclick="softwareSubTab='browse';switchTab('software')">Available</div>
<div class="sub-tab${softwareSubTab==='current'?' on':''}" onclick="softwareSubTab='current';switchTab('software')">Current</div>
</div>
${softwareSubTab==='browse'?renderSwBrowse():renderSwCurrent()}`;
}

function renderSwBrowse(){
  return`<div class="sw-grid" id="sw-grid">${SOFTWARE_DEFS.map(s=>`<div class="card sw-card">
<div class="sw-icon">${s.icon}</div>
<div class="sw-name">${s.name}</div>
<div class="sw-desc">${s.desc}</div>
<div class="sw-ver-list" id="sw-vers-${s.id}"><div class="sw-loader"><div class="sw-spinner"></div></div></div>
</div>`).join('')}</div>`;
}

function renderSwCurrent(){
  if(!activeJar)return`<div class="coming-soon" style="height:40vh"><i class="fa-solid fa-box-open"></i><h2>No Software Detected</h2><p style="font-size:12px">No server jar found in /app</p></div>`;
  return`<div class="card" style="text-align:center;padding:30px;max-width:400px;margin:0 auto">
<div class="sw-icon" style="margin-bottom:12px">📦</div>
<div class="sw-name" style="font-size:18px">${escHtml(activeJar)}</div>
<div style="font-size:12px;color:var(--t3);margin-top:8px;margin-bottom:16px">Active server jar</div>
<div style="display:flex;gap:8px;justify-content:center">
<button class="btn btn-g btn-s" onclick="toast('No update check available in demo','warn')"><i class="fa-solid fa-rotate"></i>Check Update</button>
</div></div>`;
}

async function initSoftware(){
  const r=await fetch('/api/server/status').catch(()=>null);
  if(r){const d=await r.json().catch(()=>{});activeJar=d.active_jar||null;}
  if(softwareSubTab==='browse')fetchAllSoftwareVersions();
}

async function fetchAllSoftwareVersions(){
  SOFTWARE_DEFS.forEach(s=>fetchSoftwareVersions(s.id));
}

async function fetchSoftwareVersions(id){
  const el=document.getElementById(`sw-vers-${id}`);if(!el)return;
  try{
    let versions=[];
    if(id==='paper'){
      const r=await fetch('https://api.papermc.io/v2/projects/paper');
      const d=await r.json();versions=[...d.versions].reverse().slice(0,12);
    }else if(id==='purpur'){
      const r=await fetch('https://api.purpurmc.org/v2/purpur');
      const d=await r.json();versions=[...d.versions].reverse().slice(0,12);
    }else if(id==='fabric'){
      const r=await fetch('https://meta.fabricmc.net/v2/versions/game');
      const d=await r.json();versions=d.filter(v=>v.stable).slice(0,12).map(v=>v.version);
    }else if(id==='vanilla'){
      const r=await fetch('https://launchermeta.mojang.com/mc/game/version_manifest.json');
      const d=await r.json();versions=d.versions.filter(v=>v.type==='release').slice(0,12).map(v=>v.id);
    }else if(id==='spigot'){
      versions=['1.20.4','1.20.3','1.20.2','1.20.1','1.19.4','1.19.3','1.19.2','1.18.2','1.17.1','1.16.5'];
    }
    swVersions[id]=versions;
    const isActive=(v)=>activeJar&&activeJar.toLowerCase().includes(v);
    el.innerHTML=versions.map(v=>`<div class="sw-ver${isActive(v)?' active':''}" onclick="showSwInstall('${id}','${v}')">
<span>${v}</span>${isActive(v)?'<span class="sv-tag">Active</span>':''}
</div>`).join('')+(versions.length===0?`<div style="font-size:11px;color:var(--t3);text-align:center;padding:8px">Unable to fetch versions</div>`:'');
  }catch(e){
    el.innerHTML=`<div style="font-size:11px;color:var(--t3);text-align:center;padding:8px">Failed to load versions</div>`;
  }
}

function showSwInstall(type,version){
  const sw=SOFTWARE_DEFS.find(s=>s.id===type);
  showModal({title:`Install ${sw.name} ${version}`,
    body:`<div style="text-align:center;padding:8px 0">
<div style="font-size:36px;margin-bottom:10px">${sw.icon}</div>
<div style="font-size:16px;font-weight:600;margin-bottom:4px">${sw.name} ${version}</div>
<div style="font-size:12px;color:var(--t2);margin-bottom:16px">${sw.desc}</div>
<div class="warn-sub" style="margin-bottom:0">This will download and replace your current server jar. A restart is required.</div>
</div>`,
    foot:`<button class="btn btn-g" onclick="closeModal()">Cancel</button>
<button class="btn btn-p" id="sw-install-btn" onclick="doSoftwareInstall('${type}','${version}')"><i class="fa-solid fa-download"></i>Download & Install</button>`});
}

async function doSoftwareInstall(type,version){
  const btn=document.getElementById('sw-install-btn');if(btn){btn.disabled=true;btn.innerHTML='<i class="fa-solid fa-spinner spin"></i> Downloading...';}
  const fd=new FormData();fd.append('type',type);fd.append('version',version);
  const r=await fetch('/api/software/install',{method:'POST',body:fd});
  if(r.ok){toast(`Installed ${type} ${version}. Restart to apply.`,'success');closeModal();}
  else{const err=await r.text();toast('Install failed: '+err,'error');if(btn){btn.disabled=false;btn.innerHTML='<i class="fa-solid fa-download"></i> Download & Install';}}
}

// ─── SETTINGS ─────────────────────────────────────────────────────────────
const PROP_GROUPS=[
  {group:'Network',icon:'fa-network-wired',props:[
    {key:'server-port',type:'number',desc:'Server port number'},
    {key:'server-ip',type:'text',desc:'Server IP binding address'},
    {key:'online-mode',type:'bool',desc:'Authenticate with Mojang'},
    {key:'network-compression-threshold',type:'number',desc:'Compression threshold'},
    {key:'enable-query',type:'bool',desc:'Enable GameSpy4 protocol'}
  ]},{group:'Gameplay',icon:'fa-gamepad',props:[
    {key:'gamemode',type:'select',options:['survival','creative','adventure','spectator'],desc:'Default game mode'},
    {key:'difficulty',type:'select',options:['peaceful','easy','normal','hard'],desc:'Server difficulty'},
    {key:'pvp',type:'bool',desc:'Enable player combat'},
    {key:'max-players',type:'number',desc:'Maximum players'},
    {key:'spawn-protection',type:'number',desc:'Spawn protection radius'},
    {key:'allow-flight',type:'bool',desc:'Allow flight'},
    {key:'hardcore',type:'bool',desc:'Enable hardcore mode'},
    {key:'force-gamemode',type:'bool',desc:'Force gamemode on join'}
  ]},{group:'World',icon:'fa-globe',props:[
    {key:'level-name',type:'text',desc:'World folder name'},
    {key:'level-seed',type:'text',desc:'World seed'},
    {key:'level-type',type:'select',options:['minecraft:normal','minecraft:flat','minecraft:large_biomes','minecraft:amplified'],desc:'World type'},
    {key:'generate-structures',type:'bool',desc:'Generate structures'},
    {key:'max-world-size',type:'number',desc:'Max world radius'},
    {key:'spawn-animals',type:'bool',desc:'Spawn animals'},
    {key:'spawn-monsters',type:'bool',desc:'Spawn monsters'},
    {key:'spawn-npcs',type:'bool',desc:'Spawn villagers'}
  ]},{group:'General',icon:'fa-cog',props:[
    {key:'motd',type:'text',desc:'Server list message'},
    {key:'enable-command-block',type:'bool',desc:'Enable command blocks'},
    {key:'white-list',type:'bool',desc:'Enable whitelist'},
    {key:'view-distance',type:'number',desc:'View distance in chunks'},
    {key:'simulation-distance',type:'number',desc:'Simulation distance'}
  ]}
];

function renderSettings(){
  return`<div class="tab-head"><div class="tab-title">Settings</div><button class="btn btn-p btn-s" onclick="saveSettings()"><i class="fa-solid fa-save"></i>Save All</button></div>
<div class="sub-tabs" style="max-width:400px">
<div class="sub-tab${settingsSubTab==='server'?' on':''}" onclick="settingsSubTab='server';switchTab('settings')">server.properties</div>
<div class="sub-tab${settingsSubTab==='panel'?' on':''}" onclick="settingsSubTab='panel';switchTab('settings')">Panel Config</div>
</div>
${settingsSubTab==='server'?renderServerProps():renderPanelConfig()}`;
}

function renderServerProps(){
  const filtered=PROP_GROUPS.map(g=>({...g,props:g.props.filter(p=>!settingsSearch||p.key.includes(settingsSearch)||p.desc.toLowerCase().includes(settingsSearch.toLowerCase()))})).filter(g=>g.props.length);
  return`<div class="search-box"><i class="fa-solid fa-search"></i><input type="text" id="prop-search" placeholder="Search properties..." value="${escHtml(settingsSearch)}" oninput="settingsSearch=this.value;document.getElementById('props-body').innerHTML=renderPropsList()"></div>
<div id="props-body">${renderPropsList()}</div>`;
}

function renderPropsList(){
  const filtered=PROP_GROUPS.map(g=>({...g,props:g.props.filter(p=>!settingsSearch||p.key.includes(settingsSearch)||p.desc.toLowerCase().includes(settingsSearch.toLowerCase()))})).filter(g=>g.props.length);
  return filtered.map(g=>`<div class="prop-group"><div class="prop-group-title"><i class="fa-solid ${g.icon}" style="margin-right:6px"></i>${g.group}</div>
${g.props.map(p=>{const val=serverProps[p.key]??'';return`<div class="prop-row"><div class="prop-label">${p.key}<div class="prop-desc">${p.desc}</div></div>
<div class="prop-input">${p.type==='bool'?`<div class="toggle${(val==='true'||val===true)?' on':''}" onclick="toggleProp('${p.key}',this)" data-key="${p.key}"></div>`:p.type==='select'?renderCustomSelect(p.key,val,p.options):`<input type="${p.type==='number'?'number':'text'}" value="${escHtml(val)}" onchange="serverProps['${p.key}']=this.value" placeholder="—">`}</div>
</div>`;}).join('')}</div>`).join('');
}

async function fetchServerProps(){
  try{
    const r=await fetch('/api/settings/properties');
    if(r.ok){serverProps=await r.json();}
  }catch(e){}
  const body=document.getElementById('props-body');
  if(body)body.innerHTML=renderPropsList();
}

function toggleProp(key,el){
  const isOn=el.classList.toggle('on');
  serverProps[key]=isOn?'true':'false';
}

async function saveSettings(){
  if(settingsSubTab==='server'){
    const fd=new FormData();fd.append('data',JSON.stringify(serverProps));
    const r=await fetch('/api/settings/properties',{method:'POST',body:fd});
    if(r.ok)toast('server.properties saved','success');else toast('Save failed','error');
  }else{
    const fd=new FormData();fd.append('data',JSON.stringify(panelConfig));
    await fetch('/api/settings/panel',{method:'POST',body:fd});
    toast('Panel config saved','success');
  }
}

function renderCustomSelect(key,val,options){
  return`<div class="custom-select" id="cs-${key}" onclick="toggleCS('cs-${key}')">
<div class="cs-display"><span id="cs-val-${key}">${escHtml(val||options[0]||'')}</span><i class="fa-solid fa-chevron-down"></i></div>
<div class="cs-options">${options.map(o=>`<div class="cs-opt${o===val?' on':''}" onclick="event.stopPropagation();selectCS('cs-${key}','${o}','${key}')">${o}</div>`).join('')}</div></div>`;
}

function toggleCS(id){
  document.querySelectorAll('.custom-select.open').forEach(el=>{if(el.id!==id)el.classList.remove('open')});
  document.getElementById(id)?.classList.toggle('open');
}
function selectCS(id,val,propKey){
  const el=document.getElementById(id);if(!el)return;
  const span=document.getElementById('cs-val-'+propKey);if(span)span.textContent=val;
  el.querySelectorAll('.cs-opt').forEach(o=>{o.classList.toggle('on',o.textContent===val)});
  el.classList.remove('open');
  serverProps[propKey]=val;
}
document.addEventListener('click',e=>{if(!e.target.closest('.custom-select'))document.querySelectorAll('.custom-select.open').forEach(el=>el.classList.remove('open'))});

function renderPanelConfig(){
  return`<div class="prop-group"><div class="prop-group-title"><i class="fa-solid fa-globe" style="margin-right:6px"></i>Server Info</div>
<div class="prop-row"><div class="prop-label">Server Address<div class="prop-desc">Displayed on dashboard; used for status checks</div></div>
<div class="prop-input"><input type="text" value="${escHtml(panelConfig.serverAddress)}" onchange="panelConfig.serverAddress=this.value"></div></div>
</div>
<div class="prop-group"><div class="prop-group-title"><i class="fa-solid fa-palette" style="margin-right:6px"></i>Theme</div>
<div class="prop-row"><div class="prop-label">Accent Color<div class="prop-desc">Primary color for buttons and highlights</div></div>
<div class="prop-input"><div class="color-input-wrap">
<input type="text" id="pc-accent" value="${escHtml(panelConfig.accentColor)}" onchange="applyAccent(this.value)">
<div class="color-preview" style="background:${escHtml(panelConfig.accentColor)}"><input type="color" value="${escHtml(panelConfig.accentColor)}" oninput="document.getElementById('pc-accent').value=this.value;applyAccent(this.value);this.parentElement.style.background=this.value"></div>
</div></div></div>
<div class="prop-row"><div class="prop-label">Background Color<div class="prop-desc">Main background color</div></div>
<div class="prop-input"><div class="color-input-wrap">
<input type="text" id="pc-bg" value="${escHtml(panelConfig.bgColor)}" onchange="applyBg(this.value)">
<div class="color-preview" style="background:${escHtml(panelConfig.bgColor)}"><input type="color" value="${escHtml(panelConfig.bgColor)}" oninput="document.getElementById('pc-bg').value=this.value;applyBg(this.value);this.parentElement.style.background=this.value"></div>
</div></div></div>
<div class="prop-row"><div class="prop-label">Text Size<div class="prop-desc">Base font size in pixels (10–20)</div></div>
<div class="prop-input"><input type="number" value="${escHtml(panelConfig.textSize)}" min="10" max="20" onchange="panelConfig.textSize=this.value;document.documentElement.style.setProperty('--tsz',this.value+'px')"></div></div>
</div>`;
}

function applyAccent(c){
  if(!/^#[0-9a-fA-F]{6}$/.test(c))return;
  panelConfig.accentColor=c;
  const r=parseInt(c.slice(1,3),16),g=parseInt(c.slice(3,5),16),b=parseInt(c.slice(5,7),16);
  const darker=`rgb(${Math.floor(r*.8)},${Math.floor(g*.8)},${Math.floor(b*.8)})`;
  document.documentElement.style.setProperty('--g',c);
  document.documentElement.style.setProperty('--gd',darker);
  document.documentElement.style.setProperty('--ga',c+'14');
  document.documentElement.style.setProperty('--ga2',c+'28');
}
function applyBg(c){
  if(!/^#[0-9a-fA-F]{6}$/.test(c))return;
  panelConfig.bgColor=c;
  document.documentElement.style.setProperty('--bg',c);
  const r=parseInt(c.slice(1,3),16),g=parseInt(c.slice(3,5),16),b=parseInt(c.slice(5,7),16);
  document.documentElement.style.setProperty('--bg2',`rgb(${Math.min(r+10,255)},${Math.min(g+10,255)},${Math.min(b+10,255)})`);
  document.documentElement.style.setProperty('--bg3',`rgb(${Math.min(r+18,255)},${Math.min(g+18,255)},${Math.min(b+18,255)})`);
  document.documentElement.style.setProperty('--bg4',`rgb(${Math.min(r+28,255)},${Math.min(g+28,255)},${Math.min(b+28,255)})`);
}

async function loadPanelConfig(){
  try{
    const r=await fetch('/api/settings/panel');
    if(r.ok){const d=await r.json();Object.assign(panelConfig,d);applyAccent(panelConfig.accentColor);applyBg(panelConfig.bgColor);if(panelConfig.textSize)document.documentElement.style.setProperty('--tsz',panelConfig.textSize+'px');}
  }catch(e){}
}

// ─── PROFILE ──────────────────────────────────────────────────────────────
function renderProfile(){
  return`<div class="tab-head"><div class="tab-title">Profile</div></div>
<div class="coming-soon"><i class="fa-solid fa-user-astronaut"></i><h2>Coming Soon</h2><p style="font-size:12px">Profile management is under development</p></div>`;
}

// ─── MODAL ────────────────────────────────────────────────────────────────
function showModal(cfg){
  const m=document.getElementById('modal-wrap'),box=document.getElementById('modal-box');
  box.className='modal';
  if(cfg.cls==='editor-modal')m.classList.add('editor-modal');else m.classList.remove('editor-modal');
  box.innerHTML=`<div class="modal-head"><h3>${cfg.title||''}</h3><button class="modal-close" onclick="closeModal()"><i class="fa-solid fa-xmark"></i></button></div><div class="modal-body">${cfg.body||''}</div>${cfg.foot?`<div class="modal-foot">${cfg.foot}</div>`:''}`;
  m.classList.add('on');
}
function closeModal(){document.getElementById('modal-wrap').classList.remove('on','editor-modal')}
function modalBgClick(e){if(e.target.classList.contains('modal-bg'))closeModal()}

// ─── TOAST ────────────────────────────────────────────────────────────────
function toast(msg,type='success'){
  const w=document.getElementById('toast-wrap');
  const icons={success:'fa-circle-check',error:'fa-circle-xmark',warn:'fa-triangle-exclamation'};
  const t=document.createElement('div');t.className=`toast ${type}`;
  t.innerHTML=`<i class="fa-solid ${icons[type]||icons.success}"></i><span>${escHtml(msg)}</span>`;
  w.appendChild(t);
  setTimeout(()=>{t.style.opacity='0';t.style.transform='translateY(-10px)';t.style.transition='all .3s';setTimeout(()=>t.remove(),300)},3500);
}

// ─── SIDEBAR ──────────────────────────────────────────────────────────────
function toggleSb(){document.getElementById('sidebar').classList.add('open');document.getElementById('overlay').classList.add('on')}
function closeSb(){document.getElementById('sidebar').classList.remove('open');document.getElementById('overlay').classList.remove('on')}
function hideCtx(){document.getElementById('ctx-menu').style.display='none'}

// ─── KEYBOARD ─────────────────────────────────────────────────────────────
document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeModal();hideCtx()}});

// ─── INIT ─────────────────────────────────────────────────────────────────
(async()=>{
  await loadPanelConfig();
  // Update sidebar server info
  try{
    const r=await fetch('/api/server/status');const d=await r.json();
    const info=document.getElementById('sb-server-info');
    if(info)info.textContent=`v${d.mc_version||'?'} • ${d.active_jar||'No jar'}`;
  }catch(e){}
  renderNav();
  switchTab('server');
})();
</script>
</body></html>"""

# ─── PATH HELPER ─────────────────────────────────────────────────────────────
def safe_path(p: str) -> str:
    clean = (p or "").strip("/").replace("..", "")
    full  = os.path.abspath(os.path.join(BASE_DIR, clean))
    if not full.startswith(os.path.abspath(BASE_DIR)):
        raise HTTPException(403, "Access denied")
    return full

# ─── MC PROCESS MANAGEMENT ───────────────────────────────────────────────────
async def stream_output(pipe):
    while True:
        line = await pipe.readline()
        if not line:
            break
        txt = line.decode("utf-8", errors="replace").rstrip()
        output_history.append(txt)
        dead = set()
        for c in connected_clients:
            try:
                await c.send_text(txt)
            except:
                dead.add(c)
        connected_clients.difference_update(dead)

async def boot_mc():
    global mc_process, server_start_time
    # Prefer purpur.jar → paper.jar → server.jar
    jar = None
    for candidate in ("purpur.jar", "paper.jar", "server.jar"):
        p = os.path.join(BASE_DIR, candidate)
        if os.path.exists(p):
            jar = p
            break
    if not jar:
        output_history.append("\x1b[33m[System] No server jar found in /app. Upload one via Files or install via Software tab.\x1b[0m")
        return
    server_start_time = time.time()
    mc_process = await asyncio.create_subprocess_exec(
        "java", "-Xmx4G", "-Xms1G", "-Dfile.encoding=UTF-8",
        "-XX:+UseG1GC", "-XX:+ParallelRefProcEnabled",
        "-jar", jar, "--nogui",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=BASE_DIR
    )
    asyncio.create_task(stream_output(mc_process.stdout))
    await mc_process.wait()
    server_start_time = None
    output_history.append("[System] Server process exited.")

@app.on_event("startup")
async def on_start():
    os.makedirs(PLUGINS_DIR, exist_ok=True)
    asyncio.create_task(boot_mc())

# ─── ROUTES ───────────────────────────────────────────────────────────────────
@app.get("/")
def index():
    return HTMLResponse(HTML_CONTENT)

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    connected_clients.add(ws)
    # Replay history
    for line in output_history:
        try:
            await ws.send_text(line)
        except:
            break
    try:
        while True:
            cmd = await ws.receive_text()
            if mc_process and mc_process.stdin and not mc_process.stdin.is_closing():
                mc_process.stdin.write((cmd + "\n").encode())
                await mc_process.stdin.drain()
    except (WebSocketDisconnect, Exception):
        connected_clients.discard(ws)

@app.get("/api/console/history")
def console_history():
    return list(output_history)

# ─── SERVER STATUS ────────────────────────────────────────────────────────────
@app.get("/api/server/status")
def server_status():
    running = mc_process is not None and mc_process.returncode is None

    # Uptime
    uptime_str = "—"
    if server_start_time and running:
        secs  = int(time.time() - server_start_time)
        h, r  = divmod(secs, 3600)
        m, s  = divmod(r, 60)
        uptime_str = f"{h}h {m}m {s}s" if h else f"{m}m {s}s"

    # Memory (from /proc/meminfo if available)
    ram_total, ram_used, ram_pct = 0, 0, 0
    try:
        with open("/proc/meminfo") as f:
            mem = {}
            for line in f:
                k, v = line.split(":", 1)
                mem[k.strip()] = int(v.strip().split()[0])
        ram_total = mem.get("MemTotal", 0)
        ram_free  = mem.get("MemAvailable", mem.get("MemFree", 0))
        ram_used  = ram_total - ram_free
        ram_pct   = round(ram_used / ram_total * 100) if ram_total else 0
    except:
        pass

    # CPU (simple /proc/stat delta approximation)
    cpu_pct = 0
    try:
        with open("/proc/stat") as f:
            vals = list(map(int, f.readline().split()[1:]))
        idle, total = vals[3], sum(vals)
        cpu_pct = max(0, round(100 - idle / total * 100)) if total else 0
    except:
        pass

    # Disk
    disk_total, disk_used, disk_pct = 0, 0, 0
    try:
        st = os.statvfs(BASE_DIR)
        disk_total = st.f_blocks * st.f_frsize
        disk_free  = st.f_bfree  * st.f_frsize
        disk_used  = disk_total  - disk_free
        disk_pct   = round(disk_used / disk_total * 100) if disk_total else 0
    except:
        pass

    def mb(b): return f"{b//1048576} MB" if b else "—"
    def gb(b): return f"{b/1073741824:.1f} GB" if b else "—"

    # Active jar
    active_jar = None
    for c in ("purpur.jar", "paper.jar", "server.jar"):
        if os.path.exists(os.path.join(BASE_DIR, c)):
            active_jar = c; break

    return {
        "running":    running,
        "uptime":     uptime_str,
        "cpu_pct":    cpu_pct,
        "cpu_sub":    f"{cpu_pct}% utilization",
        "ram_pct":    ram_pct,
        "ram_sub":    f"{mb(ram_used)} / {mb(ram_total)}",
        "disk_pct":   disk_pct,
        "disk_sub":   f"{gb(disk_used)} / {gb(disk_total)}",
        "tps":        "—",
        "players":    "—",
        "mc_version": "1.20.4",
        "active_jar": active_jar,
        "address":    ""
    }

@app.post("/api/server/{action}")
async def server_control(action: str):
    global mc_process
    if action == "stop":
        if mc_process and mc_process.returncode is None:
            try:
                mc_process.stdin.write(b"stop\n")
                await mc_process.stdin.drain()
            except:
                mc_process.terminate()
    elif action == "start":
        if mc_process is None or mc_process.returncode is not None:
            asyncio.create_task(boot_mc())
    elif action == "restart":
        if mc_process and mc_process.returncode is None:
            try:
                mc_process.stdin.write(b"stop\n")
                await mc_process.stdin.drain()
                await asyncio.sleep(3)
            except:
                pass
        asyncio.create_task(boot_mc())
    return {"ok": True}

# ─── FILE SYSTEM API ──────────────────────────────────────────────────────────
@app.get("/api/fs/list")
def fs_list(path: str = ""):
    target = safe_path(path)
    if not os.path.isdir(target):
        raise HTTPException(404, "Not a directory")
    items = []
    for name in os.listdir(target):
        fp  = os.path.join(target, name)
        st  = os.stat(fp)
        items.append({
            "name":   name,
            "is_dir": os.path.isdir(fp),
            "size":   st.st_size if not os.path.isdir(fp) else -1,
            "mtime":  int(st.st_mtime)
        })
    return sorted(items, key=lambda x: (not x["is_dir"], x["name"].lower()))

@app.get("/api/fs/read")
def fs_read(path: str):
    target = safe_path(path)
    if not os.path.isfile(target):
        raise HTTPException(404, "File not found")
    try:
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        if path.endswith(".json"):
            try:
                return json.loads(content)
            except:
                pass
        return Response(content, media_type="text/plain; charset=utf-8")
    except:
        raise HTTPException(500, "Cannot read file")

@app.get("/api/fs/download")
def fs_download(path: str):
    target = safe_path(path)
    if not os.path.isfile(target):
        raise HTTPException(404, "File not found")
    from fastapi.responses import FileResponse
    return FileResponse(target, filename=os.path.basename(target))

@app.post("/api/fs/write")
async def fs_write(path: str = Form(...), content: str = Form(...)):
    target = safe_path(path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write(content)
    return {"ok": True}

@app.post("/api/fs/upload")
async def fs_upload(path: str = Form(""), file: UploadFile = File(...)):
    target_dir = safe_path(path)
    os.makedirs(target_dir, exist_ok=True)
    dest = os.path.join(target_dir, file.filename)
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"ok": True}

@app.post("/api/fs/delete")
def fs_delete(path: str = Form(...)):
    target = safe_path(path)
    if not os.path.exists(target):
        raise HTTPException(404, "Not found")
    if os.path.isdir(target):
        shutil.rmtree(target)
    else:
        os.remove(target)
    return {"ok": True}

@app.post("/api/fs/rename")
def fs_rename(old_path: str = Form(...), new_path: str = Form(...)):
    src = safe_path(old_path)
    dst = safe_path(new_path)
    if not os.path.exists(src):
        raise HTTPException(404, "Source not found")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src, dst)
    return {"ok": True}

@app.post("/api/fs/create")
def fs_create(path: str = Form(...), is_dir: str = Form("0")):
    target = safe_path(path)
    if is_dir == "1":
        os.makedirs(target, exist_ok=True)
    else:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if not os.path.exists(target):
            open(target, "w").close()
    return {"ok": True}

# ─── PLUGIN INSTALLER ─────────────────────────────────────────────────────────
@app.post("/api/plugins/install")
def plugins_install(
    url: str        = Form(...),
    filename: str   = Form(...),
    project_id: str = Form(...),
    version_id: str = Form(...),
    name: str       = Form(...)
):
    dest = os.path.join(PLUGINS_DIR, filename)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "OrbitPanel/2.0"})
        with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
            shutil.copyfileobj(resp, f)
    except Exception as e:
        raise HTTPException(500, f"Download failed: {e}")

    record_path = os.path.join(PLUGINS_DIR, "plugins.json")
    data = {}
    if os.path.exists(record_path):
        try:
            with open(record_path) as f:
                data = json.load(f)
        except:
            pass
    data[project_id] = {
        "name":         name,
        "filename":     filename,
        "version_id":   version_id,
        "installed_at": time.time()
    }
    with open(record_path, "w") as f:
        json.dump(data, f, indent=2)
    return {"ok": True}

# ─── SOFTWARE INSTALLER ───────────────────────────────────────────────────────
@app.post("/api/software/install")
async def software_install(type: str = Form(...), version: str = Form(...)):
    """Download and install a server jar from official sources."""
    dest = os.path.join(BASE_DIR, "server.jar")
    # Rename existing jar as backup
    for candidate in ("purpur.jar", "paper.jar", "server.jar"):
        p = os.path.join(BASE_DIR, candidate)
        if os.path.exists(p):
            shutil.copy2(p, p + ".bak")

    try:
        dl_url = None

        if type == "paper":
            # Get latest build for version
            builds_url = f"https://api.papermc.io/v2/projects/paper/versions/{version}/builds"
            with urllib.request.urlopen(builds_url, timeout=15) as r:
                builds_data = json.loads(r.read())
            latest_build = builds_data["builds"][-1]["build"]
            jar_name     = f"paper-{version}-{latest_build}.jar"
            dl_url       = f"https://api.papermc.io/v2/projects/paper/versions/{version}/builds/{latest_build}/downloads/{jar_name}"

        elif type == "purpur":
            dl_url = f"https://api.purpurmc.org/v2/purpur/{version}/latest/download"

        elif type == "vanilla":
            with urllib.request.urlopen("https://launchermeta.mojang.com/mc/game/version_manifest.json", timeout=15) as r:
                manifest = json.loads(r.read())
            ver_info = next((v for v in manifest["versions"] if v["id"] == version), None)
            if not ver_info:
                raise HTTPException(404, f"Version {version} not found in manifest")
            with urllib.request.urlopen(ver_info["url"], timeout=15) as r:
                ver_data = json.loads(r.read())
            dl_url = ver_data["downloads"]["server"]["url"]

        elif type == "fabric":
            # Get latest loader + installer
            with urllib.request.urlopen("https://meta.fabricmc.net/v2/versions/loader", timeout=10) as r:
                loaders = json.loads(r.read())
            with urllib.request.urlopen("https://meta.fabricmc.net/v2/versions/installer", timeout=10) as r:
                installers = json.loads(r.read())
            loader_ver    = loaders[0]["version"]
            installer_ver = installers[0]["version"]
            dl_url = f"https://meta.fabricmc.net/v2/versions/loader/{version}/{loader_ver}/{installer_ver}/server/jar"

        else:
            raise HTTPException(400, f"Unsupported type: {type}")

        def do_download():
            req = urllib.request.Request(dl_url, headers={"User-Agent": "OrbitPanel/2.0"})
            with urllib.request.urlopen(req, timeout=300) as resp, open(dest, "wb") as f:
                shutil.copyfileobj(resp, f)

        # Run blocking download in thread
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, do_download)
        output_history.append(f"[System] Installed {type} {version} → server.jar")
        return {"ok": True}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

# ─── SETTINGS API ─────────────────────────────────────────────────────────────
def _parse_properties(path: str) -> dict:
    props = {}
    if not os.path.isfile(path):
        return props
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            props[k.strip()] = v.strip()
    return props

def _write_properties(path: str, props: dict):
    lines = [f"# Managed by Orbit Panel\n"]
    for k, v in sorted(props.items()):
        lines.append(f"{k}={v}\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)

@app.get("/api/settings/properties")
def get_properties():
    path = os.path.join(BASE_DIR, "server.properties")
    return _parse_properties(path)

@app.post("/api/settings/properties")
async def save_properties(data: str = Form(...)):
    path = os.path.join(BASE_DIR, "server.properties")
    try:
        props = json.loads(data)
        _write_properties(path, props)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/api/settings/panel")
def get_panel_config():
    if os.path.isfile(PANEL_CFG):
        try:
            with open(PANEL_CFG) as f:
                return json.load(f)
        except:
            pass
    return {"accentColor": "#00ff88", "bgColor": "#0a0a0a", "textSize": "14", "serverAddress": ""}

@app.post("/api/settings/panel")
async def save_panel_config(data: str = Form(...)):
    try:
        cfg = json.loads(data)
        with open(PANEL_CFG, "w") as f:
            json.dump(cfg, f, indent=2)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, str(e))

# ─── ENTRY POINT ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 7860)),
        log_level="warning"
    )
