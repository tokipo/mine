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
# Automatically adapts to Hugging Face Docker environments (/app, /home/user/app, etc.)
BASE_DIR = os.path.abspath(os.getcwd())

# -----------------
# HTML FRONTEND (Ultra-Modern UI)
# -----------------
HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>OrbitMC</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=Geist:wght@300;400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#0a0a0a;--s1:#111;--s2:#181818;--s3:#222;
  --b1:#2a2a2a;--b2:#333;
  --t1:#f0f0f0;--t2:#999;--t3:#555;
  --accent:#4ade80;--accent2:#22c55e;
  --red:#f87171;--blue:#60a5fa;--yellow:#fbbf24;
  --r:8px;--font:'Geist',sans-serif;--mono:'JetBrains Mono',monospace;
  --trans:all .15s ease;
}
body{background:var(--bg);color:var(--t1);font-family:var(--font);font-size:14px;display:flex;height:100vh;overflow:hidden}

/* SIDEBAR */
.sidebar{width:56px;background:var(--s1);border-right:1px solid var(--b1);display:flex;flex-direction:column;align-items:center;padding:16px 0;gap:4px;z-index:10;flex-shrink:0}
.nav-btn{width:40px;height:40px;border:none;background:transparent;color:var(--t3);border-radius:var(--r);cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:16px;transition:var(--trans);position:relative}
.nav-btn:hover{background:var(--s3);color:var(--t2)}
.nav-btn.active{background:rgba(74,222,128,.12);color:var(--accent)}
.nav-btn .tooltip{position:absolute;left:52px;background:#1a1a1a;border:1px solid var(--b1);color:var(--t1);padding:4px 10px;border-radius:6px;font-size:12px;white-space:nowrap;pointer-events:none;opacity:0;transition:opacity .15s;z-index:100}
.nav-btn:hover .tooltip{opacity:1}

/* MAIN */
.main{flex:1;display:flex;flex-direction:column;overflow:hidden}
.panel{display:none;flex:1;overflow:hidden}
.panel.active{display:flex;flex-direction:column}

/* CONSOLE */
.console-wrap{flex:1;position:relative;overflow:hidden;background:var(--s1)}
.console-blur{position:absolute;top:0;left:0;right:0;height:60px;background:linear-gradient(to bottom,var(--s1) 0%,transparent 100%);z-index:2;pointer-events:none}
.console-out{position:absolute;inset:0;overflow-y:auto;padding:16px;font-family:var(--mono);font-size:12.5px;line-height:1.7;scrollbar-width:thin;scrollbar-color:var(--b2) transparent}
.console-out::-webkit-scrollbar{width:4px}
.console-out::-webkit-scrollbar-thumb{background:var(--b2);border-radius:2px}
.log-line{animation:fadeUp .25s ease forwards;opacity:0;word-break:break-all}
@keyframes fadeUp{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.log-line.info{color:#94a3b8}.log-line.warn{color:var(--yellow)}.log-line.error{color:var(--red)}.log-line.ok{color:var(--accent)}
.console-input-bar{padding:12px 16px 20px;background:var(--s1);border-top:1px solid var(--b1);display:flex;gap:8px;align-items:center}
.console-input-bar .prompt{color:var(--accent);font-family:var(--mono);font-size:13px;flex-shrink:0}
.console-input-bar input{flex:1;background:var(--s2);border:1px solid var(--b1);color:var(--t1);font-family:var(--mono);font-size:13px;padding:8px 12px;border-radius:var(--r);outline:none;transition:var(--trans)}
.console-input-bar input:focus{border-color:var(--accent);box-shadow:0 0 0 2px rgba(74,222,128,.1)}
.send-btn{background:var(--accent);color:#000;border:none;padding:8px 16px;border-radius:var(--r);font-family:var(--font);font-weight:600;font-size:13px;cursor:pointer;transition:var(--trans);flex-shrink:0}
.send-btn:hover{background:var(--accent2)}

/* FILE MANAGER */
.fm-wrap{display:flex;flex-direction:column;flex:1;overflow:hidden}
.fm-toolbar{padding:12px 16px;background:var(--s1);border-bottom:1px solid var(--b1);display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.fm-breadcrumb{flex:1;display:flex;align-items:center;gap:4px;font-size:13px;color:var(--t2);overflow:hidden;min-width:0}
.fm-breadcrumb span{cursor:pointer;transition:color .15s;white-space:nowrap}
.fm-breadcrumb span:hover{color:var(--accent)}
.fm-breadcrumb .sep{color:var(--t3)}
.tb-btn{height:32px;padding:0 12px;background:var(--s2);border:1px solid var(--b1);color:var(--t2);border-radius:6px;cursor:pointer;font-size:12px;font-family:var(--font);display:flex;align-items:center;gap:6px;transition:var(--trans);white-space:nowrap}
.tb-btn:hover{background:var(--s3);color:var(--t1)}
.tb-btn.danger:hover{border-color:var(--red);color:var(--red)}
.fm-list{flex:1;overflow-y:auto;padding:8px;scrollbar-width:thin;scrollbar-color:var(--b2) transparent}
.fm-list::-webkit-scrollbar{width:4px}
.fm-list::-webkit-scrollbar-thumb{background:var(--b2)}
.fm-empty{display:flex;align-items:center;justify-content:center;height:100%;color:var(--t3);font-size:13px}
.fm-item{display:flex;align-items:center;padding:9px 12px;border-radius:6px;cursor:pointer;transition:background .1s;gap:10px;user-select:none}
.fm-item:hover{background:var(--s2)}
.fm-item.selected{background:rgba(74,222,128,.08);outline:1px solid rgba(74,222,128,.2)}
.fm-icon{width:20px;text-align:center;font-size:14px;flex-shrink:0}
.fi-dir{color:var(--blue)}.fi-cfg{color:var(--yellow)}.fi-jar{color:var(--accent)}.fi-log{color:var(--t3)}.fi-other{color:var(--t2)}
.fm-name{flex:1;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.fm-size{font-size:11px;color:var(--t3);flex-shrink:0}
.ctx-menu{position:fixed;background:#1a1a1a;border:1px solid var(--b1);border-radius:8px;padding:6px;z-index:1000;min-width:160px;box-shadow:0 8px 32px rgba(0,0,0,.6);animation:ctxIn .12s ease}
@keyframes ctxIn{from{opacity:0;transform:scale(.95)}to{opacity:1;transform:none}}
.ctx-item{padding:7px 12px;border-radius:5px;cursor:pointer;font-size:13px;color:var(--t2);display:flex;align-items:center;gap:8px;transition:var(--trans)}
.ctx-item:hover{background:var(--s3);color:var(--t1)}
.ctx-item.danger{color:var(--red)}.ctx-item.danger:hover{background:rgba(248,113,113,.1)}
.ctx-sep{height:1px;background:var(--b1);margin:4px 0}

/* CONFIG */
.cfg-wrap{flex:1;overflow-y:auto;padding:16px;scrollbar-width:thin;scrollbar-color:var(--b2) transparent}
.cfg-section{background:var(--s1);border:1px solid var(--b1);border-radius:10px;margin-bottom:16px;overflow:hidden}
.cfg-section-head{padding:12px 16px;border-bottom:1px solid var(--b1);font-size:12px;font-weight:600;color:var(--t3);text-transform:uppercase;letter-spacing:.06em}
.cfg-row{display:flex;align-items:center;padding:10px 16px;border-bottom:1px solid rgba(255,255,255,.03);gap:12px}
.cfg-row:last-child{border-bottom:none}
.cfg-key{flex:1;font-family:var(--mono);font-size:12.5px;color:var(--t2)}
.cfg-val{flex:1;background:var(--s2);border:1px solid var(--b1);color:var(--t1);font-family:var(--mono);font-size:12px;padding:5px 10px;border-radius:6px;outline:none;transition:var(--trans)}
.cfg-val:focus{border-color:var(--accent)}
.cfg-save{margin:0 16px 16px;background:var(--accent);color:#000;border:none;padding:9px 20px;border-radius:var(--r);font-weight:600;font-size:13px;cursor:pointer;transition:var(--trans)}
.cfg-save:hover{background:var(--accent2)}
.coming-soon{display:flex;align-items:center;justify-content:center;height:100%;flex-direction:column;gap:12px;color:var(--t3)}
.coming-soon i{font-size:36px;opacity:.3}

/* MODALS */
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:500;display:flex;align-items:center;justify-content:center;animation:fadeIn .15s ease;backdrop-filter:blur(4px)}
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
.modal{background:#161616;border:1px solid var(--b1);border-radius:12px;padding:24px;width:90%;max-width:480px;animation:modalIn .2s ease;box-shadow:0 24px 64px rgba(0,0,0,.6)}
.modal.wide{max-width:760px}
@keyframes modalIn{from{opacity:0;transform:translateY(12px) scale(.98)}to{opacity:1;transform:none}}
.modal h3{font-size:15px;font-weight:600;margin-bottom:16px;color:var(--t1)}
.modal input,.modal textarea{width:100%;background:var(--s2);border:1px solid var(--b1);color:var(--t1);font-family:var(--mono);font-size:13px;padding:9px 12px;border-radius:var(--r);outline:none;transition:var(--trans);margin-bottom:12px}
.modal input:focus,.modal textarea:focus{border-color:var(--accent)}
.modal textarea{min-height:320px;resize:vertical;line-height:1.6}
.modal-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:4px}
.btn-ghost{background:transparent;border:1px solid var(--b1);color:var(--t2);padding:7px 16px;border-radius:6px;cursor:pointer;font-family:var(--font);font-size:13px;transition:var(--trans)}
.btn-ghost:hover{border-color:var(--b2);color:var(--t1)}
.btn-primary{background:var(--accent);color:#000;border:none;padding:7px 16px;border-radius:6px;font-family:var(--font);font-weight:600;font-size:13px;cursor:pointer;transition:var(--trans)}
.btn-primary:hover{background:var(--accent2)}
.btn-danger{background:transparent;border:1px solid var(--red);color:var(--red);padding:7px 16px;border-radius:6px;cursor:pointer;font-family:var(--font);font-size:13px;transition:var(--trans)}
.btn-danger:hover{background:rgba(248,113,113,.1)}
.upload-zone{border:2px dashed var(--b2);border-radius:8px;padding:32px;text-align:center;color:var(--t3);cursor:pointer;transition:var(--trans);margin-bottom:12px}
.upload-zone:hover,.upload-zone.drag{border-color:var(--accent);color:var(--accent);background:rgba(74,222,128,.04)}
.upload-zone i{font-size:24px;margin-bottom:8px;display:block}
.upload-zone p{font-size:13px}
.status-dot{width:7px;height:7px;border-radius:50%;background:var(--accent);box-shadow:0 0 6px var(--accent);display:inline-block;margin-right:6px;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
@media(max-width:600px){.sidebar{width:48px}.tb-btn span{display:none}.tb-btn{padding:0 10px}.fm-size{display:none}}
</style>
</head>
<body>
<nav class="sidebar">
  <button class="nav-btn active" data-tab="console" onclick="switchTab('console',this)"><i class="fa-solid fa-terminal"></i><span class="tooltip">Console</span></button>
  <button class="nav-btn" data-tab="files" onclick="switchTab('files',this)"><i class="fa-solid fa-folder-open"></i><span class="tooltip">Files</span></button>
  <button class="nav-btn" data-tab="config" onclick="switchTab('config',this)"><i class="fa-solid fa-sliders"></i><span class="tooltip">Config</span></button>
  <button class="nav-btn" data-tab="plugins" onclick="switchTab('plugins',this)" style="margin-top:auto"><i class="fa-solid fa-puzzle-piece"></i><span class="tooltip">Plugins</span></button>
</nav>

<div class="main">
  <!-- CONSOLE -->
  <div class="panel active" id="tab-console">
    <div class="console-wrap">
      <div class="console-blur"></div>
      <div class="console-out" id="console-out"></div>
    </div>
    <div class="console-input-bar">
      <span class="prompt">$</span>
      <input id="cmd-input" type="text" placeholder="Enter command..." autocomplete="off" spellcheck="false" onkeydown="cmdKey(event)">
      <button class="send-btn" onclick="sendCmd()"><i class="fa-solid fa-paper-plane"></i></button>
    </div>
  </div>

  <!-- FILES -->
  <div class="panel" id="tab-files">
    <div class="fm-toolbar">
      <div class="fm-breadcrumb" id="breadcrumb"></div>
      <button class="tb-btn" onclick="showMkdir()"><i class="fa-solid fa-folder-plus"></i><span>New Folder</span></button>
      <button class="tb-btn" onclick="showUpload()"><i class="fa-solid fa-upload"></i><span>Upload</span></button>
    </div>
    <div class="fm-list" id="fm-list"></div>
  </div>

  <!-- CONFIG -->
  <div class="panel" id="tab-config">
    <div class="cfg-wrap" id="cfg-wrap">
      <div class="fm-empty" style="height:80px"><i class="fa-solid fa-spinner fa-spin"></i>&nbsp;Loading...</div>
    </div>
  </div>

  <!-- PLUGINS -->
  <div class="panel" id="tab-plugins">
    <div class="coming-soon">
      <i class="fa-solid fa-puzzle-piece"></i>
      <p style="font-size:15px;font-weight:600;color:var(--t2)">Plugins</p>
      <p style="font-size:13px">Coming soon</p>
    </div>
  </div>
</div>

<!-- MODALS -->
<div id="overlay" class="overlay" style="display:none" onclick="closeModal(event)">
  <div class="modal" id="modal" onclick="event.stopPropagation()">
    <h3 id="modal-title"></h3>
    <div id="modal-body"></div>
    <div class="modal-actions" id="modal-actions"></div>
  </div>
</div>

<script>
// WS
const wsProto = location.protocol === 'https:' ? 'wss' : 'ws';
let ws, cmdHistory=[], histIdx=-1;
function connectWS(){
  ws = new WebSocket(`${wsProto}://${location.host}/ws`);
  ws.onmessage = e => addLog(e.data);
  ws.onclose = () => setTimeout(connectWS, 2000);
}
connectWS();

function classify(l){
  if(/\[WARN|WARN\]/i.test(l)) return 'warn';
  if(/\[ERROR|ERROR\]/i.test(l)||/exception/i.test(l)) return 'error';
  if(/Done|started|enabled|loaded/i.test(l)) return 'ok';
  return 'info';
}
function addLog(txt){
  const out = document.getElementById('console-out');
  const atBottom = out.scrollHeight - out.clientHeight - out.scrollTop < 40;
  const d = document.createElement('div');
  d.className = `log-line ${classify(txt)}`;
  d.textContent = txt;
  out.appendChild(d);
  if(out.children.length > 400) out.removeChild(out.firstChild);
  if(atBottom) out.scrollTop = out.scrollHeight;
}
function sendCmd(){
  const i = document.getElementById('cmd-input');
  const v = i.value.trim();
  if(!v || !ws) return;
  ws.send(v);
  cmdHistory.unshift(v); histIdx=-1;
  i.value='';
}
function cmdKey(e){
  if(e.key==='Enter') sendCmd();
  else if(e.key==='ArrowUp'){histIdx=Math.min(histIdx+1,cmdHistory.length-1);document.getElementById('cmd-input').value=cmdHistory[histIdx]||'';}
  else if(e.key==='ArrowDown'){histIdx=Math.max(histIdx-1,-1);document.getElementById('cmd-input').value=histIdx>=0?cmdHistory[histIdx]:'';}
}

// TABS
function switchTab(id,btn){
  document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b=>b.classList.remove('active'));
  document.getElementById('tab-'+id).classList.add('active');
  btn.classList.add('active');
  if(id==='files') loadDir(currentPath);
  if(id==='config') loadConfig();
}

// FILE MANAGER
let currentPath='', selectedItem=null;
const api = p => fetch(p).then(r=>r.json());
const apiPost = (p,fd) => fetch(p,{method:'POST',body:fd});

async function loadDir(path=''){
  currentPath = path;
  renderBreadcrumb(path);
  const list = document.getElementById('fm-list');
  list.innerHTML = '<div class="fm-empty"><i class="fa-solid fa-spinner fa-spin"></i>&nbsp;Loading...</div>';
  const items = await api(`/api/fs/list?path=${encodeURIComponent(path)}`);
  list.innerHTML = '';
  if(!items.length){list.innerHTML='<div class="fm-empty">Empty folder</div>';return;}
  items.forEach(item => {
    const el = document.createElement('div');
    el.className = 'fm-item';
    const icon = getIcon(item);
    el.innerHTML = `<i class="fm-icon ${icon.cls} ${icon.ic}"></i><span class="fm-name">${item.name}</span><span class="fm-size">${item.is_dir?'—':fmtSize(item.size)}</span>`;
    el.addEventListener('click',()=>selectItem(item,el));
    el.addEventListener('dblclick',()=>openItem(item));
    el.addEventListener('contextmenu',e=>{e.preventDefault();selectItem(item,el);showCtx(e,item);});
    list.appendChild(el);
  });
}
function selectItem(item,el){
  document.querySelectorAll('.fm-item').forEach(e=>e.classList.remove('selected'));
  el.classList.add('selected'); selectedItem=item;
}
function getIcon(item){
  if(item.is_dir) return {cls:'fi-dir',ic:'fa-solid fa-folder'};
  const ext = item.name.split('.').pop().toLowerCase();
  if(['yml','yaml','json','toml','cfg','conf'].includes(ext)) return {cls:'fi-cfg',ic:'fa-solid fa-file-code'};
  if(ext==='jar') return {cls:'fi-jar',ic:'fa-solid fa-cube'};
  if(ext==='log') return {cls:'fi-log',ic:'fa-solid fa-file-lines'};
  if(['txt','md'].includes(ext)) return {cls:'fi-other',ic:'fa-solid fa-file-alt'};
  return {cls:'fi-other',ic:'fa-solid fa-file'};
}
function fmtSize(b){if(b<1024)return b+'B';if(b<1048576)return (b/1024).toFixed(1)+'KB';return (b/1048576).toFixed(1)+'MB';}
function renderBreadcrumb(path){
  const bc = document.getElementById('breadcrumb');
  const parts = path ? path.split('/').filter(Boolean) : [];
  let html = `<span onclick="loadDir('')"><i class="fa-solid fa-server" style="color:var(--accent)"></i></span>`;
  let acc = '';
  parts.forEach(p=>{acc+=(acc?'/':'')+p;const cp=acc;html+=`<span class="sep">/</span><span onclick="loadDir('${cp}')">${p}</span>`;});
  bc.innerHTML = html;
}
function openItem(item){
  const fp = (currentPath ? currentPath+'/' : '') + item.name;
  if(item.is_dir){loadDir(fp);return;}
  const ext = item.name.split('.').pop().toLowerCase();
  const editable = ['yml','yaml','json','toml','cfg','conf','txt','md','properties','log','sh','py','js'].includes(ext);
  if(editable) openEditor(fp,item.name);
  else downloadFile(fp,item.name);
}
function fullPath(name){return (currentPath ? currentPath+'/' : '') + name;}

async function openEditor(fp,name){
  const res = await fetch(`/api/fs/read?path=${encodeURIComponent(fp)}`);
  if(!res.ok){toast('Cannot read binary file');return;}
  const text = await res.text();
  openModal('Edit — '+name,'wide');
  M.body.innerHTML = `<textarea id="editor-ta" spellcheck="false">${escHtml(text)}</textarea>`;
  M.actions.innerHTML = `<button class="btn-ghost" onclick="closeModal()">Cancel</button><button class="btn-primary" onclick="saveFile('${fp}')">Save</button>`;
}
async function saveFile(fp){
  const content = document.getElementById('editor-ta').value;
  const fd = new FormData(); fd.append('path',fp); fd.append('content',content);
  await apiPost('/api/fs/write',fd);
  toast('Saved'); closeModal();
}
function downloadFile(fp,name){window.location='/api/fs/download?path='+encodeURIComponent(fp);}

function showCtx(e,item){
  document.querySelectorAll('.ctx-menu').forEach(c=>c.remove());
  const fp = fullPath(item.name);
  const m = document.createElement('div'); m.className='ctx-menu';
  const items = [
    {icon:'fa-solid fa-pen',label:'Rename',fn:()=>showRename(fp,item.name)},
    ...(item.is_dir?[]:[{icon:'fa-solid fa-edit',label:'Edit',fn:()=>openEditor(fp,item.name)},{icon:'fa-solid fa-download',label:'Download',fn:()=>downloadFile(fp,item.name)}]),
    {sep:true},
    {icon:'fa-solid fa-trash',label:'Delete',fn:()=>showDelete(fp,item.name),danger:true},
  ];
  items.forEach(it=>{
    if(it.sep){const s=document.createElement('div');s.className='ctx-sep';m.appendChild(s);return;}
    const d=document.createElement('div');d.className='ctx-item'+(it.danger?' danger':'');
    d.innerHTML=`<i class="${it.icon}"></i>${it.label}`;
    d.onclick=()=>{m.remove();it.fn();};
    m.appendChild(d);
  });
  m.style.top = Math.min(e.clientY,window.innerHeight-m.offsetHeight-10)+'px';
  m.style.left = Math.min(e.clientX,window.innerWidth-180)+'px';
  document.body.appendChild(m);
  setTimeout(()=>document.addEventListener('click',()=>m.remove(),{once:true}),10);
}

function showRename(fp,name){
  openModal('Rename');
  M.body.innerHTML=`<input id="rename-in" value="${name}" autocomplete="off">`;
  M.actions.innerHTML=`<button class="btn-ghost" onclick="closeModal()">Cancel</button><button class="btn-primary" onclick="doRename('${fp}')">Rename</button>`;
  setTimeout(()=>{const i=document.getElementById('rename-in');i.focus();i.select();},50);
}
async function doRename(fp){
  const nv = document.getElementById('rename-in').value.trim();
  if(!nv) return;
  const fd=new FormData();fd.append('path',fp);fd.append('new_name',nv);
  await apiPost('/api/fs/rename',fd);
  closeModal(); loadDir(currentPath);
}
function showDelete(fp,name){
  openModal('Delete');
  M.body.innerHTML=`<p style="color:var(--t2);font-size:13px;margin-bottom:16px">Delete <strong style="color:var(--t1)">${name}</strong>? This cannot be undone.</p>`;
  M.actions.innerHTML=`<button class="btn-ghost" onclick="closeModal()">Cancel</button><button class="btn-danger" onclick="doDelete('${fp}')">Delete</button>`;
}
async function doDelete(fp){
  const fd=new FormData();fd.append('path',fp);
  await apiPost('/api/fs/delete',fd);
  closeModal(); loadDir(currentPath);
}
function showMkdir(){
  openModal('New Folder');
  M.body.innerHTML=`<input id="mkdir-in" placeholder="Folder name" autocomplete="off">`;
  M.actions.innerHTML=`<button class="btn-ghost" onclick="closeModal()">Cancel</button><button class="btn-primary" onclick="doMkdir()">Create</button>`;
  setTimeout(()=>document.getElementById('mkdir-in').focus(),50);
}
async function doMkdir(){
  const n=document.getElementById('mkdir-in').value.trim();if(!n)return;
  const fd=new FormData();fd.append('path',(currentPath?currentPath+'/':'')+n);
  await apiPost('/api/fs/mkdir',fd);
  closeModal(); loadDir(currentPath);
}
function showUpload(){
  openModal('Upload Files');
  M.body.innerHTML=`<div class="upload-zone" id="drop-zone" onclick="document.getElementById('file-in').click()">
    <i class="fa-solid fa-cloud-arrow-up"></i><p>Click or drag & drop files</p></div>
    <input type="file" id="file-in" multiple style="display:none" onchange="handleUpload(this.files)">
    <div id="upload-prog"></div>`;
  M.actions.innerHTML=`<button class="btn-ghost" onclick="closeModal()">Close</button>`;
  const dz=document.getElementById('drop-zone');
  dz.ondragover=e=>{e.preventDefault();dz.classList.add('drag')};
  dz.ondragleave=()=>dz.classList.remove('drag');
  dz.ondrop=e=>{e.preventDefault();dz.classList.remove('drag');handleUpload(e.dataTransfer.files);};
}
async function handleUpload(files){
  const prog=document.getElementById('upload-prog');
  for(const file of files){
    prog.innerHTML=`<p style="font-size:12px;color:var(--t2);margin-bottom:4px">Uploading ${file.name}...</p>`;
    const fd=new FormData();fd.append('path',currentPath);fd.append('file',file);
    await apiPost('/api/fs/upload',fd);
  }
  prog.innerHTML=`<p style="font-size:12px;color:var(--accent)">Done!</p>`;
  loadDir(currentPath);
}

// CONFIG
async function loadConfig(){
  const wrap = document.getElementById('cfg-wrap');
  wrap.innerHTML='<div class="fm-empty"><i class="fa-solid fa-spinner fa-spin"></i>&nbsp;Loading...</div>';
  const res = await fetch('/api/fs/read?path='+encodeURIComponent('server.properties'));
  if(!res.ok){wrap.innerHTML='<div class="fm-empty" style="flex-direction:column;gap:8px"><i class="fa-solid fa-circle-exclamation" style="color:var(--t3)"></i><p style="font-size:13px;color:var(--t3)">server.properties not found</p></div>';return;}
  const text = await res.text();
  const groups = {General:[],World:[],Network:[],Game:[],Performance:[]};
  const gmap={motd:'General',server_ip:'Network','server-port':'Network','max-players':'General','online-mode':'Network','enable-rcon':'Network','rcon.port':'Network','rcon.password':'Network','level-name':'World','level-seed':'World','gamemode':'Game','difficulty':'Game','hardcore':'Game','pvp':'Game','spawn-monsters':'Game','spawn-animals':'Game','spawn-npcs':'Game','view-distance':'Performance','simulation-distance':'Performance','max-tick-time':'Performance','network-compression-threshold':'Performance'};
  const lines=text.split('\n').filter(l=>l&&!l.startsWith('#'));
  const entries=[];
  lines.forEach(l=>{const eq=l.indexOf('=');if(eq<0)return;const k=l.slice(0,eq).trim(),v=l.slice(eq+1).trim();entries.push({k,v});});
  const grouped={General:[],World:[],Network:[],Game:[],Performance:[],Other:[]};
  entries.forEach(e=>{const g=gmap[e.k]||'Other';grouped[g].push(e);});
  wrap.innerHTML='';
  Object.entries(grouped).forEach(([g,rows])=>{
    if(!rows.length) return;
    const sec=document.createElement('div');sec.className='cfg-section';
    sec.innerHTML=`<div class="cfg-section-head">${g}</div>`;
    rows.forEach(({k,v})=>{
      const r=document.createElement('div');r.className='cfg-row';
      r.innerHTML=`<span class="cfg-key">${k}</span><input class="cfg-val" data-key="${k}" value="${escHtml(v)}">`;
      sec.appendChild(r);
    });
    wrap.appendChild(sec);
  });
  const btn=document.createElement('button');btn.className='cfg-save';btn.textContent='Save Changes';
  btn.onclick=saveConfig;wrap.appendChild(btn);
}
async function saveConfig(){
  const res=await fetch('/api/fs/read?path=server.properties');
  let text=await res.text();
  document.querySelectorAll('.cfg-val').forEach(inp=>{
    const k=inp.dataset.key,v=inp.value;
    text=text.replace(new RegExp(`^(${k}\\s*=).*$`,'m'),`$1${v}`);
  });
  const fd=new FormData();fd.append('path','server.properties');fd.append('content',text);
  await apiPost('/api/fs/write',fd);
  toast('server.properties saved');
}

// MODAL
const M={el:null,body:null,actions:null};
function openModal(title,cls=''){
  const ov=document.getElementById('overlay');
  const mo=document.getElementById('modal');
  mo.className='modal'+(cls?' '+cls:'');
  document.getElementById('modal-title').textContent=title;
  M.body=document.getElementById('modal-body');M.body.innerHTML='';
  M.actions=document.getElementById('modal-actions');M.actions.innerHTML='';
  ov.style.display='flex';
}
function closeModal(e){
  if(e&&e.target!==document.getElementById('overlay'))return;
  document.getElementById('overlay').style.display='none';
}
document.addEventListener('keydown',e=>{if(e.key==='Escape')document.getElementById('overlay').style.display='none';});

// TOAST
function toast(msg){
  const t=document.createElement('div');
  t.style.cssText='position:fixed;bottom:80px;left:50%;transform:translateX(-50%);background:#1a1a1a;border:1px solid var(--b1);color:var(--t1);padding:8px 18px;border-radius:8px;font-size:13px;z-index:9999;animation:fadeIn .2s ease;white-space:nowrap;box-shadow:0 8px 24px rgba(0,0,0,.5)';
  t.textContent=msg;document.body.appendChild(t);
  setTimeout(()=>t.remove(),2200);
}
function escHtml(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}

// Init
loadDir('');
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
        raise HTTPException(status_code=403, detail="Access denied outside server directory")
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

@app.post("/api/fs/rename")
def fs_rename(path: str = Form(...), new_name: str = Form(...)):
    target = get_safe_path(path)
    if not os.path.exists(target):
        raise HTTPException(404, "File not found")
    if "/" in new_name or "\\" in new_name:
        raise HTTPException(400, "Invalid new name")
    new_target = get_safe_path(os.path.join(os.path.dirname(path), new_name))
    os.rename(target, new_target)
    return {"status": "ok"}

@app.post("/api/fs/mkdir")
def fs_mkdir(path: str = Form(...)):
    target = get_safe_path(path)
    os.makedirs(target, exist_ok=True)
    return {"status": "ok"}

@app.post("/api/fs/delete")
def fs_delete(path: str = Form(...)):
    target = get_safe_path(path)
    if os.path.isdir(target): shutil.rmtree(target)
    else: os.remove(target)
    return {"status": "ok"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860, log_level="warning")