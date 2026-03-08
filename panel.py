#!/usr/bin/env python3
"""
OSP Panel — Minecraft Server Management Panel
Single-file deployment for HuggingFace Docker Spaces.

Required HF Secrets:
  HF_USERNAME    — Panel login username
  HF_PASSWORD    — Panel login password
  SERVER_ZIP_URL — Google Drive share link to server zip (optional)

Usage:
  pip install fastapi uvicorn python-multipart
  python app.py
"""

import os, sys, asyncio, collections, shutil, urllib.request, json, time, re, secrets, hashlib
import tarfile, zipfile, threading
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import (
    FastAPI, WebSocket, WebSocketDisconnect, Form, UploadFile, File,
    HTTPException, Request, Response, Depends, Cookie
)
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════════
app = FastAPI(title="OSP Panel", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"]
)

BASE_DIR       = os.environ.get("SERVER_DIR", "/app")
PLUGINS_DIR    = os.path.join(BASE_DIR, "plugins")
BACKUPS_DIR    = os.path.join(BASE_DIR, "backups")
PANEL_CFG      = os.path.join(BASE_DIR, "panel.json")
EULA_PATH      = os.path.join(BASE_DIR, "eula.txt")
STORAGE_LIMIT  = 20 * 1024 * 1024 * 1024  # 20 GB software limit

HF_USERNAME    = os.environ.get("HF_USERNAME", "admin")
HF_PASSWORD    = os.environ.get("HF_PASSWORD", "admin")
SERVER_ZIP_URL = os.environ.get("SERVER_ZIP_URL", "")

mc_process: Optional[asyncio.subprocess.Process] = None
output_history   = collections.deque(maxlen=1000)
connected_clients: set = set()
server_start_time: Optional[float] = None
active_sessions: dict = {}  # token -> expiry

schedule_tasks: dict = {}  # schedule_id -> asyncio.Task

# ═══════════════════════════════════════════════════════════════════════════════
# PANEL.JSON PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════════════
DEFAULT_PANEL = {
    "theme": "dark",
    "accent": "blue",
    "fontSize": "default",
    "reducedMotion": False,
    "compactMode": False,
    "serverAddress": "",
    "serverPort": "25565",
    "schedules": [],
    "backups": {
        "gdrive_enabled": False,
        "gdrive_client_id": "",
        "gdrive_client_secret": "",
        "gdrive_refresh_token": "",
        "gdrive_folder_id": ""
    }
}

def load_panel() -> dict:
    if os.path.isfile(PANEL_CFG):
        try:
            with open(PANEL_CFG) as f:
                data = json.load(f)
            merged = {**DEFAULT_PANEL, **data}
            if "backups" not in merged or not isinstance(merged["backups"], dict):
                merged["backups"] = DEFAULT_PANEL["backups"]
            return merged
        except:
            pass
    return dict(DEFAULT_PANEL)

def save_panel(cfg: dict):
    with open(PANEL_CFG, "w") as f:
        json.dump(cfg, f, indent=2)

# ═══════════════════════════════════════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════════════════════════════════════
def create_session(remember: bool = False) -> tuple:
    token = secrets.token_hex(32)
    expiry = time.time() + (30 * 86400 if remember else 86400)
    active_sessions[token] = expiry
    return token, expiry

def verify_session(token: str) -> bool:
    if not token or token not in active_sessions:
        return False
    if time.time() > active_sessions[token]:
        del active_sessions[token]
        return False
    return True

async def require_auth(request: Request):
    token = request.cookies.get("osp_session")
    if not verify_session(token):
        raise HTTPException(401, "Unauthorized")

# ═══════════════════════════════════════════════════════════════════════════════
# PATH SAFETY
# ═══════════════════════════════════════════════════════════════════════════════
def safe_path(p: str) -> str:
    clean = os.path.normpath((p or "").strip("/")).replace("..", "")
    full = os.path.abspath(os.path.join(BASE_DIR, clean))
    if not full.startswith(os.path.abspath(BASE_DIR)):
        raise HTTPException(403, "Access denied")
    return full

# ═══════════════════════════════════════════════════════════════════════════════
# STORAGE USAGE
# ═══════════════════════════════════════════════════════════════════════════════
def get_dir_size(path: str) -> int:
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            try:
                total += os.path.getsize(fp)
            except:
                pass
    return total

# ═══════════════════════════════════════════════════════════════════════════════
# GOOGLE DRIVE HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def gdrive_download(share_url: str, dest_path: str):
    """Download file from Google Drive share link."""
    file_id = None
    patterns = [
        r'/file/d/([a-zA-Z0-9_-]+)',
        r'id=([a-zA-Z0-9_-]+)',
        r'/d/([a-zA-Z0-9_-]+)',
    ]
    for pat in patterns:
        m = re.search(pat, share_url)
        if m:
            file_id = m.group(1)
            break
    if not file_id:
        raise Exception(f"Cannot extract file ID from: {share_url}")

    url = f"https://drive.google.com/uc?export=download&id={file_id}&confirm=t"
    req = urllib.request.Request(url, headers={"User-Agent": "OSPPanel/1.0"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        with open(dest_path, "wb") as f:
            shutil.copyfileobj(resp, f)

def gdrive_upload(file_path: str, cfg: dict) -> bool:
    """Upload file to Google Drive using refresh token."""
    try:
        # Get access token
        token_url = "https://oauth2.googleapis.com/token"
        token_data = urllib.parse.urlencode({
            "client_id": cfg.get("gdrive_client_id", ""),
            "client_secret": cfg.get("gdrive_client_secret", ""),
            "refresh_token": cfg.get("gdrive_refresh_token", ""),
            "grant_type": "refresh_token"
        }).encode()
        req = urllib.request.Request(token_url, data=token_data, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            token_resp = json.loads(resp.read())
        access_token = token_resp["access_token"]

        filename = os.path.basename(file_path)
        filesize = os.path.getsize(file_path)
        folder_id = cfg.get("gdrive_folder_id", "")

        metadata = {"name": filename}
        if folder_id:
            metadata["parents"] = [folder_id]

        # Simple upload for files < 5MB, resumable for larger
        if filesize < 5 * 1024 * 1024:
            import email.mime.multipart
            boundary = "----OSPBoundary"
            meta_json = json.dumps(metadata)
            with open(file_path, "rb") as f:
                file_data = f.read()
            body = (
                f"--{boundary}\r\n"
                f"Content-Type: application/json; charset=UTF-8\r\n\r\n"
                f"{meta_json}\r\n"
                f"--{boundary}\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n"
            ).encode() + file_data + f"\r\n--{boundary}--".encode()
            req = urllib.request.Request(
                "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart",
                data=body,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": f"multipart/related; boundary={boundary}"
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                resp.read()
        else:
            # Resumable upload
            meta_json = json.dumps(metadata).encode()
            req = urllib.request.Request(
                "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable",
                data=meta_json,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json; charset=UTF-8",
                    "X-Upload-Content-Length": str(filesize)
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                upload_url = resp.headers.get("Location")
            with open(file_path, "rb") as f:
                data = f.read()
            req2 = urllib.request.Request(
                upload_url, data=data,
                headers={"Content-Length": str(filesize)},
                method="PUT"
            )
            with urllib.request.urlopen(req2, timeout=600) as resp:
                resp.read()
        return True
    except Exception as e:
        output_history.append(f"[Panel] GDrive upload failed: {e}")
        return False

# ═══════════════════════════════════════════════════════════════════════════════
# MC PROCESS MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════
async def stream_output(pipe):
    while True:
        line = await pipe.readline()
        if not line:
            break
        txt = line.decode("utf-8", errors="replace").rstrip()
        # Strip ANSI codes for clean output
        txt_clean = re.sub(r'\x1b\[[0-9;]*m', '', txt)
        output_history.append(txt_clean)
        dead = set()
        for c in connected_clients:
            try:
                await c.send_text(txt_clean)
            except:
                dead.add(c)
        connected_clients.difference_update(dead)

async def boot_mc():
    global mc_process, server_start_time
    jar = None
    for candidate in ("purpur.jar", "paper.jar", "server.jar"):
        p = os.path.join(BASE_DIR, candidate)
        if os.path.exists(p):
            jar = p
            break
    if not jar:
        output_history.append("[Panel] No server jar found. Upload one via Files or install via Plugins.")
        return

    # Accept EULA
    with open(EULA_PATH, "w") as f:
        f.write("eula=true\n")

    server_start_time = time.time()
    output_history.append(f"[Panel] Starting {os.path.basename(jar)}...")
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
    output_history.append("[Panel] Server process exited.")

async def download_server_zip():
    """Download and extract server zip from SERVER_ZIP_URL on first boot."""
    if not SERVER_ZIP_URL:
        return
    marker = os.path.join(BASE_DIR, ".osp_initialized")
    if os.path.exists(marker):
        return
    output_history.append(f"[Panel] Downloading server files from configured URL...")
    try:
        zip_path = os.path.join(BASE_DIR, "_server_download.zip")
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, gdrive_download, SERVER_ZIP_URL, zip_path)
        output_history.append("[Panel] Extracting server files...")
        if zipfile.is_zipfile(zip_path):
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(BASE_DIR)
        elif tarfile.is_tarfile(zip_path):
            with tarfile.open(zip_path) as tf:
                tf.extractall(BASE_DIR)
        os.remove(zip_path)
        with open(marker, "w") as f:
            f.write(str(time.time()))
        output_history.append("[Panel] Server files extracted successfully.")
    except Exception as e:
        output_history.append(f"[Panel] Download failed: {e}")

# ═══════════════════════════════════════════════════════════════════════════════
# SCHEDULES
# ═══════════════════════════════════════════════════════════════════════════════
async def run_schedule(schedule: dict):
    """Background task that runs a schedule repeatedly."""
    while True:
        try:
            stype = schedule.get("type", "interval")
            if stype == "interval":
                hours = int(schedule.get("intervalHours", 1))
                mins = int(schedule.get("intervalMinutes", 0))
                await asyncio.sleep(hours * 3600 + mins * 60)
            elif stype == "daily":
                # Wait until next occurrence of HH:MM
                target = schedule.get("time", "00:00")
                h, m = map(int, target.split(":"))
                now = datetime.now()
                target_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
                if target_dt <= now:
                    target_dt = target_dt.replace(day=target_dt.day + 1)
                wait = (target_dt - now).total_seconds()
                await asyncio.sleep(max(wait, 60))
            elif stype == "weekly":
                await asyncio.sleep(7 * 86400)
            else:
                await asyncio.sleep(3600)

            if not schedule.get("enabled", True):
                continue

            tasks = schedule.get("tasks", [])
            for task in tasks:
                action = task.get("action", "")
                if action == "command" and mc_process and mc_process.returncode is None:
                    cmd = task.get("payload", "")
                    if cmd:
                        mc_process.stdin.write((cmd + "\n").encode())
                        await mc_process.stdin.drain()
                        output_history.append(f"[Schedule:{schedule.get('name','')}] {cmd}")
                elif action == "restart":
                    if mc_process and mc_process.returncode is None:
                        mc_process.stdin.write(b"stop\n")
                        await mc_process.stdin.drain()
                        await asyncio.sleep(5)
                    asyncio.create_task(boot_mc())
                    output_history.append(f"[Schedule:{schedule.get('name','')}] Restarted server")
                elif action == "backup":
                    await asyncio.get_event_loop().run_in_executor(None, create_backup_sync, f"auto-{schedule.get('name','schedule')}")
                    output_history.append(f"[Schedule:{schedule.get('name','')}] Created backup")
        except asyncio.CancelledError:
            break
        except Exception as e:
            output_history.append(f"[Schedule Error] {e}")
            await asyncio.sleep(60)

def start_schedules():
    """Start all enabled schedules from panel.json."""
    global schedule_tasks
    # Cancel existing
    for tid, task in schedule_tasks.items():
        task.cancel()
    schedule_tasks.clear()

    cfg = load_panel()
    for sched in cfg.get("schedules", []):
        if sched.get("enabled", True):
            sid = sched.get("id", secrets.token_hex(4))
            schedule_tasks[sid] = asyncio.create_task(run_schedule(sched))

# ═══════════════════════════════════════════════════════════════════════════════
# BACKUP HELPERS
# ═══════════════════════════════════════════════════════════════════════════════
def create_backup_sync(name: str) -> dict:
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', name)
    filename = f"{safe_name}_{ts}.tar.gz"
    filepath = os.path.join(BACKUPS_DIR, filename)

    with tarfile.open(filepath, "w:gz") as tar:
        for item in os.listdir(BASE_DIR):
            if item in ("backups", "_server_download.zip", ".osp_initialized"):
                continue
            tar.add(os.path.join(BASE_DIR, item), arcname=item)

    size = os.path.getsize(filepath)

    # Update backups list in panel.json
    cfg = load_panel()
    if "backup_list" not in cfg:
        cfg["backup_list"] = []
    cfg["backup_list"].append({
        "id": secrets.token_hex(4),
        "name": name,
        "filename": filename,
        "size": size,
        "date": datetime.now().isoformat(),
        "locked": False,
        "gdrive": False
    })
    save_panel(cfg)

    # Optional GDrive upload
    bcfg = cfg.get("backups", {})
    if bcfg.get("gdrive_enabled") and bcfg.get("gdrive_refresh_token"):
        threading.Thread(target=gdrive_upload, args=(filepath, bcfg), daemon=True).start()

    return {"ok": True, "filename": filename, "size": size}

# ═══════════════════════════════════════════════════════════════════════════════
# STARTUP
# ═══════════════════════════════════════════════════════════════════════════════
@app.on_event("startup")
async def on_start():
    os.makedirs(BASE_DIR, exist_ok=True)
    os.makedirs(PLUGINS_DIR, exist_ok=True)
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    await download_server_zip()
    asyncio.create_task(boot_mc())
    # Start schedules after a brief delay
    await asyncio.sleep(2)
    start_schedules()

# ═══════════════════════════════════════════════════════════════════════════════
# AUTH ROUTES
# ═══════════════════════════════════════════════════════════════════════════════
@app.post("/api/auth/login")
async def auth_login(username: str = Form(...), password: str = Form(...), remember: str = Form("0")):
    if username != HF_USERNAME or password != HF_PASSWORD:
        raise HTTPException(401, "Invalid credentials")
    token, expiry = create_session(remember == "1")
    resp = JSONResponse({"ok": True})
    max_age = 30 * 86400 if remember == "1" else 86400
    resp.set_cookie("osp_session", token, max_age=max_age, httponly=True, samesite="lax")
    return resp

@app.post("/api/auth/logout")
async def auth_logout(request: Request):
    token = request.cookies.get("osp_session")
    if token and token in active_sessions:
        del active_sessions[token]
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("osp_session")
    return resp

@app.get("/api/auth/check")
async def auth_check(request: Request):
    token = request.cookies.get("osp_session")
    return {"authenticated": verify_session(token)}

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN PAGE
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/")
async def index(request: Request):
    return HTMLResponse(HTML_CONTENT)

# ═══════════════════════════════════════════════════════════════════════════════
# WEBSOCKET
# ═══════════════════════════════════════════════════════════════════════════════
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    # Check auth from cookie
    token = ws.cookies.get("osp_session")
    if not verify_session(token):
        await ws.close(code=4001, reason="Unauthorized")
        return
    connected_clients.add(ws)
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

@app.get("/api/console/history", dependencies=[Depends(require_auth)])
def console_history():
    return list(output_history)

# ═══════════════════════════════════════════════════════════════════════════════
# SERVER STATUS & CONTROL
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/server/status", dependencies=[Depends(require_auth)])
def server_status():
    running = mc_process is not None and mc_process.returncode is None
    uptime_str = "—"
    if server_start_time and running:
        secs = int(time.time() - server_start_time)
        h, r = divmod(secs, 3600)
        m, s = divmod(r, 60)
        uptime_str = f"{h}h {m}m" if h else f"{m}m {s}s"

    # Storage with 20GB limit
    disk_used = get_dir_size(BASE_DIR)
    disk_pct = min(100, round(disk_used / STORAGE_LIMIT * 100))

    active_jar = None
    for c in ("purpur.jar", "paper.jar", "server.jar"):
        if os.path.exists(os.path.join(BASE_DIR, c)):
            active_jar = c
            break

    # MC version from server.properties or jar name
    mc_ver = "Unknown"
    props_path = os.path.join(BASE_DIR, "server.properties")
    if os.path.isfile(props_path):
        try:
            with open(props_path) as f:
                for line in f:
                    if line.startswith("# Minecraft server"):
                        mc_ver = line.strip()
                        break
        except:
            pass

    cfg = load_panel()
    return {
        "running": running,
        "uptime": uptime_str,
        "storage_used": disk_used,
        "storage_total": STORAGE_LIMIT,
        "storage_pct": disk_pct,
        "active_jar": active_jar,
        "mc_version": mc_ver,
        "server_name": cfg.get("serverName", "Minecraft Server"),
        "address": cfg.get("serverAddress", "")
    }

@app.post("/api/server/{action}", dependencies=[Depends(require_auth)])
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
                await asyncio.sleep(5)
            except:
                pass
        asyncio.create_task(boot_mc())
    elif action == "kill":
        if mc_process and mc_process.returncode is None:
            mc_process.kill()
    return {"ok": True}

# ═══════════════════════════════════════════════════════════════════════════════
# FILE SYSTEM API
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/fs/list", dependencies=[Depends(require_auth)])
def fs_list(path: str = ""):
    target = safe_path(path)
    if not os.path.isdir(target):
        raise HTTPException(404, "Not a directory")
    items = []
    for name in os.listdir(target):
        fp = os.path.join(target, name)
        try:
            st = os.stat(fp)
            items.append({
                "name": name,
                "is_dir": os.path.isdir(fp),
                "size": st.st_size if not os.path.isdir(fp) else -1,
                "mtime": int(st.st_mtime)
            })
        except:
            pass
    return sorted(items, key=lambda x: (not x["is_dir"], x["name"].lower()))

@app.get("/api/fs/read", dependencies=[Depends(require_auth)])
def fs_read(path: str):
    target = safe_path(path)
    if not os.path.isfile(target):
        raise HTTPException(404, "File not found")
    try:
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return Response(content, media_type="text/plain; charset=utf-8")
    except:
        raise HTTPException(500, "Cannot read file")

@app.get("/api/fs/download", dependencies=[Depends(require_auth)])
def fs_download(path: str):
    target = safe_path(path)
    if not os.path.isfile(target):
        raise HTTPException(404, "File not found")
    return FileResponse(target, filename=os.path.basename(target))

@app.post("/api/fs/write", dependencies=[Depends(require_auth)])
async def fs_write(path: str = Form(...), content: str = Form(...)):
    target = safe_path(path)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write(content)
    return {"ok": True}

@app.post("/api/fs/upload", dependencies=[Depends(require_auth)])
async def fs_upload(path: str = Form(""), file: UploadFile = File(...)):
    target_dir = safe_path(path)
    os.makedirs(target_dir, exist_ok=True)
    dest = os.path.join(target_dir, file.filename)
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"ok": True}

@app.post("/api/fs/delete", dependencies=[Depends(require_auth)])
def fs_delete(path: str = Form(...)):
    target = safe_path(path)
    if not os.path.exists(target):
        raise HTTPException(404, "Not found")
    if os.path.isdir(target):
        shutil.rmtree(target)
    else:
        os.remove(target)
    return {"ok": True}

@app.post("/api/fs/rename", dependencies=[Depends(require_auth)])
def fs_rename(old_path: str = Form(...), new_path: str = Form(...)):
    src = safe_path(old_path)
    dst = safe_path(new_path)
    if not os.path.exists(src):
        raise HTTPException(404, "Source not found")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.move(src, dst)
    return {"ok": True}

@app.post("/api/fs/create", dependencies=[Depends(require_auth)])
def fs_create(path: str = Form(...), is_dir: str = Form("0")):
    target = safe_path(path)
    if is_dir == "1":
        os.makedirs(target, exist_ok=True)
    else:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if not os.path.exists(target):
            open(target, "w").close()
    return {"ok": True}

@app.post("/api/fs/zip", dependencies=[Depends(require_auth)])
def fs_zip(path: str = Form(...)):
    target = safe_path(path)
    if not os.path.exists(target):
        raise HTTPException(404, "Not found")
    zip_path = target + ".zip" if os.path.isdir(target) else target.rsplit(".", 1)[0] + ".zip"
    if os.path.isdir(target):
        shutil.make_archive(target, 'zip', target)
    else:
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.write(target, os.path.basename(target))
    return {"ok": True, "path": zip_path}

@app.post("/api/fs/unzip", dependencies=[Depends(require_auth)])
def fs_unzip(path: str = Form(...)):
    target = safe_path(path)
    if not os.path.isfile(target):
        raise HTTPException(404, "File not found")
    extract_dir = target.rsplit(".", 1)[0]
    os.makedirs(extract_dir, exist_ok=True)
    if zipfile.is_zipfile(target):
        with zipfile.ZipFile(target, 'r') as zf:
            zf.extractall(extract_dir)
    elif tarfile.is_tarfile(target):
        with tarfile.open(target) as tf:
            tf.extractall(extract_dir)
    else:
        raise HTTPException(400, "Not a recognized archive")
    return {"ok": True}

# ═══════════════════════════════════════════════════════════════════════════════
# PLUGIN INSTALLER
# ═══════════════════════════════════════════════════════════════════════════════
@app.post("/api/plugins/install", dependencies=[Depends(require_auth)])
async def plugins_install(
    url: str = Form(...),
    filename: str = Form(...),
    project_id: str = Form(...),
    version_id: str = Form(...),
    name: str = Form(...)
):
    dest = os.path.join(PLUGINS_DIR, filename)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "OSPPanel/1.0"})
        loop = asyncio.get_event_loop()
        def dl():
            with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
                shutil.copyfileobj(resp, f)
        await loop.run_in_executor(None, dl)
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
        "name": name,
        "filename": filename,
        "version_id": version_id,
        "installed_at": time.time()
    }
    with open(record_path, "w") as f:
        json.dump(data, f, indent=2)
    return {"ok": True}

@app.get("/api/plugins/installed", dependencies=[Depends(require_auth)])
def plugins_installed():
    record_path = os.path.join(PLUGINS_DIR, "plugins.json")
    if not os.path.isfile(record_path):
        return {}
    try:
        with open(record_path) as f:
            return json.load(f)
    except:
        return {}

@app.post("/api/plugins/uninstall", dependencies=[Depends(require_auth)])
def plugins_uninstall(project_id: str = Form(...)):
    record_path = os.path.join(PLUGINS_DIR, "plugins.json")
    data = {}
    if os.path.exists(record_path):
        try:
            with open(record_path) as f:
                data = json.load(f)
        except:
            pass
    if project_id in data:
        fname = data[project_id].get("filename", "")
        fpath = os.path.join(PLUGINS_DIR, fname)
        if os.path.isfile(fpath):
            os.remove(fpath)
        del data[project_id]
        with open(record_path, "w") as f:
            json.dump(data, f, indent=2)
    return {"ok": True}

# ═══════════════════════════════════════════════════════════════════════════════
# SETTINGS API
# ═══════════════════════════════════════════════════════════════════════════════
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
    lines = ["# Managed by OSP Panel\n"]
    for k, v in sorted(props.items()):
        lines.append(f"{k}={v}\n")
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)

@app.get("/api/settings/properties", dependencies=[Depends(require_auth)])
def get_properties():
    return _parse_properties(os.path.join(BASE_DIR, "server.properties"))

@app.post("/api/settings/properties", dependencies=[Depends(require_auth)])
async def save_properties(data: str = Form(...)):
    path = os.path.join(BASE_DIR, "server.properties")
    try:
        props = json.loads(data)
        _write_properties(path, props)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/api/settings/panel", dependencies=[Depends(require_auth)])
def get_panel_config():
    return load_panel()

@app.post("/api/settings/panel", dependencies=[Depends(require_auth)])
async def save_panel_config(data: str = Form(...)):
    try:
        cfg = json.loads(data)
        save_panel(cfg)
        start_schedules()  # Restart schedules on config save
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, str(e))

# ═══════════════════════════════════════════════════════════════════════════════
# BACKUPS API
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/backups/list", dependencies=[Depends(require_auth)])
def backups_list():
    cfg = load_panel()
    return cfg.get("backup_list", [])

@app.post("/api/backups/create", dependencies=[Depends(require_auth)])
async def backups_create(name: str = Form("Manual Backup")):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, create_backup_sync, name)
    return result

@app.post("/api/backups/delete", dependencies=[Depends(require_auth)])
def backups_delete(backup_id: str = Form(...)):
    cfg = load_panel()
    bl = cfg.get("backup_list", [])
    backup = next((b for b in bl if b["id"] == backup_id), None)
    if not backup:
        raise HTTPException(404, "Backup not found")
    if backup.get("locked"):
        raise HTTPException(400, "Backup is locked")
    fpath = os.path.join(BACKUPS_DIR, backup["filename"])
    if os.path.isfile(fpath):
        os.remove(fpath)
    cfg["backup_list"] = [b for b in bl if b["id"] != backup_id]
    save_panel(cfg)
    return {"ok": True}

@app.post("/api/backups/restore", dependencies=[Depends(require_auth)])
async def backups_restore(backup_id: str = Form(...)):
    cfg = load_panel()
    bl = cfg.get("backup_list", [])
    backup = next((b for b in bl if b["id"] == backup_id), None)
    if not backup:
        raise HTTPException(404, "Backup not found")
    fpath = os.path.join(BACKUPS_DIR, backup["filename"])
    if not os.path.isfile(fpath):
        raise HTTPException(404, "Backup file missing")

    # Stop server first
    global mc_process
    if mc_process and mc_process.returncode is None:
        try:
            mc_process.stdin.write(b"stop\n")
            await mc_process.stdin.drain()
            await asyncio.sleep(5)
        except:
            mc_process.kill()

    # Extract backup
    def do_restore():
        with tarfile.open(fpath, "r:gz") as tf:
            tf.extractall(BASE_DIR)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, do_restore)
    output_history.append(f"[Panel] Restored backup: {backup['name']}")

    # Restart server
    asyncio.create_task(boot_mc())
    return {"ok": True}

@app.post("/api/backups/lock", dependencies=[Depends(require_auth)])
def backups_lock(backup_id: str = Form(...)):
    cfg = load_panel()
    bl = cfg.get("backup_list", [])
    for b in bl:
        if b["id"] == backup_id:
            b["locked"] = not b.get("locked", False)
            break
    save_panel(cfg)
    return {"ok": True}

@app.get("/api/backups/download", dependencies=[Depends(require_auth)])
def backups_download(backup_id: str):
    cfg = load_panel()
    bl = cfg.get("backup_list", [])
    backup = next((b for b in bl if b["id"] == backup_id), None)
    if not backup:
        raise HTTPException(404, "Backup not found")
    fpath = os.path.join(BACKUPS_DIR, backup["filename"])
    if not os.path.isfile(fpath):
        raise HTTPException(404, "File missing")
    return FileResponse(fpath, filename=backup["filename"])

@app.post("/api/backups/gdrive-upload", dependencies=[Depends(require_auth)])
async def backups_gdrive_upload(backup_id: str = Form(...)):
    cfg = load_panel()
    bcfg = cfg.get("backups", {})
    if not bcfg.get("gdrive_enabled") or not bcfg.get("gdrive_refresh_token"):
        raise HTTPException(400, "Google Drive not configured")
    bl = cfg.get("backup_list", [])
    backup = next((b for b in bl if b["id"] == backup_id), None)
    if not backup:
        raise HTTPException(404, "Backup not found")
    fpath = os.path.join(BACKUPS_DIR, backup["filename"])
    if not os.path.isfile(fpath):
        raise HTTPException(404, "File missing")
    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, gdrive_upload, fpath, bcfg)
    if ok:
        for b in bl:
            if b["id"] == backup_id:
                b["gdrive"] = True
        save_panel(cfg)
        return {"ok": True}
    raise HTTPException(500, "Upload failed")

# ═══════════════════════════════════════════════════════════════════════════════
# SCHEDULES API
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/schedules/list", dependencies=[Depends(require_auth)])
def schedules_list():
    cfg = load_panel()
    return cfg.get("schedules", [])

@app.post("/api/schedules/save", dependencies=[Depends(require_auth)])
async def schedules_save(data: str = Form(...)):
    cfg = load_panel()
    cfg["schedules"] = json.loads(data)
    save_panel(cfg)
    start_schedules()
    return {"ok": True}

# ═══════════════════════════════════════════════════════════════════════════════
# SOFTWARE INSTALLER
# ═══════════════════════════════════════════════════════════════════════════════
@app.post("/api/software/install", dependencies=[Depends(require_auth)])
async def software_install(type: str = Form(...), version: str = Form(...)):
    dest = os.path.join(BASE_DIR, "server.jar")
    for candidate in ("purpur.jar", "paper.jar", "server.jar"):
        p = os.path.join(BASE_DIR, candidate)
        if os.path.exists(p):
            shutil.copy2(p, p + ".bak")
    try:
        dl_url = None
        if type == "paper":
            builds_url = f"https://api.papermc.io/v2/projects/paper/versions/{version}/builds"
            with urllib.request.urlopen(builds_url, timeout=15) as r:
                builds_data = json.loads(r.read())
            latest_build = builds_data["builds"][-1]["build"]
            jar_name = f"paper-{version}-{latest_build}.jar"
            dl_url = f"https://api.papermc.io/v2/projects/paper/versions/{version}/builds/{latest_build}/downloads/{jar_name}"
        elif type == "purpur":
            dl_url = f"https://api.purpurmc.org/v2/purpur/{version}/latest/download"
        elif type == "vanilla":
            with urllib.request.urlopen("https://launchermeta.mojang.com/mc/game/version_manifest.json", timeout=15) as r:
                manifest = json.loads(r.read())
            ver_info = next((v for v in manifest["versions"] if v["id"] == version), None)
            if not ver_info:
                raise HTTPException(404, f"Version {version} not found")
            with urllib.request.urlopen(ver_info["url"], timeout=15) as r:
                ver_data = json.loads(r.read())
            dl_url = ver_data["downloads"]["server"]["url"]
        elif type == "fabric":
            with urllib.request.urlopen("https://meta.fabricmc.net/v2/versions/loader", timeout=10) as r:
                loaders = json.loads(r.read())
            with urllib.request.urlopen("https://meta.fabricmc.net/v2/versions/installer", timeout=10) as r:
                installers = json.loads(r.read())
            dl_url = f"https://meta.fabricmc.net/v2/versions/loader/{version}/{loaders[0]['version']}/{installers[0]['version']}/server/jar"
        else:
            raise HTTPException(400, f"Unsupported: {type}")
        def do_download():
            req = urllib.request.Request(dl_url, headers={"User-Agent": "OSPPanel/1.0"})
            with urllib.request.urlopen(req, timeout=300) as resp, open(dest, "wb") as f:
                shutil.copyfileobj(resp, f)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, do_download)
        output_history.append(f"[Panel] Installed {type} {version} → server.jar")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))

# ═══════════════════════════════════════════════════════════════════════════════
# HTML FRONTEND
# ═══════════════════════════════════════════════════════════════════════════════
HTML_CONTENT = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>OSP Panel</title>
<meta name="description" content="Minecraft Server Management Panel">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:hsl(0,0%,5%);--bg2:hsl(0,0%,9%);--bg3:hsl(0,0%,13%);--bg4:hsl(0,0%,15%);
  --fg:hsl(0,0%,93%);--fg2:hsl(0,0%,80%);--fg3:hsl(0,0%,55%);
  --primary:hsl(211,100%,50%);--primary-fg:#fff;
  --border:hsl(0,0%,15%);
  --success:hsl(142,71%,45%);--warning:hsl(38,92%,50%);--destructive:hsl(0,72%,51%);
  --radius:0.75rem;--sidebar-w:256px;
  --font:'Inter',-apple-system,BlinkMacSystemFont,sans-serif;
  --mono:'SF Mono','Fira Code','Consolas',monospace;
}
html{font-size:16px}
body{font-family:var(--font);background:var(--bg);color:var(--fg);-webkit-font-smoothing:antialiased;overflow:hidden;height:100vh}
::-webkit-scrollbar{width:6px;height:6px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:hsl(0,0%,25%);border-radius:3px}
::-webkit-scrollbar-thumb:hover{background:hsl(0,0%,35%)}
a{color:var(--primary);text-decoration:none}
input,textarea,select,button{font-family:var(--font)}

/* ── LOGIN ── */
.login-wrap{min-height:100vh;display:flex;align-items:center;justify-content:center;padding:16px}
.login-box{width:100%;max-width:360px}
.login-icon{width:64px;height:64px;border-radius:18px;background:hsla(211,100%,50%,0.1);border:1px solid hsla(211,100%,50%,0.2);display:flex;align-items:center;justify-content:center;margin:0 auto 20px;font-size:28px;color:var(--primary)}
.login-title{text-align:center;font-size:24px;font-weight:600;letter-spacing:-0.02em}
.login-sub{text-align:center;font-size:14px;color:var(--fg3);margin-top:6px;margin-bottom:32px}
.form-label{display:block;font-size:12px;font-weight:500;color:var(--fg3);margin-bottom:6px}
.form-input{width:100%;background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:10px 14px;color:var(--fg);font-size:14px;outline:none;transition:border-color .2s}
.form-input:focus{border-color:hsla(211,100%,50%,0.5)}
.form-input::placeholder{color:var(--fg3)}
.form-group{margin-bottom:14px}
.pass-wrap{position:relative}
.pass-toggle{position:absolute;right:12px;top:50%;transform:translateY(-50%);background:none;border:none;color:var(--fg3);cursor:pointer;font-size:14px}
.pass-toggle:hover{color:var(--fg)}
.login-check{display:flex;align-items:center;gap:8px;margin-bottom:24px}
.toggle-sm{width:34px;height:20px;border-radius:10px;background:var(--bg3);border:1px solid var(--border);position:relative;cursor:pointer;transition:all .2s;flex-shrink:0}
.toggle-sm.on{background:var(--primary);border-color:var(--primary)}
.toggle-sm::after{content:'';position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;background:#fff;transition:transform .2s;box-shadow:0 1px 3px rgba(0,0,0,.3)}
.toggle-sm.on::after{transform:translateX(14px)}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;border:none;border-radius:8px;font-size:14px;font-weight:500;cursor:pointer;transition:all .2s;padding:10px 16px}
.btn:active{transform:scale(0.97)}
.btn-primary{background:var(--primary);color:#fff}
.btn-primary:hover{filter:brightness(1.1)}
.btn-secondary{background:var(--bg3);color:var(--fg);border:1px solid var(--border)}
.btn-secondary:hover{background:var(--bg4)}
.btn-danger{background:var(--destructive);color:#fff}
.btn-danger:hover{filter:brightness(1.1)}
.btn-ghost{background:transparent;color:var(--fg3);padding:8px 12px}
.btn-ghost:hover{background:var(--bg4);color:var(--fg)}
.btn-sm{padding:6px 12px;font-size:12px;border-radius:6px}
.btn-full{width:100%;padding:12px}
.login-error{display:flex;align-items:center;gap:8px;background:hsla(0,72%,51%,0.1);border:1px solid hsla(0,72%,51%,0.2);color:var(--destructive);font-size:12px;font-weight:500;border-radius:8px;padding:10px 14px;margin-bottom:16px}
.login-footer{text-align:center;font-size:11px;color:hsla(0,0%,55%,0.5);margin-top:32px}

/* ── LAYOUT ── */
.app{display:flex;height:100vh;overflow:hidden}
.sidebar{width:var(--sidebar-w);min-width:var(--sidebar-w);height:100vh;background:hsl(0,0%,7%);border-right:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden;flex-shrink:0}
.sb-header{padding:20px 16px 12px;display:flex;align-items:center;gap:10px}
.sb-logo{font-size:16px;font-weight:700;letter-spacing:-0.02em}
.sb-logo i{color:var(--primary);margin-right:6px}
.sb-nav{flex:1;overflow-y:auto;padding:8px}
.nav-item{display:flex;align-items:center;gap:12px;padding:10px 12px;border-radius:8px;font-size:14px;font-weight:500;color:var(--fg3);cursor:pointer;transition:all .15s;margin-bottom:2px}
.nav-item:hover{background:var(--bg4);color:var(--fg)}
.nav-item.active{color:var(--primary);background:hsla(211,100%,50%,0.1)}
.nav-item i{width:18px;text-align:center;font-size:14px}
.sb-footer{padding:12px 16px;border-top:1px solid var(--border)}
.sb-footer .btn{width:100%;justify-content:flex-start}
.main{flex:1;display:flex;flex-direction:column;overflow:hidden}
.m-header{display:none;height:52px;background:var(--bg2);border-bottom:1px solid var(--border);align-items:center;padding:0 14px;gap:12px;flex-shrink:0}
.m-header .ham{width:36px;height:36px;border-radius:8px;border:none;background:transparent;color:var(--fg);cursor:pointer;font-size:16px;display:flex;align-items:center;justify-content:center}
.m-header .m-title{font-size:15px;font-weight:600;flex:1}
.m-header .m-dot{width:8px;height:8px;border-radius:50%;background:var(--success);box-shadow:0 0 8px var(--success)}
.content{flex:1;overflow-y:auto;overflow-x:hidden}
.page{max-width:960px;margin:0 auto;padding:20px 24px;display:flex;flex-direction:column;gap:16px}
.page-header{display:flex;align-items:center;justify-content:space-between}
.page-title{font-size:20px;font-weight:600;letter-spacing:-0.02em}
.card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--radius);padding:16px}
.overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:90}
.overlay.on{display:block}
.m-bottom-nav{display:none;position:fixed;bottom:0;left:0;right:0;background:var(--bg2);border-top:1px solid var(--border);padding:6px 0 env(safe-area-inset-bottom);z-index:80}
.m-bottom-nav-inner{display:flex;justify-content:space-around;align-items:center}
.m-nav-btn{display:flex;flex-direction:column;align-items:center;gap:2px;padding:6px 0;color:var(--fg3);font-size:10px;cursor:pointer;border:none;background:none;min-width:48px}
.m-nav-btn.active{color:var(--primary)}
.m-nav-btn i{font-size:18px}

/* ── STATUS BAR ── */
.status-bar{padding:12px 16px;display:flex;align-items:center;justify-content:space-between}
.status-left{display:flex;align-items:center;gap:10px}
.status-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.status-dot.on{background:var(--success);box-shadow:0 0 8px var(--success)}
.status-dot.off{background:var(--fg3)}
.status-name{font-size:14px;font-weight:500}
.status-version{font-size:11px;color:var(--fg3)}
.status-uptime{font-size:11px;color:var(--fg3)}

/* ── CONSOLE ── */
.console-wrap{display:flex;flex-direction:column;overflow:hidden;border-radius:var(--radius);border:1px solid var(--border);background:var(--bg2)}
.console-output{flex:1;overflow-y:auto;padding:12px;font-family:var(--mono);font-size:11px;line-height:1.8;background:hsla(0,0%,3%,0.5);min-height:300px;max-height:calc(100vh - 300px)}
.c-line{white-space:pre-wrap;word-break:break-all}
.c-info{color:var(--fg2)}
.c-warn{color:var(--warning)}
.c-error{color:var(--destructive)}
.c-green{color:var(--success)}
.c-time{color:var(--fg3);margin-right:4px}
.console-input{display:flex;align-items:center;gap:8px;padding:8px 12px;border-top:1px solid var(--border);background:hsla(0,0%,5%,0.5)}
.console-input span{color:hsla(0,0%,55%,0.4);font-family:var(--mono);font-size:12px;user-select:none}
.console-input input{flex:1;background:transparent;border:none;color:var(--fg);font-family:var(--mono);font-size:12px;outline:none}
.console-input input::placeholder{color:hsla(0,0%,55%,0.4)}
.console-input button{padding:4px 8px}

/* ── STORAGE BAR ── */
.storage-bar{display:flex;align-items:center;gap:12px;padding:12px 16px}
.storage-bar i{color:var(--fg3);font-size:14px;flex-shrink:0}
.storage-info{flex:1}
.storage-labels{display:flex;justify-content:space-between;margin-bottom:4px}
.storage-labels span{font-size:11px;color:var(--fg3)}
.storage-labels .val{font-size:11px;font-weight:500;color:var(--fg)}
.progress-track{height:4px;background:var(--bg3);border-radius:2px;overflow:hidden}
.progress-fill{height:100%;border-radius:2px;background:var(--primary);transition:width .3s}
.progress-fill.danger{background:var(--destructive)}

/* ── POWER CONTROLS ── */
.power-row{display:flex;gap:8px}
.power-btn{flex:1;display:flex;align-items:center;justify-content:center;gap:8px;padding:10px;border-radius:var(--radius);font-size:14px;font-weight:500;cursor:pointer;border:none;transition:all .15s}
.power-btn:active{transform:scale(0.97)}
.power-btn.stop{background:hsla(0,72%,51%,0.1);color:var(--destructive)}
.power-btn.stop:hover{background:hsla(0,72%,51%,0.15)}
.power-btn.start{background:hsla(142,71%,45%,0.1);color:var(--success)}
.power-btn.start:hover{background:hsla(142,71%,45%,0.15)}
.power-btn.restart{background:var(--bg3);color:var(--fg);border:1px solid var(--border)}
.power-btn.restart:hover{background:var(--bg4)}

/* ── FILE MANAGER ── */
.fm-toolbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.breadcrumbs{display:flex;align-items:center;gap:4px;flex:1;min-width:0;overflow-x:auto;font-size:13px}
.crumb{color:var(--fg3);cursor:pointer;padding:4px 6px;border-radius:4px;white-space:nowrap;transition:all .1s}
.crumb:hover{background:var(--bg4);color:var(--fg)}
.crumb.now{color:var(--fg);cursor:default}
.crumb.now:hover{background:transparent}
.sep{color:var(--fg3);font-size:10px;opacity:.5}
.fm-list{border-radius:var(--radius);border:1px solid var(--border);overflow:hidden;background:var(--bg2)}
.fm-header{display:grid;grid-template-columns:1fr 100px 120px 40px;padding:8px 16px;font-size:11px;font-weight:600;color:var(--fg3);text-transform:uppercase;letter-spacing:0.05em;border-bottom:1px solid var(--border);background:var(--bg2)}
.fm-row{display:grid;grid-template-columns:1fr 100px 120px 40px;padding:8px 16px;align-items:center;border-bottom:1px solid hsla(0,0%,15%,0.3);cursor:pointer;transition:background .1s}
.fm-row:hover{background:var(--bg4)}
.fm-row:last-child{border-bottom:none}
.fm-name{display:flex;align-items:center;gap:10px;font-size:13px;min-width:0}
.fm-name i{font-size:16px;flex-shrink:0;width:20px;text-align:center}
.fm-name span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.fm-size,.fm-date{font-size:12px;color:var(--fg3)}
.fm-dot{width:28px;height:28px;border-radius:6px;border:none;background:transparent;color:var(--fg3);cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:14px;transition:all .1s}
.fm-dot:hover{background:var(--bg4);color:var(--fg)}

/* ── CONTEXT MENU ── */
.ctx-menu{position:fixed;z-index:200;background:var(--bg2);border:1px solid var(--border);border-radius:10px;box-shadow:0 8px 30px rgba(0,0,0,.5);overflow:hidden;min-width:180px;display:none}
.ctx-item{display:flex;align-items:center;gap:10px;padding:10px 14px;font-size:13px;color:var(--fg);cursor:pointer;transition:background .1s}
.ctx-item:hover{background:var(--bg4)}
.ctx-item i{width:16px;text-align:center;font-size:13px;color:var(--fg3)}
.ctx-item.danger{color:var(--destructive)}
.ctx-item.danger i{color:var(--destructive)}
.ctx-sep{height:1px;background:var(--border);margin:4px 0}

/* ── MODAL ── */
.modal-wrap{position:fixed;inset:0;z-index:300;display:flex;align-items:center;justify-content:center;padding:16px;opacity:0;pointer-events:none;transition:opacity .2s}
.modal-wrap.on{opacity:1;pointer-events:auto}
.modal-bg{position:absolute;inset:0;background:rgba(0,0,0,.7);backdrop-filter:blur(4px)}
.modal{position:relative;background:var(--bg2);border:1px solid var(--border);border-radius:14px;width:100%;max-width:500px;max-height:90vh;display:flex;flex-direction:column;box-shadow:0 20px 60px rgba(0,0,0,.5)}
.modal-head{display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid var(--border)}
.modal-head h3{font-size:15px;font-weight:600}
.modal-close{width:30px;height:30px;border-radius:6px;border:none;background:transparent;color:var(--fg2);cursor:pointer;font-size:14px;display:flex;align-items:center;justify-content:center}
.modal-close:hover{background:var(--bg4);color:var(--fg)}
.modal-body{padding:20px;overflow-y:auto;flex:1}
.modal-foot{padding:14px 20px;border-top:1px solid var(--border);display:flex;justify-content:flex-end;gap:8px}
.modal-body label{display:block;font-size:12px;font-weight:500;color:var(--fg3);margin-bottom:6px}
.modal-body input,.modal-body textarea,.modal-body select{width:100%;background:var(--bg4);border:1px solid var(--border);border-radius:8px;padding:9px 12px;color:var(--fg);font-size:13px;outline:none}
.modal-body input:focus,.modal-body textarea:focus{border-color:hsla(211,100%,50%,0.5)}
.modal-body select{cursor:pointer}
.modal-body textarea{font-family:var(--mono);font-size:12px;line-height:1.6;resize:vertical;min-height:100px}
.editor-modal .modal{max-width:900px;height:80vh}
.editor-modal .modal-body{padding:0;display:flex;flex-direction:column}
.editor-modal textarea{flex:1;border:none;border-radius:0;resize:none;padding:16px;background:hsl(0,0%,3%);min-height:200px}

/* ── PLUGIN CARDS ── */
.plugin-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}
.pg-card{display:flex;flex-direction:column;gap:10px}
.pg-top{display:flex;gap:12px}
.pg-icon{width:48px;height:48px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0;background:var(--bg4)}
.pg-icon img{width:100%;height:100%;border-radius:10px;object-fit:cover}
.pg-info{flex:1;min-width:0}
.pg-name{font-size:14px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pg-desc{font-size:12px;color:var(--fg3);line-height:1.4;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;margin-top:2px}
.pg-meta{font-size:11px;color:var(--fg3);display:flex;gap:12px;margin-top:6px}
.pg-actions{display:flex;gap:6px;margin-top:auto}
.sub-tabs{display:flex;background:var(--bg3);border-radius:8px;padding:4px;gap:2px}
.sub-tab{flex:1;text-align:center;padding:8px 16px;border-radius:6px;font-size:13px;font-weight:500;color:var(--fg3);cursor:pointer;transition:all .15s}
.sub-tab.on{background:var(--bg4);color:var(--fg);box-shadow:0 1px 3px rgba(0,0,0,.2)}
.search-box{position:relative}
.search-box i{position:absolute;left:12px;top:50%;transform:translateY(-50%);color:var(--fg3);font-size:14px}
.search-box input{width:100%;padding:10px 14px 10px 36px}

/* ── SETTINGS ── */
.prop-group{margin-bottom:20px}
.prop-group-title{font-size:13px;font-weight:600;color:var(--fg);margin-bottom:10px;display:flex;align-items:center;gap:6px}
.prop-group-title i{color:var(--primary);font-size:13px}
.prop-row{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;background:var(--bg2);border:1px solid var(--border);border-radius:8px;margin-bottom:6px;gap:12px}
.prop-label{font-size:13px;font-weight:500}
.prop-desc{font-size:11px;color:var(--fg3);margin-top:2px}
.prop-input{min-width:140px;max-width:200px}
.prop-input input,.prop-input select{width:100%;padding:7px 10px;font-size:13px}
.toggle{width:44px;height:24px;border-radius:12px;background:var(--bg3);border:1px solid var(--border);position:relative;cursor:pointer;transition:all .2s}
.toggle.on{background:var(--primary);border-color:var(--primary)}
.toggle::after{content:'';position:absolute;top:2px;left:2px;width:18px;height:18px;border-radius:50%;background:#fff;transition:transform .2s;box-shadow:0 1px 3px rgba(0,0,0,.3)}
.toggle.on::after{transform:translateX(20px)}

/* ── BACKUP ── */
.backup-item{display:flex;align-items:center;gap:12px;padding:14px;border-bottom:1px solid hsla(0,0%,15%,0.3)}
.backup-item:last-child{border-bottom:none}
.backup-icon{width:40px;height:40px;border-radius:10px;background:var(--bg4);display:flex;align-items:center;justify-content:center;color:var(--primary);font-size:16px;flex-shrink:0}
.backup-info{flex:1;min-width:0}
.backup-name{font-size:14px;font-weight:500;display:flex;align-items:center;gap:6px}
.backup-meta{font-size:12px;color:var(--fg3);margin-top:2px}
.backup-actions{display:flex;gap:4px}

/* ── SCHEDULE ── */
.sched-item{display:flex;align-items:center;gap:12px;padding:14px}
.sched-icon{width:40px;height:40px;border-radius:10px;background:hsla(211,100%,50%,0.1);display:flex;align-items:center;justify-content:center;color:var(--primary);font-size:16px;flex-shrink:0}
.sched-info{flex:1}
.sched-name{font-size:14px;font-weight:500}
.sched-desc{font-size:12px;color:var(--fg3);margin-top:2px}
.badge{display:inline-flex;align-items:center;gap:4px;padding:3px 8px;border-radius:20px;font-size:11px;font-weight:500}
.badge-green{background:hsla(142,71%,45%,0.15);color:var(--success)}
.badge-red{background:hsla(0,72%,51%,0.15);color:var(--destructive)}
.badge-blue{background:hsla(211,100%,50%,0.15);color:var(--primary)}

/* ── TOAST ── */
.toast-wrap{position:fixed;top:16px;right:16px;z-index:500;display:flex;flex-direction:column;gap:8px;pointer-events:none}
.toast{display:flex;align-items:center;gap:10px;padding:12px 16px;background:var(--bg2);border:1px solid var(--border);border-radius:10px;font-size:13px;pointer-events:auto;box-shadow:0 8px 24px rgba(0,0,0,.4);max-width:340px;animation:fadeUp .2s ease-out}
.toast i{font-size:14px;flex-shrink:0}
.toast.success i{color:var(--success)}.toast.error i{color:var(--destructive)}.toast.warn i{color:var(--warning)}

/* ── UPLOAD ── */
.upload-zone{border:2px dashed var(--border);border-radius:var(--radius);padding:40px;text-align:center;color:var(--fg3);cursor:pointer;transition:all .2s}
.upload-zone:hover,.upload-zone.drag{border-color:var(--primary);background:hsla(211,100%,50%,0.05);color:var(--fg2)}
.upload-zone i{font-size:32px;margin-bottom:10px;display:block}
.warn-icon{width:48px;height:48px;border-radius:50%;background:hsla(0,72%,51%,0.1);display:flex;align-items:center;justify-content:center;margin:0 auto 14px;font-size:20px;color:var(--destructive)}
.warn-text{text-align:center;font-size:14px;margin-bottom:6px}
.warn-sub{text-align:center;font-size:12px;color:var(--fg3)}

/* ── PASTE BTN ── */
.paste-btn{position:fixed;bottom:80px;right:16px;z-index:100;display:flex;align-items:center;gap:8px;padding:12px 20px;background:var(--primary);color:#fff;border:none;border-radius:var(--radius);font-size:14px;font-weight:500;cursor:pointer;box-shadow:0 4px 20px rgba(0,0,0,.4)}
.paste-cancel{margin-left:4px;opacity:.7;cursor:pointer}

/* ── SPINNER ── */
.spin{animation:spin .7s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes fadeUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}

/* ── THEME VARIANTS ── */
.theme-light{--bg:hsl(0,0%,96%);--bg2:hsl(0,0%,100%);--bg3:hsl(0,0%,92%);--bg4:hsl(0,0%,90%);--fg:hsl(0,0%,10%);--fg2:hsl(0,0%,25%);--fg3:hsl(0,0%,40%);--border:hsl(0,0%,85%)}
.theme-light .sidebar{background:hsl(0,0%,98%)}
.theme-amoled{--bg:hsl(0,0%,0%);--bg2:hsl(0,0%,4%);--bg3:hsl(0,0%,8%);--bg4:hsl(0,0%,10%);--border:hsl(0,0%,10%)}
.theme-amoled .sidebar{background:hsl(0,0%,2%)}
.accent-purple{--primary:hsl(270,80%,60%)}
.accent-green{--primary:hsl(142,71%,45%)}
.accent-orange{--primary:hsl(25,95%,53%)}
.accent-red{--primary:hsl(0,72%,51%)}
.accent-teal{--primary:hsl(180,60%,45%)}

/* ── CUSTOM SELECT ── */
.custom-select{position:relative;cursor:pointer}
.cs-display{display:flex;align-items:center;justify-content:space-between;padding:7px 10px;background:var(--bg4);border:1px solid var(--border);border-radius:8px;font-size:13px}
.cs-display i{font-size:10px;color:var(--fg3)}
.cs-options{display:none;position:absolute;top:100%;left:0;right:0;background:var(--bg2);border:1px solid var(--border);border-radius:8px;margin-top:4px;z-index:50;max-height:200px;overflow-y:auto;box-shadow:0 8px 24px rgba(0,0,0,.3)}
.custom-select.open .cs-options{display:block}
.cs-opt{padding:8px 12px;font-size:13px;cursor:pointer;transition:background .1s}
.cs-opt:hover{background:var(--bg4)}
.cs-opt.on{color:var(--primary)}

/* ── MOBILE ── */
@media(max-width:768px){
  .sidebar{position:fixed;left:0;top:0;bottom:0;z-index:100;transform:translateX(-100%);transition:transform .3s ease}
  .sidebar.open{transform:translateX(0)}
  .m-header{display:flex}
  .m-bottom-nav{display:block}
  .page{padding:16px;padding-bottom:80px}
  .fm-header{grid-template-columns:1fr 40px}.fm-header .h-size,.fm-header .h-date{display:none}
  .fm-row{grid-template-columns:1fr 40px}.fm-size,.fm-date{display:none}
  .plugin-grid{grid-template-columns:1fr}
  .prop-row{flex-direction:column;align-items:flex-start;gap:6px}
  .prop-input{width:100%;max-width:100%}
  .toast-wrap{top:auto;bottom:80px;right:8px;left:8px}
  .toast{max-width:100%}
  .console-output{min-height:200px;max-height:50vh}
}
</style>
</head>
<body>

<!-- LOGIN SCREEN -->
<div id="login-screen" class="login-wrap" style="display:none">
<div class="login-box">
  <div class="login-icon"><i class="fa-solid fa-server"></i></div>
  <h1 class="login-title">Welcome back</h1>
  <p class="login-sub">Sign in to your server panel</p>
  <div id="login-error" class="login-error" style="display:none"></div>
  <form id="login-form" onsubmit="doLogin(event)">
    <div class="form-group">
      <label class="form-label">Username</label>
      <input type="text" id="login-user" class="form-input" placeholder="admin" autocomplete="username" required>
    </div>
    <div class="form-group">
      <label class="form-label">Password</label>
      <div class="pass-wrap">
        <input type="password" id="login-pass" class="form-input" placeholder="••••••••" autocomplete="current-password" required>
        <button type="button" class="pass-toggle" onclick="togglePass()"><i class="fa-solid fa-eye"></i></button>
      </div>
    </div>
    <div class="login-check">
      <div class="toggle-sm" id="login-remember" onclick="this.classList.toggle('on')"></div>
      <span style="font-size:12px;color:var(--fg3)">Remember me</span>
    </div>
    <button type="submit" class="btn btn-primary btn-full" id="login-btn">Sign In</button>
  </form>
  <p class="login-footer">OSP Panel v1.0.0</p>
</div>
</div>

<!-- MAIN APP -->
<div id="app-screen" class="app" style="display:none">
  <div class="overlay" id="overlay" onclick="closeSb()"></div>
  <aside class="sidebar" id="sidebar">
    <div class="sb-header"><div class="sb-logo"><i class="fa-solid fa-circle-nodes"></i>OSP Panel</div></div>
    <nav class="sb-nav" id="nav"></nav>
    <div class="sb-footer">
      <button class="btn btn-ghost" onclick="doLogout()" style="color:var(--destructive)"><i class="fa-solid fa-right-from-bracket"></i>Sign Out</button>
    </div>
  </aside>
  <div class="main">
    <div class="m-header">
      <button class="ham" onclick="toggleSb()"><i class="fa-solid fa-bars"></i></button>
      <div class="m-title" id="m-page-title">Dashboard</div>
      <div class="m-dot" id="m-dot"></div>
    </div>
    <div class="content" id="content"></div>
    <div class="m-bottom-nav">
      <div class="m-bottom-nav-inner" id="bottom-nav"></div>
    </div>
  </div>
</div>

<div id="paste-container"></div>
<div class="modal-wrap" id="modal-wrap" onclick="modalBgClick(event)"><div class="modal-bg"></div><div class="modal" id="modal-box"></div></div>
<div class="ctx-menu" id="ctx-menu"></div>
<div class="toast-wrap" id="toast-wrap"></div>

<script>
// ═══════════════════════════════════════════════════════════════════════════
// STATE
// ═══════════════════════════════════════════════════════════════════════════
const TABS=[
  {id:'dashboard',icon:'fa-server',label:'Dashboard',mobile:true},
  {id:'files',icon:'fa-folder',label:'Files',mobile:true},
  {id:'plugins',icon:'fa-puzzle-piece',label:'Plugins',mobile:true},
  {id:'status',icon:'fa-signal',label:'Status',mobile:false},
  {id:'schedules',icon:'fa-clock',label:'Schedules',mobile:false},
  {id:'backups',icon:'fa-box-archive',label:'Backups',mobile:true},
  {id:'settings',icon:'fa-gear',label:'Settings',mobile:true}
];
let currentTab='dashboard',serverRunning=false,currentPath='/',pluginSubTab='browse',settingsSubTab='server';
let clipboardItem=null,clipboardAction=null;
let serverProps={},panelConfig={},currentFiles=[],ws=null;
let pluginSearch='',settingsSearch='';
let backupList=[],scheduleList=[];

// ═══════════════════════════════════════════════════════════════════════════
// AUTH
// ═══════════════════════════════════════════════════════════════════════════
async function checkAuth(){
  try{
    const r=await fetch('/api/auth/check');
    const d=await r.json();
    if(d.authenticated){showApp();return}
  }catch(e){}
  showLogin();
}
function showLogin(){
  document.getElementById('login-screen').style.display='flex';
  document.getElementById('app-screen').style.display='none';
}
function showApp(){
  document.getElementById('login-screen').style.display='none';
  document.getElementById('app-screen').style.display='flex';
  initApp();
}
async function doLogin(e){
  e.preventDefault();
  const user=document.getElementById('login-user').value;
  const pass=document.getElementById('login-pass').value;
  const remember=document.getElementById('login-remember').classList.contains('on')?'1':'0';
  const btn=document.getElementById('login-btn');
  const err=document.getElementById('login-error');
  err.style.display='none';
  btn.innerHTML='<i class="fa-solid fa-spinner spin"></i>';
  btn.disabled=true;
  try{
    const fd=new FormData();fd.append('username',user);fd.append('password',pass);fd.append('remember',remember);
    const r=await fetch('/api/auth/login',{method:'POST',body:fd});
    if(r.ok){showApp();return}
    const d=await r.json().catch(()=>({}));
    err.innerHTML='<i class="fa-solid fa-circle-exclamation"></i>'+(d.detail||'Invalid credentials');
    err.style.display='flex';
  }catch(ex){
    err.innerHTML='<i class="fa-solid fa-circle-exclamation"></i>Connection failed';
    err.style.display='flex';
  }
  btn.innerHTML='Sign In';btn.disabled=false;
}
async function doLogout(){
  await fetch('/api/auth/logout',{method:'POST'}).catch(()=>{});
  if(ws){ws.close();ws=null}
  showLogin();
}
function togglePass(){
  const inp=document.getElementById('login-pass');
  const btn=inp.nextElementSibling.querySelector('i');
  if(inp.type==='password'){inp.type='text';btn.className='fa-solid fa-eye-slash'}
  else{inp.type='password';btn.className='fa-solid fa-eye'}
}

// ═══════════════════════════════════════════════════════════════════════════
// APP INIT
// ═══════════════════════════════════════════════════════════════════════════
function initApp(){
  connectWS();loadPanelConfig();renderNav();renderBottomNav();switchTab('dashboard');
}
function connectWS(){
  if(ws)ws.close();
  ws=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws');
  ws.onopen=()=>updateStatus(true);
  ws.onclose=()=>{updateStatus(false);setTimeout(connectWS,5000)};
  ws.onmessage=e=>{
    if(currentTab==='dashboard'){
      const el=document.getElementById('console-scroll');
      if(el){addLineEl(el,e.data);const out=document.getElementById('console-out');if(out)out.scrollTop=99999}
    }
  };
}
function updateStatus(on){
  serverRunning=on;
  const d=document.getElementById('m-dot');
  if(d){d.style.background=on?'var(--success)':'var(--fg3)';d.style.boxShadow=on?'0 0 8px var(--success)':'none'}
}

// ═══════════════════════════════════════════════════════════════════════════
// NAV
// ═══════════════════════════════════════════════════════════════════════════
function renderNav(){
  document.getElementById('nav').innerHTML=TABS.map(t=>
    `<div class="nav-item${t.id===currentTab?' active':''}" onclick="switchTab('${t.id}')"><i class="fa-solid ${t.icon}"></i>${t.label}</div>`
  ).join('');
}
function renderBottomNav(){
  const mobile=TABS.filter(t=>t.mobile);
  const more=TABS.filter(t=>!t.mobile);
  document.getElementById('bottom-nav').innerHTML=
    mobile.map(t=>`<button class="m-nav-btn${t.id===currentTab?' active':''}" onclick="switchTab('${t.id}')"><i class="fa-solid ${t.icon}"></i>${t.label}</button>`).join('')+
    (more.length?`<button class="m-nav-btn" onclick="showMoreMenu()"><i class="fa-solid fa-ellipsis"></i>More</button>`:'');
}
function showMoreMenu(){
  const extra=TABS.filter(t=>!t.mobile);
  showModal({title:'More',body:extra.map(t=>`<div class="ctx-item" onclick="switchTab('${t.id}');closeModal()"><i class="fa-solid ${t.icon}"></i>${t.label}</div>`).join(''),foot:''});
}
function switchTab(id){
  currentTab=id;renderNav();renderBottomNav();
  const t=TABS.find(x=>x.id===id);
  document.getElementById('m-page-title').textContent=t?t.label:'';
  const c=document.getElementById('content');
  const renders={dashboard:renderDashboard,files:renderFiles,plugins:renderPlugins,status:renderStatus,schedules:renderSchedules,backups:renderBackups,settings:renderSettings};
  c.innerHTML=`<div class="page">${(renders[id]||renderDashboard)()}</div>`;
  c.scrollTop=0;
  if(id==='dashboard'){initConsole();fetchServerStatus()}
  if(id==='files')fetchFiles(currentPath);
  if(id==='plugins'&&pluginSubTab==='installed')loadInstalledPlugins();
  if(id==='status')fetchExternalStatus();
  if(id==='schedules')loadSchedules();
  if(id==='backups')loadBackups();
  if(id==='settings'&&settingsSubTab==='server')fetchServerProps();
  updatePasteBtn();closeSb();hideCtx();
}

// ═══════════════════════════════════════════════════════════════════════════
// UTILS
// ═══════════════════════════════════════════════════════════════════════════
function escHtml(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function fileIcon(name,isDir){
  if(isDir)return'<i class="fa-solid fa-folder" style="color:#ffa502"></i>';
  const ext=name.split('.').pop().toLowerCase();
  const m={jar:'<i class="fa-solid fa-mug-hot" style="color:#e67e22"></i>',yml:'<i class="fa-solid fa-file-code" style="color:#5b9aff"></i>',yaml:'<i class="fa-solid fa-file-code" style="color:#5b9aff"></i>',properties:'<i class="fa-solid fa-file-lines" style="color:#a29bfe"></i>',json:'<i class="fa-solid fa-file-code" style="color:#ffd43b"></i>',txt:'<i class="fa-solid fa-file-lines" style="color:#888"></i>',log:'<i class="fa-solid fa-file-lines" style="color:#888"></i>',gz:'<i class="fa-solid fa-file-zipper" style="color:#e17055"></i>',zip:'<i class="fa-solid fa-file-zipper" style="color:#e17055"></i>',png:'<i class="fa-solid fa-file-image" style="color:#00b894"></i>',jpg:'<i class="fa-solid fa-file-image" style="color:#00b894"></i>'};
  return m[ext]||'<i class="fa-solid fa-file" style="color:#636e72"></i>';
}
function isEditable(n){return/\.(txt|yml|yaml|properties|json|cfg|conf|log|xml|toml|ini|md|sh|csv)$/i.test(n)}
function isImage(n){return/\.(png|jpg|jpeg|gif|bmp|svg|webp)$/i.test(n)}
function fmtSize(b){if(!b||b<0)return'—';if(b<1024)return b+'B';if(b<1048576)return(b/1024).toFixed(1)+' KB';if(b<1073741824)return(b/1048576).toFixed(1)+' MB';return(b/1073741824).toFixed(1)+' GB'}
function fmtDate(ts){if(!ts)return'—';return new Date(ts*1000).toLocaleDateString('en',{month:'short',day:'numeric',year:'numeric'})}
function setEl(id,v){const e=document.getElementById(id);if(e)e.textContent=v}

// ═══════════════════════════════════════════════════════════════════════════
// DASHBOARD
// ═══════════════════════════════════════════════════════════════════════════
function renderDashboard(){
  return`
  <div class="card status-bar" id="status-bar">
    <div class="status-left"><div class="status-dot" id="srv-dot"></div><span class="status-name" id="srv-name">Server</span><span class="status-version" id="srv-version"></span></div>
    <span class="status-uptime" id="srv-uptime">—</span>
  </div>
  <div class="console-wrap">
    <div class="console-output" id="console-out"><div id="console-scroll"></div></div>
    <div class="console-input"><span>&gt;</span><input type="text" id="cmd-input" placeholder="Type a command..." onkeydown="if(event.key==='Enter')sendCmd()"><button class="btn btn-ghost btn-sm" onclick="sendCmd()"><i class="fa-solid fa-paper-plane"></i></button></div>
  </div>
  <div class="card storage-bar" id="storage-card">
    <i class="fa-solid fa-hard-drive"></i>
    <div class="storage-info">
      <div class="storage-labels"><span>Storage</span><span class="val" id="storage-text">— / 20 GB</span></div>
      <div class="progress-track"><div class="progress-fill" id="storage-fill" style="width:0%"></div></div>
    </div>
  </div>
  <div class="power-row">
    <button class="power-btn" id="power-toggle" onclick="togglePower()"><i class="fa-solid fa-play"></i>Start</button>
    <button class="power-btn restart" onclick="controlServer('restart')"><i class="fa-solid fa-rotate-right"></i><span class="hide-mobile">Restart</span></button>
  </div>`;
}

async function fetchServerStatus(){
  try{
    const r=await fetch('/api/server/status');const d=await r.json();
    const dot=document.getElementById('srv-dot');
    if(dot){dot.className='status-dot '+(d.running?'on':'off')}
    setEl('srv-name',d.server_name||'Server');
    setEl('srv-version',d.active_jar||'');
    setEl('srv-uptime',d.running?d.uptime:'Offline');
    updateStatus(d.running);

    const pct=d.storage_pct||0;
    setEl('storage-text',fmtSize(d.storage_used)+' / '+fmtSize(d.storage_total));
    const fill=document.getElementById('storage-fill');
    if(fill){fill.style.width=pct+'%';fill.className='progress-fill'+(pct>80?' danger':'')}

    const btn=document.getElementById('power-toggle');
    if(btn){
      if(d.running){btn.className='power-btn stop';btn.innerHTML='<i class="fa-solid fa-square"></i>Stop'}
      else{btn.className='power-btn start';btn.innerHTML='<i class="fa-solid fa-play"></i>Start'}
    }
  }catch(e){}
}
function togglePower(){
  const btn=document.getElementById('power-toggle');
  if(btn&&btn.classList.contains('stop'))controlServer('stop');
  else controlServer('start');
}
async function controlServer(action){
  try{
    const r=await fetch(`/api/server/${action}`,{method:'POST'});
    if(r.ok)toast(action==='start'?'Starting server...':action==='stop'?'Stopping server...':'Restarting...','success');
    else toast('Action failed','error');
    setTimeout(fetchServerStatus,2000);
  }catch(e){toast('Request failed','error')}
}

// ═══════════════════════════════════════════════════════════════════════════
// CONSOLE
// ═══════════════════════════════════════════════════════════════════════════
function initConsole(){
  const el=document.getElementById('console-scroll');if(!el)return;
  el.innerHTML='';
  fetch('/api/console/history').then(r=>r.json()).then(lines=>{
    lines.forEach(l=>addLineEl(el,l));
    const out=document.getElementById('console-out');if(out)out.scrollTop=99999;
  }).catch(()=>{});
}
function addLineEl(container,text){
  const d=document.createElement('div');d.className='c-line';
  let cls='c-info';
  if(/WARN/i.test(text))cls='c-warn';
  else if(/ERROR|SEVERE/i.test(text))cls='c-error';
  else if(/Done|started/i.test(text))cls='c-green';
  const m=text.match(/^\[[\d:]+/);
  if(m)d.innerHTML=`<span class="c-time">${escHtml(m[0])}</span><span class="${cls}">${escHtml(text.slice(m[0].length))}</span>`;
  else d.innerHTML=`<span class="${cls}">${escHtml(text)}</span>`;
  container.appendChild(d);
  if(container.children.length>500)container.removeChild(container.firstChild);
}
function sendCmd(){
  const inp=document.getElementById('cmd-input');if(!inp||!inp.value.trim())return;
  if(ws&&ws.readyState===1)ws.send(inp.value.trim());
  else toast('Not connected','error');
  inp.value='';
}

// ═══════════════════════════════════════════════════════════════════════════
// FILES
// ═══════════════════════════════════════════════════════════════════════════
function renderFiles(){
  const parts=currentPath.split('/').filter(Boolean);
  let crumbs=`<span class="crumb${currentPath==='/'?' now':''}" onclick="fetchFiles('/')"><i class="fa-solid fa-server" style="font-size:11px"></i></span>`;
  let bp='';parts.forEach((p,i)=>{bp+='/'+p;const last=i===parts.length-1;
    crumbs+=`<span class="sep"><i class="fa-solid fa-chevron-right"></i></span><span class="crumb${last?' now':''}" ${last?'':`onclick="fetchFiles('${bp}')"`}>${escHtml(p)}</span>`});
  return`
  <div class="page-header"><h1 class="page-title">Files</h1></div>
  <div class="fm-toolbar">
    ${currentPath!=='/'?`<button class="btn btn-ghost btn-sm" onclick="fetchFiles('${'/'+parts.slice(0,-1).join('/')}')"><i class="fa-solid fa-arrow-left"></i></button>`:''}
    <div class="breadcrumbs">${crumbs}</div>
    <button class="btn btn-ghost btn-sm" onclick="startUpload()"><i class="fa-solid fa-upload"></i></button>
    <button class="btn btn-primary btn-sm" onclick="startCreate()"><i class="fa-solid fa-plus"></i></button>
  </div>
  <div class="fm-list">
    <div class="fm-header"><span>Name</span><span class="h-size">Size</span><span class="h-date">Modified</span><span></span></div>
    <div id="fm-body"><div style="text-align:center;padding:30px;color:var(--fg3)"><i class="fa-solid fa-spinner spin"></i></div></div>
  </div>`;
}

async function fetchFiles(path){
  currentPath=path||'/';
  if(currentTab!=='files'){switchTab('files');return}
  const body=document.getElementById('fm-body');if(!body)return;
  body.innerHTML='<div style="text-align:center;padding:30px;color:var(--fg3)"><i class="fa-solid fa-spinner spin"></i></div>';
  try{
    const r=await fetch('/api/fs/list?path='+encodeURIComponent(currentPath.replace(/^\//,'')));
    const files=await r.json();currentFiles=files;
    if(!files.length){body.innerHTML='<div style="padding:40px;text-align:center;color:var(--fg3)">Empty directory</div>';return}
    body.innerHTML=files.map((f,i)=>`<div class="fm-row" ondblclick="${f.is_dir?`fetchFiles('${(currentPath==='/'?'':currentPath)}/${f.name}')`:`openFileEditor('${escHtml(f.name)}')`}">
      <div class="fm-name">${fileIcon(f.name,f.is_dir)}<span>${escHtml(f.name)}</span></div>
      <div class="fm-size">${fmtSize(f.size)}</div>
      <div class="fm-date">${fmtDate(f.mtime)}</div>
      <div><button class="fm-dot" onclick="event.stopPropagation();showFileCtx(${i},this)"><i class="fa-solid fa-ellipsis"></i></button></div>
    </div>`).join('');
  }catch(e){body.innerHTML='<div style="padding:40px;text-align:center;color:var(--destructive)">Failed to load</div>'}
  // Update breadcrumbs
  const bc=document.querySelector('.breadcrumbs');
  if(bc){
    const parts=currentPath.split('/').filter(Boolean);
    let crumbs=`<span class="crumb${currentPath==='/'?' now':''}" onclick="fetchFiles('/')"><i class="fa-solid fa-server" style="font-size:11px"></i></span>`;
    let bp='';parts.forEach((p,i)=>{bp+='/'+p;const last=i===parts.length-1;
      crumbs+=`<span class="sep"><i class="fa-solid fa-chevron-right"></i></span><span class="crumb${last?' now':''}" ${last?'':`onclick="fetchFiles('${bp}')"`}>${escHtml(p)}</span>`});
    bc.innerHTML=crumbs;
  }
}
function showFileCtx(idx,btn){
  const f=currentFiles[idx];if(!f)return;
  const fp=(currentPath==='/'?'':currentPath)+'/'+f.name;
  const rect=btn.getBoundingClientRect();const menu=document.getElementById('ctx-menu');
  let h='';
  if(f.is_dir)h+=`<div class="ctx-item" onclick="fetchFiles('${fp}');hideCtx()"><i class="fa-solid fa-folder-open"></i>Open</div>`;
  if(isEditable(f.name))h+=`<div class="ctx-item" onclick="openFileEditor('${escHtml(f.name)}');hideCtx()"><i class="fa-solid fa-pen-to-square"></i>Edit</div>`;
  if(isImage(f.name))h+=`<div class="ctx-item" onclick="previewImage('${escHtml(f.name)}');hideCtx()"><i class="fa-solid fa-eye"></i>Preview</div>`;
  h+=`<div class="ctx-item" onclick="showRename('${escHtml(f.name)}');hideCtx()"><i class="fa-solid fa-i-cursor"></i>Rename</div>`;
  h+=`<div class="ctx-item" onclick="downloadFile('${encodeURIComponent(fp.replace(/^\//,''))}');hideCtx()"><i class="fa-solid fa-download"></i>Download</div>`;
  h+=`<div class="ctx-item" onclick="startMove('${escHtml(f.name)}');hideCtx()"><i class="fa-solid fa-arrow-right-arrow-left"></i>Move</div>`;
  h+=`<div class="ctx-sep"></div>`;
  h+=`<div class="ctx-item danger" onclick="showDeleteFile('${escHtml(f.name)}');hideCtx()"><i class="fa-solid fa-trash"></i>Delete</div>`;
  menu.innerHTML=h;menu.style.display='block';
  let x=rect.right-menu.offsetWidth,y=rect.bottom+4;
  if(x<8)x=8;if(y+menu.offsetHeight>window.innerHeight)y=rect.top-menu.offsetHeight-4;
  menu.style.left=x+'px';menu.style.top=y+'px';
  setTimeout(()=>document.addEventListener('click',hideCtx,{once:true}),10);
}
function hideCtx(){document.getElementById('ctx-menu').style.display='none'}
function downloadFile(p){window.open('/api/fs/download?path='+p,'_blank')}

async function openFileEditor(name){
  if(isImage(name)){previewImage(name);return}
  const path=(currentPath==='/'?'':currentPath)+'/'+name;
  showModal({title:'Editing: '+name,cls:'editor-modal',
    body:`<textarea id="editor-area" spellcheck="false">Loading...</textarea>`,
    foot:`<button class="btn btn-secondary" onclick="closeModal()">Cancel</button><button class="btn btn-primary" onclick="saveFile('${escHtml(path.replace(/^\//,''))}')"><i class="fa-solid fa-floppy-disk"></i>Save</button>`});
  try{
    const r=await fetch('/api/fs/read?path='+encodeURIComponent(path.replace(/^\//,'')));
    const text=await r.text();
    document.getElementById('editor-area').value=text;
  }catch(e){document.getElementById('editor-area').value='// Failed to load'}
}
async function saveFile(path){
  const ta=document.getElementById('editor-area');if(!ta)return;
  const fd=new FormData();fd.append('path',path);fd.append('content',ta.value);
  const r=await fetch('/api/fs/write',{method:'POST',body:fd});
  if(r.ok){toast('Saved','success');closeModal()}else toast('Save failed','error');
}
function previewImage(name){
  const path=(currentPath==='/'?'':currentPath)+'/'+name;
  showModal({title:name,body:`<div style="display:flex;justify-content:center;padding:20px"><img src="/api/fs/download?path=${encodeURIComponent(path.replace(/^\//,''))}" style="max-width:100%;max-height:60vh;border-radius:8px" onerror="this.alt='Preview unavailable'"></div>`,foot:`<button class="btn btn-secondary" onclick="closeModal()">Close</button>`});
}
function showRename(name){
  showModal({title:'Rename',body:`<label>New name</label><input type="text" id="rename-input" value="${escHtml(name)}">`,
    foot:`<button class="btn btn-secondary" onclick="closeModal()">Cancel</button><button class="btn btn-primary" onclick="doRename('${escHtml(name)}')">Rename</button>`});
  setTimeout(()=>{const i=document.getElementById('rename-input');if(i){i.focus();i.select()}},100);
}
async function doRename(old){
  const inp=document.getElementById('rename-input');if(!inp||!inp.value.trim())return;
  const fd=new FormData();
  fd.append('old_path',(currentPath==='/'?'':currentPath)+'/'+old);
  fd.append('new_path',(currentPath==='/'?'':currentPath)+'/'+inp.value.trim());
  const r=await fetch('/api/fs/rename',{method:'POST',body:fd});
  if(r.ok){toast('Renamed','success');closeModal();fetchFiles(currentPath)}else toast('Failed','error');
}
function showDeleteFile(name){
  const path=(currentPath==='/'?'':currentPath)+'/'+name;
  showModal({title:'Delete',body:`<div class="warn-icon"><i class="fa-solid fa-triangle-exclamation"></i></div><div class="warn-text">Delete "${escHtml(name)}"?</div><div class="warn-sub">This cannot be undone.</div>`,
    foot:`<button class="btn btn-secondary" onclick="closeModal()">Cancel</button><button class="btn btn-danger" onclick="doDeleteFile('${escHtml(path.replace(/^\//,''))}')">Delete</button>`});
}
async function doDeleteFile(path){
  const fd=new FormData();fd.append('path',path);
  const r=await fetch('/api/fs/delete',{method:'POST',body:fd});
  if(r.ok){toast('Deleted','success');closeModal();fetchFiles(currentPath)}else toast('Failed','error');
}
function startUpload(){
  showModal({title:'Upload Files',body:`<div class="upload-zone" id="drop-zone" onclick="document.getElementById('file-up').click()" ondragover="event.preventDefault();this.classList.add('drag')" ondragleave="this.classList.remove('drag')" ondrop="handleDrop(event)"><i class="fa-solid fa-cloud-arrow-up"></i><div>Drop files or click to browse</div><div style="font-size:11px;margin-top:6px;color:var(--fg3)">Uploading to: ${escHtml(currentPath)}</div></div><input type="file" id="file-up" style="display:none" onchange="doUpload(this.files)" multiple>`,
    foot:`<button class="btn btn-secondary" onclick="closeModal()">Cancel</button>`});
}
async function handleDrop(e){e.preventDefault();document.getElementById('drop-zone').classList.remove('drag');await doUpload(e.dataTransfer.files)}
async function doUpload(files){
  if(!files||!files.length)return;closeModal();
  for(const file of files){
    toast('Uploading '+file.name+'...','success');
    const fd=new FormData();fd.append('path',currentPath.replace(/^\//,''));fd.append('file',file);
    const r=await fetch('/api/fs/upload',{method:'POST',body:fd});
    if(r.ok)toast('Uploaded '+file.name,'success');else toast('Failed: '+file.name,'error');
  }
  fetchFiles(currentPath);
}
function startCreate(){
  showModal({title:'Create New',body:`<div style="display:flex;gap:8px;margin-bottom:14px">
    <button class="btn btn-secondary" style="flex:1" id="cb-file" onclick="document.getElementById('cb-file').style.borderColor='var(--primary)';document.getElementById('cb-dir').style.borderColor='var(--border)'"><i class="fa-solid fa-file"></i> File</button>
    <button class="btn btn-secondary" style="flex:1" id="cb-dir" onclick="document.getElementById('cb-dir').style.borderColor='var(--primary)';document.getElementById('cb-file').style.borderColor='var(--border)'"><i class="fa-solid fa-folder"></i> Folder</button>
  </div><label>Name</label><input type="text" id="create-name" placeholder="Enter name...">`,
  foot:`<button class="btn btn-secondary" onclick="closeModal()">Cancel</button><button class="btn btn-primary" onclick="doCreate()">Create</button>`});
}
async function doCreate(){
  const name=document.getElementById('create-name')?.value?.trim();if(!name)return;
  const isDir=document.getElementById('cb-dir')?.style.borderColor?.includes('primary')||false;
  const fd=new FormData();
  fd.append('path',(currentPath==='/'?'':currentPath)+'/'+name);
  fd.append('is_dir',isDir?'1':'0');
  const r=await fetch('/api/fs/create',{method:'POST',body:fd});
  if(r.ok){toast('Created','success');closeModal();fetchFiles(currentPath)}else toast('Failed','error');
}
function startMove(name){clipboardItem={name,from:currentPath};clipboardAction='move';updatePasteBtn();toast('Navigate to destination and paste','success')}
async function doPaste(){
  if(clipboardAction==='move'&&clipboardItem){
    const fd=new FormData();
    fd.append('old_path',(clipboardItem.from==='/'?'':clipboardItem.from)+'/'+clipboardItem.name);
    fd.append('new_path',(currentPath==='/'?'':currentPath)+'/'+clipboardItem.name);
    const r=await fetch('/api/fs/rename',{method:'POST',body:fd});
    if(r.ok)toast('Moved','success');else toast('Move failed','error');
  }
  cancelClip();fetchFiles(currentPath);
}
function cancelClip(){clipboardItem=null;clipboardAction=null;updatePasteBtn()}
function updatePasteBtn(){
  const c=document.getElementById('paste-container');
  if(clipboardAction==='move'&&clipboardItem)
    c.innerHTML=`<button class="paste-btn" onclick="doPaste()"><i class="fa-solid fa-paste"></i> Paste "${escHtml(clipboardItem.name)}" here <span class="paste-cancel" onclick="event.stopPropagation();cancelClip()"><i class="fa-solid fa-xmark"></i></span></button>`;
  else c.innerHTML='';
}

// ═══════════════════════════════════════════════════════════════════════════
// PLUGINS
// ═══════════════════════════════════════════════════════════════════════════
function renderPlugins(){
  return`<div class="page-header"><h1 class="page-title">Plugins</h1></div>
  <div class="sub-tabs"><div class="sub-tab${pluginSubTab==='browse'?' on':''}" onclick="pluginSubTab='browse';switchTab('plugins')">Browse</div><div class="sub-tab${pluginSubTab==='installed'?' on':''}" onclick="pluginSubTab='installed';switchTab('plugins')">Installed</div></div>
  ${pluginSubTab==='browse'?renderPluginBrowse():renderPluginInstalled()}`;
}
function renderPluginBrowse(){
  return`<div class="search-box"><i class="fa-solid fa-search"></i><input type="text" class="form-input" style="padding-left:36px" id="plugin-search" placeholder="Search Modrinth..." value="${escHtml(pluginSearch)}" onkeydown="if(event.key==='Enter')searchPlugins()"></div>
  <div id="plugin-results"></div>`;
}
function renderPluginInstalled(){
  return`<div id="installed-list"><div style="text-align:center;padding:30px;color:var(--fg3)"><i class="fa-solid fa-spinner spin"></i></div></div>`;
}
async function searchPlugins(){
  const q=document.getElementById('plugin-search')?.value?.trim();if(!q)return;
  pluginSearch=q;
  const el=document.getElementById('plugin-results');if(!el)return;
  el.innerHTML='<div style="text-align:center;padding:30px;color:var(--fg3)"><i class="fa-solid fa-spinner spin"></i></div>';
  try{
    const r=await fetch(`https://api.modrinth.com/v2/search?query=${encodeURIComponent(q)}&facets=[["project_type:plugin"]]&limit=20`);
    const d=await r.json();
    if(!d.hits||!d.hits.length){el.innerHTML='<div style="text-align:center;padding:30px;color:var(--fg3)">No results</div>';return}
    el.innerHTML='<div class="plugin-grid">'+d.hits.map(p=>`<div class="card pg-card">
      <div class="pg-top">
        <div class="pg-icon">${p.icon_url?`<img src="${p.icon_url}" alt="">`:p.title[0]}</div>
        <div class="pg-info"><div class="pg-name">${escHtml(p.title)}</div><div class="pg-desc">${escHtml(p.description||'')}</div></div>
      </div>
      <div class="pg-meta"><span><i class="fa-solid fa-download"></i> ${formatNum(p.downloads)}</span></div>
      <div class="pg-actions"><button class="btn btn-primary btn-sm" onclick="showPluginVersions('${p.slug}','${escHtml(p.title)}')"><i class="fa-solid fa-download"></i> Install</button></div>
    </div>`).join('')+'</div>';
  }catch(e){el.innerHTML='<div style="color:var(--destructive);text-align:center;padding:20px">Search failed</div>'}
}
function formatNum(n){if(n>=1e6)return(n/1e6).toFixed(1)+'M';if(n>=1e3)return(n/1e3).toFixed(0)+'K';return n}

async function showPluginVersions(slug,name){
  showModal({title:'Install '+name,body:'<div style="text-align:center;padding:20px"><i class="fa-solid fa-spinner spin"></i> Loading versions...</div>',foot:''});
  try{
    const r=await fetch(`https://api.modrinth.com/v2/project/${slug}/version?loaders=["paper","spigot","bukkit","purpur"]&limit=10`);
    const versions=await r.json();
    if(!versions.length){document.querySelector('.modal-body').innerHTML='<div style="text-align:center;padding:20px;color:var(--fg3)">No compatible versions</div>';return}
    document.querySelector('.modal-body').innerHTML=versions.map(v=>{
      const file=v.files.find(f=>f.primary)||v.files[0];
      return`<div style="display:flex;align-items:center;justify-content:space-between;padding:10px;border:1px solid var(--border);border-radius:8px;margin-bottom:6px">
        <div><div style="font-size:13px;font-weight:500">${escHtml(v.version_number)}</div><div style="font-size:11px;color:var(--fg3)">${v.game_versions.slice(0,3).join(', ')}</div></div>
        <button class="btn btn-primary btn-sm" onclick="installPlugin('${file.url}','${escHtml(file.filename)}','${slug}','${v.id}','${escHtml(name)}')">Install</button>
      </div>`}).join('');
  }catch(e){document.querySelector('.modal-body').innerHTML='<div style="color:var(--destructive)">Failed to load versions</div>'}
}
async function installPlugin(url,filename,pid,vid,name){
  closeModal();toast('Installing '+name+'...','success');
  const fd=new FormData();fd.append('url',url);fd.append('filename',filename);fd.append('project_id',pid);fd.append('version_id',vid);fd.append('name',name);
  const r=await fetch('/api/plugins/install',{method:'POST',body:fd});
  if(r.ok)toast(name+' installed!','success');else toast('Install failed','error');
}
async function loadInstalledPlugins(){
  const el=document.getElementById('installed-list');if(!el)return;
  try{
    const r=await fetch('/api/plugins/installed');const data=await r.json();
    const entries=Object.entries(data);
    if(!entries.length){el.innerHTML='<div style="text-align:center;padding:40px;color:var(--fg3)">No plugins installed</div>';return}
    el.innerHTML='<div class="plugin-grid">'+entries.map(([pid,p])=>`<div class="card pg-card">
      <div class="pg-top"><div class="pg-icon">${(p.name||'?')[0]}</div>
        <div class="pg-info"><div class="pg-name">${escHtml(p.name)}</div><div class="pg-desc">${escHtml(p.filename)}</div></div>
      </div>
      <div class="pg-actions"><button class="btn btn-danger btn-sm" onclick="uninstallPlugin('${pid}','${escHtml(p.name)}')"><i class="fa-solid fa-trash"></i> Uninstall</button></div>
    </div>`).join('')+'</div>';
  }catch(e){el.innerHTML='<div style="color:var(--destructive);text-align:center;padding:20px">Failed to load</div>'}
}
async function uninstallPlugin(pid,name){
  if(!confirm('Uninstall '+name+'?'))return;
  const fd=new FormData();fd.append('project_id',pid);
  const r=await fetch('/api/plugins/uninstall',{method:'POST',body:fd});
  if(r.ok){toast('Uninstalled','success');loadInstalledPlugins()}else toast('Failed','error');
}

// ═══════════════════════════════════════════════════════════════════════════
// SERVER STATUS (external API)
// ═══════════════════════════════════════════════════════════════════════════
function renderStatus(){
  return`<div class="page-header"><h1 class="page-title">Server Status</h1><button class="btn btn-ghost btn-sm" onclick="fetchExternalStatus()"><i class="fa-solid fa-rotate-right"></i></button></div>
  <div id="ext-status"><div style="text-align:center;padding:40px;color:var(--fg3)"><i class="fa-solid fa-spinner spin"></i> Checking...</div></div>`;
}
async function fetchExternalStatus(){
  const el=document.getElementById('ext-status');if(!el)return;
  const addr=panelConfig.serverAddress||'';
  if(!addr){el.innerHTML='<div class="card" style="text-align:center;padding:30px;color:var(--fg3)">Set server address in Settings to check external status</div>';return}
  try{
    const host=addr.split(':')[0]||addr;const port=addr.split(':')[1]||'25565';
    const r=await fetch(`https://api.mcsrvstat.us/3/${host}:${port}`);const d=await r.json();
    el.innerHTML=`<div class="card">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px">
        <div class="status-dot ${d.online?'on':'off'}"></div>
        <span style="font-size:16px;font-weight:600">${d.online?'Online':'Offline'}</span>
        ${d.online?`<span class="badge badge-green">${d.players?.online||0}/${d.players?.max||0} players</span>`:''}
      </div>
      ${d.online?`
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
          <div><div style="font-size:11px;color:var(--fg3)">Host</div><div style="font-size:14px;font-weight:500">${host}:${port}</div></div>
          <div><div style="font-size:11px;color:var(--fg3)">Version</div><div style="font-size:14px;font-weight:500">${escHtml(d.version||'—')}</div></div>
          <div><div style="font-size:11px;color:var(--fg3)">MOTD</div><div style="font-size:14px">${d.motd?.clean?escHtml(d.motd.clean.join(' ')):'—'}</div></div>
        </div>`:'<div style="color:var(--fg3);font-size:14px">Server appears to be offline or unreachable.</div>'}
    </div>`;
  }catch(e){el.innerHTML='<div class="card" style="color:var(--destructive)">Failed to check status</div>'}
}

// ═══════════════════════════════════════════════════════════════════════════
// SCHEDULES
// ═══════════════════════════════════════════════════════════════════════════
function renderSchedules(){
  return`<div class="page-header"><h1 class="page-title">Schedules</h1><button class="btn btn-primary btn-sm" onclick="showNewSchedule()"><i class="fa-solid fa-plus"></i> New</button></div>
  <div id="sched-list"><div style="text-align:center;padding:30px;color:var(--fg3)"><i class="fa-solid fa-spinner spin"></i></div></div>`;
}
async function loadSchedules(){
  const el=document.getElementById('sched-list');if(!el)return;
  try{
    const r=await fetch('/api/schedules/list');scheduleList=await r.json();
    if(!scheduleList.length){el.innerHTML='<div style="text-align:center;padding:40px;color:var(--fg3)">No schedules configured</div>';return}
    el.innerHTML=scheduleList.map((s,i)=>`<div class="card sched-item" style="margin-bottom:8px">
      <div class="sched-icon"><i class="fa-solid fa-clock"></i></div>
      <div class="sched-info">
        <div class="sched-name">${escHtml(s.name)} <span class="badge ${s.enabled?'badge-green':'badge-red'}">${s.enabled?'Active':'Paused'}</span></div>
        <div class="sched-desc">${escHtml(s.type)} — ${s.tasks?.length||0} task(s)</div>
      </div>
      <div style="display:flex;gap:4px">
        <div class="toggle${s.enabled?' on':''}" onclick="toggleSchedule(${i})"></div>
        <button class="btn btn-ghost btn-sm" onclick="deleteSchedule(${i})"><i class="fa-solid fa-trash" style="color:var(--destructive)"></i></button>
      </div>
    </div>`).join('');
  }catch(e){el.innerHTML='<div style="color:var(--destructive)">Failed to load</div>'}
}
async function toggleSchedule(idx){
  scheduleList[idx].enabled=!scheduleList[idx].enabled;
  const fd=new FormData();fd.append('data',JSON.stringify(scheduleList));
  await fetch('/api/schedules/save',{method:'POST',body:fd});
  loadSchedules();
}
async function deleteSchedule(idx){
  if(!confirm('Delete schedule "'+scheduleList[idx].name+'"?'))return;
  scheduleList.splice(idx,1);
  const fd=new FormData();fd.append('data',JSON.stringify(scheduleList));
  await fetch('/api/schedules/save',{method:'POST',body:fd});
  toast('Deleted','success');loadSchedules();
}
function showNewSchedule(){
  showModal({title:'New Schedule',body:`
    <div class="form-group"><label>Name</label><input type="text" id="sched-name" class="form-input" placeholder="Auto Restart"></div>
    <div class="form-group"><label>Type</label><select id="sched-type" class="form-input"><option value="interval">Interval</option><option value="daily">Daily</option></select></div>
    <div class="form-group"><label>Interval Hours</label><input type="number" id="sched-hours" class="form-input" value="6" min="0"></div>
    <div class="form-group"><label>Task Action</label><select id="sched-action" class="form-input"><option value="restart">Restart Server</option><option value="backup">Create Backup</option><option value="command">Run Command</option></select></div>
    <div class="form-group"><label>Command (if applicable)</label><input type="text" id="sched-cmd" class="form-input" placeholder="say Server restarting in 5 minutes!"></div>`,
    foot:`<button class="btn btn-secondary" onclick="closeModal()">Cancel</button><button class="btn btn-primary" onclick="createSchedule()">Create</button>`});
}
async function createSchedule(){
  const name=document.getElementById('sched-name')?.value?.trim()||'Schedule';
  const type=document.getElementById('sched-type')?.value||'interval';
  const hours=parseInt(document.getElementById('sched-hours')?.value)||6;
  const action=document.getElementById('sched-action')?.value||'restart';
  const cmd=document.getElementById('sched-cmd')?.value||'';
  const sched={id:Date.now().toString(36),name,type,intervalHours:hours,intervalMinutes:0,enabled:true,tasks:[{action,payload:cmd}]};
  scheduleList.push(sched);
  const fd=new FormData();fd.append('data',JSON.stringify(scheduleList));
  await fetch('/api/schedules/save',{method:'POST',body:fd});
  toast('Created','success');closeModal();loadSchedules();
}

// ═══════════════════════════════════════════════════════════════════════════
// BACKUPS
// ═══════════════════════════════════════════════════════════════════════════
function renderBackups(){
  return`<div class="page-header"><h1 class="page-title">Backups</h1>
    <div style="display:flex;gap:6px">
      <button class="btn btn-ghost btn-sm" onclick="showGDriveSettings()"><i class="fa-brands fa-google-drive"></i></button>
      <button class="btn btn-primary btn-sm" onclick="showCreateBackup()"><i class="fa-solid fa-plus"></i> Backup</button>
    </div>
  </div>
  <div id="backup-list"><div style="text-align:center;padding:30px;color:var(--fg3)"><i class="fa-solid fa-spinner spin"></i></div></div>`;
}
async function loadBackups(){
  const el=document.getElementById('backup-list');if(!el)return;
  try{
    const r=await fetch('/api/backups/list');backupList=await r.json();
    if(!backupList.length){el.innerHTML='<div style="text-align:center;padding:40px;color:var(--fg3)">No backups yet</div>';return}
    el.innerHTML='<div class="card" style="padding:0">'+backupList.map(b=>`<div class="backup-item">
      <div class="backup-icon"><i class="fa-solid fa-box-archive"></i></div>
      <div class="backup-info">
        <div class="backup-name">${escHtml(b.name)} ${b.locked?'<i class="fa-solid fa-lock" style="font-size:11px;color:var(--warning)"></i>':''} ${b.gdrive?'<i class="fa-brands fa-google-drive" style="font-size:11px;color:var(--primary)"></i>':''}</div>
        <div class="backup-meta">${fmtSize(b.size)} • ${b.date?new Date(b.date).toLocaleDateString():'—'}</div>
      </div>
      <div class="backup-actions">
        <button class="btn btn-ghost btn-sm" onclick="restoreBackup('${b.id}','${escHtml(b.name)}')" title="Restore"><i class="fa-solid fa-rotate-left"></i></button>
        <button class="btn btn-ghost btn-sm" onclick="window.open('/api/backups/download?backup_id=${b.id}')" title="Download"><i class="fa-solid fa-download"></i></button>
        <button class="btn btn-ghost btn-sm" onclick="toggleBackupLock('${b.id}')" title="Lock"><i class="fa-solid fa-${b.locked?'unlock':'lock'}"></i></button>
        ${!b.locked?`<button class="btn btn-ghost btn-sm" onclick="deleteBackup('${b.id}','${escHtml(b.name)}')" title="Delete"><i class="fa-solid fa-trash" style="color:var(--destructive)"></i></button>`:''}
      </div>
    </div>`).join('')+'</div>';
  }catch(e){el.innerHTML='<div style="color:var(--destructive)">Failed to load</div>'}
}
function showCreateBackup(){
  showModal({title:'Create Backup',body:`<label>Backup Name</label><input type="text" id="backup-name" class="form-input" placeholder="My Backup">`,
    foot:`<button class="btn btn-secondary" onclick="closeModal()">Cancel</button><button class="btn btn-primary" id="backup-btn" onclick="createBackup()"><i class="fa-solid fa-box-archive"></i> Create</button>`});
}
async function createBackup(){
  const name=document.getElementById('backup-name')?.value?.trim()||'Backup';
  const btn=document.getElementById('backup-btn');if(btn){btn.disabled=true;btn.innerHTML='<i class="fa-solid fa-spinner spin"></i> Creating...'}
  const fd=new FormData();fd.append('name',name);
  const r=await fetch('/api/backups/create',{method:'POST',body:fd});
  if(r.ok){toast('Backup created','success');closeModal();loadBackups()}
  else{toast('Failed','error');if(btn){btn.disabled=false;btn.innerHTML='<i class="fa-solid fa-box-archive"></i> Create'}}
}
function restoreBackup(id,name){
  showModal({title:'Restore Backup',body:`<div class="warn-icon"><i class="fa-solid fa-triangle-exclamation"></i></div><div class="warn-text">Restore "${escHtml(name)}"?</div><div class="warn-sub">This will stop the server and overwrite current files.</div>`,
    foot:`<button class="btn btn-secondary" onclick="closeModal()">Cancel</button><button class="btn btn-danger" onclick="doRestore('${id}')">Restore</button>`});
}
async function doRestore(id){
  closeModal();toast('Restoring...','success');
  const fd=new FormData();fd.append('backup_id',id);
  const r=await fetch('/api/backups/restore',{method:'POST',body:fd});
  if(r.ok)toast('Restored! Server restarting...','success');else toast('Restore failed','error');
}
async function toggleBackupLock(id){
  const fd=new FormData();fd.append('backup_id',id);
  await fetch('/api/backups/lock',{method:'POST',body:fd});loadBackups();
}
async function deleteBackup(id,name){
  if(!confirm('Delete backup "'+name+'"?'))return;
  const fd=new FormData();fd.append('backup_id',id);
  const r=await fetch('/api/backups/delete',{method:'POST',body:fd});
  if(r.ok){toast('Deleted','success');loadBackups()}else toast('Failed','error');
}
function showGDriveSettings(){
  const bc=panelConfig.backups||{};
  showModal({title:'Google Drive Settings',body:`
    <div style="margin-bottom:12px;font-size:12px;color:var(--fg3)">Optional: Connect Google Drive to automatically upload backups.</div>
    <div class="form-group"><label>Enable Google Drive</label><div class="toggle${bc.gdrive_enabled?' on':''}" id="gd-toggle" onclick="this.classList.toggle('on')"></div></div>
    <div class="form-group"><label>Client ID</label><input type="text" id="gd-cid" class="form-input" value="${escHtml(bc.gdrive_client_id||'')}"></div>
    <div class="form-group"><label>Client Secret</label><input type="password" id="gd-cs" class="form-input" value="${escHtml(bc.gdrive_client_secret||'')}"></div>
    <div class="form-group"><label>Refresh Token</label><input type="password" id="gd-rt" class="form-input" value="${escHtml(bc.gdrive_refresh_token||'')}"></div>
    <div class="form-group"><label>Folder ID (optional)</label><input type="text" id="gd-fid" class="form-input" value="${escHtml(bc.gdrive_folder_id||'')}"></div>`,
    foot:`<button class="btn btn-secondary" onclick="closeModal()">Cancel</button><button class="btn btn-primary" onclick="saveGDrive()">Save</button>`});
}
async function saveGDrive(){
  panelConfig.backups={
    gdrive_enabled:document.getElementById('gd-toggle')?.classList.contains('on')||false,
    gdrive_client_id:document.getElementById('gd-cid')?.value||'',
    gdrive_client_secret:document.getElementById('gd-cs')?.value||'',
    gdrive_refresh_token:document.getElementById('gd-rt')?.value||'',
    gdrive_folder_id:document.getElementById('gd-fid')?.value||''
  };
  const fd=new FormData();fd.append('data',JSON.stringify(panelConfig));
  await fetch('/api/settings/panel',{method:'POST',body:fd});
  toast('Saved','success');closeModal();
}

// ═══════════════════════════════════════════════════════════════════════════
// SETTINGS
// ═══════════════════════════════════════════════════════════════════════════
const PROP_GROUPS=[
  {group:'Network',icon:'fa-network-wired',props:[
    {key:'server-port',type:'number',desc:'Server port number'},
    {key:'server-ip',type:'text',desc:'Server IP binding address'},
    {key:'online-mode',type:'bool',desc:'Authenticate with Mojang'},
  ]},
  {group:'Gameplay',icon:'fa-gamepad',props:[
    {key:'gamemode',type:'select',options:['survival','creative','adventure','spectator'],desc:'Default game mode'},
    {key:'difficulty',type:'select',options:['peaceful','easy','normal','hard'],desc:'Difficulty'},
    {key:'pvp',type:'bool',desc:'Enable PvP'},
    {key:'max-players',type:'number',desc:'Max players'},
    {key:'spawn-protection',type:'number',desc:'Spawn protection radius'},
    {key:'allow-flight',type:'bool',desc:'Allow flight'},
    {key:'hardcore',type:'bool',desc:'Hardcore mode'},
  ]},
  {group:'World',icon:'fa-globe',props:[
    {key:'level-name',type:'text',desc:'World folder name'},
    {key:'level-seed',type:'text',desc:'World seed'},
    {key:'generate-structures',type:'bool',desc:'Generate structures'},
    {key:'spawn-animals',type:'bool',desc:'Spawn animals'},
    {key:'spawn-monsters',type:'bool',desc:'Spawn monsters'},
  ]},
  {group:'General',icon:'fa-cog',props:[
    {key:'motd',type:'text',desc:'Server list message'},
    {key:'enable-command-block',type:'bool',desc:'Enable command blocks'},
    {key:'white-list',type:'bool',desc:'Enable whitelist'},
    {key:'view-distance',type:'number',desc:'View distance'},
  ]}
];

function renderSettings(){
  return`<div class="page-header"><h1 class="page-title">Settings</h1><button class="btn btn-primary btn-sm" onclick="saveSettings()"><i class="fa-solid fa-floppy-disk"></i> Save</button></div>
  <div class="sub-tabs" style="max-width:400px">
    <div class="sub-tab${settingsSubTab==='server'?' on':''}" onclick="settingsSubTab='server';switchTab('settings')">Server Properties</div>
    <div class="sub-tab${settingsSubTab==='panel'?' on':''}" onclick="settingsSubTab='panel';switchTab('settings')">Panel</div>
  </div>
  ${settingsSubTab==='server'?renderServerProps():renderPanelSettings()}`;
}
function renderServerProps(){
  return`<div id="props-body">${renderPropsList()}</div>`;
}
function renderPropsList(){
  return PROP_GROUPS.map(g=>`<div class="prop-group"><div class="prop-group-title"><i class="fa-solid ${g.icon}"></i>${g.group}</div>
  ${g.props.map(p=>{const val=serverProps[p.key]??'';return`<div class="prop-row"><div><div class="prop-label">${p.key}</div><div class="prop-desc">${p.desc}</div></div>
  <div class="prop-input">${p.type==='bool'?`<div class="toggle${(val==='true'||val===true)?' on':''}" onclick="this.classList.toggle('on');serverProps['${p.key}']=this.classList.contains('on')?'true':'false'"></div>`:p.type==='select'?`<select class="form-input" onchange="serverProps['${p.key}']=this.value">${p.options.map(o=>`<option${o===val?' selected':''}>${o}</option>`).join('')}</select>`:`<input type="${p.type==='number'?'number':'text'}" class="form-input" value="${escHtml(val)}" onchange="serverProps['${p.key}']=this.value" placeholder="—">`}</div></div>`}).join('')}</div>`).join('');
}
async function fetchServerProps(){
  try{const r=await fetch('/api/settings/properties');if(r.ok)serverProps=await r.json()}catch(e){}
  const body=document.getElementById('props-body');if(body)body.innerHTML=renderPropsList();
}
function renderPanelSettings(){
  const themes=['dark','light','amoled'];const accents=['blue','purple','green','orange','red','teal'];
  return`
  <div class="prop-group"><div class="prop-group-title"><i class="fa-solid fa-palette"></i>Appearance</div>
    <div class="prop-row"><div><div class="prop-label">Theme</div></div>
    <div style="display:flex;gap:6px">${themes.map(t=>`<button class="btn btn-sm ${panelConfig.theme===t?'btn-primary':'btn-secondary'}" onclick="setTheme('${t}')">${t}</button>`).join('')}</div></div>
    <div class="prop-row"><div><div class="prop-label">Accent Color</div></div>
    <div style="display:flex;gap:6px">${accents.map(a=>`<div onclick="setAccent('${a}')" style="width:24px;height:24px;border-radius:50%;cursor:pointer;border:2px solid ${panelConfig.accent===a?'var(--fg)':'transparent'};background:var(--primary);${a!=='blue'?`background:hsl(${a==='purple'?'270,80%,60%':a==='green'?'142,71%,45%':a==='orange'?'25,95%,53%':a==='red'?'0,72%,51%':'180,60%,45%'})`:''}" title="${a}"></div>`).join('')}</div></div>
  </div>
  <div class="prop-group"><div class="prop-group-title"><i class="fa-solid fa-globe"></i>Server Connection</div>
    <div class="prop-row"><div><div class="prop-label">Server Address</div><div class="prop-desc">For external status checks</div></div>
    <div class="prop-input"><input type="text" class="form-input" value="${escHtml(panelConfig.serverAddress||'')}" onchange="panelConfig.serverAddress=this.value" placeholder="play.example.com"></div></div>
  </div>
  <div class="prop-group"><div class="prop-group-title"><i class="fa-solid fa-triangle-exclamation" style="color:var(--destructive)"></i>Danger Zone</div>
    <div class="prop-row"><div><div class="prop-label">Force Kill Server</div><div class="prop-desc">Immediately terminate the process</div></div>
    <button class="btn btn-danger btn-sm" onclick="controlServer('kill')"><i class="fa-solid fa-skull"></i> Kill</button></div>
  </div>`;
}
function setTheme(t){
  panelConfig.theme=t;
  document.body.className='';
  if(t==='light')document.body.classList.add('theme-light');
  else if(t==='amoled')document.body.classList.add('theme-amoled');
  if(panelConfig.accent&&panelConfig.accent!=='blue')document.body.classList.add('accent-'+panelConfig.accent);
  switchTab('settings');
}
function setAccent(a){
  panelConfig.accent=a;
  document.body.classList.remove('accent-purple','accent-green','accent-orange','accent-red','accent-teal');
  if(a!=='blue')document.body.classList.add('accent-'+a);
  switchTab('settings');
}
async function saveSettings(){
  if(settingsSubTab==='server'){
    const fd=new FormData();fd.append('data',JSON.stringify(serverProps));
    const r=await fetch('/api/settings/properties',{method:'POST',body:fd});
    if(r.ok)toast('server.properties saved','success');else toast('Save failed','error');
  }else{
    const fd=new FormData();fd.append('data',JSON.stringify(panelConfig));
    await fetch('/api/settings/panel',{method:'POST',body:fd});
    toast('Panel settings saved','success');
  }
}
async function loadPanelConfig(){
  try{
    const r=await fetch('/api/settings/panel');if(r.ok){const d=await r.json();Object.assign(panelConfig,d);
    if(panelConfig.theme==='light')document.body.classList.add('theme-light');
    else if(panelConfig.theme==='amoled')document.body.classList.add('theme-amoled');
    if(panelConfig.accent&&panelConfig.accent!=='blue')document.body.classList.add('accent-'+panelConfig.accent);
  }}catch(e){}
}

// ═══════════════════════════════════════════════════════════════════════════
// MODAL & TOAST
// ═══════════════════════════════════════════════════════════════════════════
function showModal(cfg){
  const m=document.getElementById('modal-wrap'),box=document.getElementById('modal-box');
  m.classList.remove('editor-modal');
  if(cfg.cls==='editor-modal')m.classList.add('editor-modal');
  box.innerHTML=`<div class="modal-head"><h3>${cfg.title||''}</h3><button class="modal-close" onclick="closeModal()"><i class="fa-solid fa-xmark"></i></button></div><div class="modal-body">${cfg.body||''}</div>${cfg.foot!==undefined&&cfg.foot!==''?`<div class="modal-foot">${cfg.foot}</div>`:(cfg.foot===''?'':`<div class="modal-foot"></div>`)}`;
  m.classList.add('on');
}
function closeModal(){document.getElementById('modal-wrap').classList.remove('on','editor-modal')}
function modalBgClick(e){if(e.target.classList.contains('modal-bg'))closeModal()}
function toast(msg,type='success'){
  const w=document.getElementById('toast-wrap');
  const icons={success:'fa-circle-check',error:'fa-circle-xmark',warn:'fa-triangle-exclamation'};
  const t=document.createElement('div');t.className='toast '+type;
  t.innerHTML=`<i class="fa-solid ${icons[type]||icons.success}"></i><span>${escHtml(msg)}</span>`;
  w.appendChild(t);
  setTimeout(()=>{t.style.opacity='0';t.style.transition='opacity .3s';setTimeout(()=>t.remove(),300)},3500);
}

// ═══════════════════════════════════════════════════════════════════════════
// SIDEBAR
// ═══════════════════════════════════════════════════════════════════════════
function toggleSb(){document.getElementById('sidebar').classList.add('open');document.getElementById('overlay').classList.add('on')}
function closeSb(){document.getElementById('sidebar').classList.remove('open');document.getElementById('overlay').classList.remove('on')}
document.addEventListener('keydown',e=>{if(e.key==='Escape'){closeModal();hideCtx()}});

// ═══════════════════════════════════════════════════════════════════════════
// INIT
// ═══════════════════════════════════════════════════════════════════════════
checkAuth();
</script>
</body>
</html>"""

# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 7860)),
        log_level="info"
    )
