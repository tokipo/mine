import os, asyncio, collections, shutil, urllib.request, json, logging, re, time, hashlib
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, Form, UploadFile, File, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
import uvicorn
from typing import Optional, Dict, List

# ── Config & Logging ──────────────────────────────────────────────────────────
logging.getLogger("uvicorn.access").setLevel(logging.CRITICAL)
logging.getLogger("uvicorn.error").setLevel(logging.CRITICAL)
BASE_DIR = os.environ.get("SERVER_DIR", os.path.abspath("/app"))
PLUGINS_DIR = os.path.join(BASE_DIR, "plugins")
CONFIG_PATH = os.path.join(PLUGINS_DIR, "panel_config.json")
PASS_SECRET = os.environ.get("PASS", "admin")
PANEL_DIR = os.path.dirname(os.path.abspath(__file__))

# Ensure directories exist
os.makedirs(PLUGINS_DIR, exist_ok=True)

# ── State ───────────────────────────────────────────────────────────
mc_process = None
output_history = collections.deque(maxlen=500)
connected_clients: set = set()
player_analytics = {} # {username: {ips: [], joins: [], leaves: [], deaths: 0}}
server_status = {"players": 0, "version": "Unknown", "ip": "127.0.0.1"}
auto_backup_triggered = False
last_backup_time = 0

# ── Config Helpers ──────────────────────────────────────────────────
def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                return json.load(f)
        except:
            pass
    return {"server_ip": "127.0.0.1", "auto_backup": True, "analytics": {}}

def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        logging.error(f"Failed to save config: {e}")

panel_config = load_config()
if "analytics" not in panel_config:
    panel_config["analytics"] = {}
    save_config(panel_config)

# ── Process helpers ─────────────────────────────────────────────────
async def stream_output(pipe):
    """Read MC stdout line-by-line, parse analytics, broadcast to WS."""
    global mc_process, server_status, auto_backup_triggered, last_backup_time
    try:
        while True:
            line = await pipe.readline()
            if not line:
                break
            txt = line.decode("utf-8", errors="replace").rstrip()
            output_history.append(txt)
            
            # --- Analytics Parsing ---
            # Join: "UUID of player <name> is <uuid>" or "<name> joined the game"
            # Leave: "<name> left the game"
            # Death: "<name> fell off..." or "<name> was slain by..."
            # IP: Usually logged on join in some versions "Connecting to..." or via proxy
            
            join_match = re.search(r"UUID of player (\S+) is", txt)
            if join_match:
                name = join_match.group(1)
                server_status["players"] += 1
                if name not in player_analytics:
                    player_analytics[name] = {"ips": [], "joins": [], "leaves": [], "deaths": 0}
                player_analytics[name]["joins"].append(time.time())
                panel_config["analytics"][name] = player_analytics[name]
                save_config(panel_config)
                # Trigger broadcast for status update
                await broadcast_status()

            leave_match = re.search(r"(\S+) left the game", txt)
            if leave_match:
                name = leave_match.group(1)
                server_status["players"] = max(0, server_status["players"] - 1)
                if name in player_analytics:
                    player_analytics[name]["leaves"].append(time.time())
                    panel_config["analytics"][name] = player_analytics[name]
                    save_config(panel_config)
                await broadcast_status()
                
                # Auto Backup Logic
                if server_status["players"] == 0 and panel_config.get("auto_backup", True):
                    now = time.time()
                    if now - last_backup_time > 60: # 60s cooldown
                        last_backup_time = now
                        output_history.append("\U0001f4be [Panel] Auto-backup triggered (0 players).")
                        if mc_process and mc_process.stdin:
                            mc_process.stdin.write(b"/drivebackup\n")
                            await mc_process.stdin.drain()

            death_match = re.search(r"(\S+) (was slain|fell|died)", txt)
            if death_match:
                name = death_match.group(1)
                if name in player_analytics:
                    player_analytics[name]["deaths"] += 1

            # Broadcast to WS
            dead = set()
            for c in connected_clients:
                try:
                    await c.send_json({"type": "log", "data": txt})
                except Exception:
                    dead.add(c)
            connected_clients.difference_update(dead)
    except Exception:
        pass

async def broadcast_status():
    """Send status update to all clients."""
    msg = {"type": "status", "data": server_status}
    dead = set()
    for c in connected_clients:
        try:
            await c.send_json(msg)
        except:
            dead.add(c)
    connected_clients.difference_update(dead)

async def boot_mc():
    """Start the Minecraft server subprocess."""
    global mc_process
    if mc_process and mc_process.returncode is None:
        return "Already running"
    jar = os.path.join(BASE_DIR, "purpur.jar")
    if not os.path.exists(jar):
        # Try server.jar fallback
        jar = os.path.join(BASE_DIR, "server.jar")
        if not os.path.exists(jar):
            return "No jar found"
    
    output_history.append("\U0001f680 [Panel] Starting Minecraft server...")
    mc_process = await asyncio.create_subprocess_exec(
        "java", "-Xmx4G", "-Xms1G", "-Dfile.encoding=UTF-8",
        "-XX:+UseG1GC", "-jar", jar, "--nogui",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=BASE_DIR,
    )
    asyncio.create_task(stream_output(mc_process.stdout))
    return "Starting"

async def startup_sequence():
    """Run once on panel boot."""
    try:
        if os.environ.get("FOLDER_URL"):
            output_history.append("\u23f3 [Panel] Starting Google Drive sync...")
            proc = await asyncio.create_subprocess_exec(
                "python3", "download_world.py",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=BASE_DIR,
            )
            asyncio.create_task(stream_output(proc.stdout))
            await proc.wait()
            output_history.append("\u2705 [Panel] World sync finished.")
        await boot_mc()
    except Exception as e:
        output_history.append(f"\u274c [Panel] Startup error: {e}")

# ── Lifespan ────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(startup_sequence())
    yield
    if mc_process and mc_process.returncode is None:
        mc_process.terminate()

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# ── Helpers ─────────────────────────────────────────────────────────
def get_path(p: str) -> str:
    safe = os.path.abspath(os.path.join(BASE_DIR, (p or "").strip("/")))
    if not safe.startswith(BASE_DIR):
        raise HTTPException(403, "Path out of bounds")
    return safe

# ── Routes: Auth ────────────────────────────────────────────────────
@app.post("/api/auth")
def auth_check(password: str = Form(alias="pass")):
    # In production, use hashlib.compare_digest for timing safety
    if password == PASS_SECRET:
        return {"status": "ok"}
    raise HTTPException(401, "Invalid password")

@app.post("/api/settings")
def update_settings(password: str = Form(...), new_pass: str = Form(...), server_ip: str = Form(...), auto_backup: bool = Form(...)):
    global PASS_SECRET, panel_config
    if password != PASS_SECRET:
        raise HTTPException(401, "Invalid current password")
    
    if new_pass:
        PASS_SECRET = new_pass
        os.environ["PASS"] = new_pass # Update env for session
    
    panel_config["server_ip"] = server_ip
    panel_config["auto_backup"] = auto_backup
    save_config(panel_config)
    server_status["ip"] = server_ip
    return {"status": "ok"}

@app.get("/api/settings")
def get_settings():
    return {
        "server_ip": panel_config.get("server_ip", "127.0.0.1"),
        "auto_backup": panel_config.get("auto_backup", True),
        "analytics": panel_config.get("analytics", {})
    }

# ── Routes: HTML ────────────────────────────────────────────────────
@app.get("/")
def index():
    html_path = os.path.join(PANEL_DIR, "index.html")
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except FileNotFoundError:
        return HTMLResponse("<h1>index.html not found</h1>", status_code=500)

# ── Routes: WebSocket Console ───────────────────────────────────────
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket, password: str = Query(alias="pass", default="")):
    if password != PASS_SECRET:
        await ws.close(code=1008)
        return
    await ws.accept()
    connected_clients.add(ws)
    # Send history
    for line in output_history:
        try:
            await ws.send_json({"type": "log", "data": line})
        except:
            break
    # Send initial status
    await ws.send_json({"type": "status", "data": server_status})
    
    try:
        while True:
            data = await ws.receive_json()
            if data.get("type") == "command":
                cmd = data.get("data")
                if mc_process and mc_process.returncode is None and mc_process.stdin:
                    mc_process.stdin.write((cmd + "\n").encode())
                    await mc_process.stdin.drain()
    except Exception:
        connected_clients.discard(ws)

# ── Routes: MC Control ─────────────────────────────────────────────
@app.post("/api/mc/control")
async def mc_control(action: str = Form(...)):
    global mc_process
    if action == "start":
        result = await boot_mc()
        return PlainTextResponse(result)
    elif action == "stop":
        if mc_process and mc_process.returncode is None and mc_process.stdin:
            mc_process.stdin.write(b"stop\n")
            await mc_process.stdin.drain()
            return PlainTextResponse("Stop command sent")
        return PlainTextResponse("Not running")
    elif action == "restart":
        if mc_process and mc_process.returncode is None and mc_process.stdin:
            mc_process.stdin.write(b"stop\n")
            await mc_process.stdin.drain()
            output_history.append("\u23f3 [Panel] Waiting for server to stop...")
            for _ in range(60):
                await asyncio.sleep(1)
                if mc_process.returncode is not None:
                    break
            await asyncio.sleep(2)
            result = await boot_mc()
            return PlainTextResponse(f"Restart: {result}")
        return PlainTextResponse("Not running")
    elif action == "kill":
        if mc_process and mc_process.returncode is None:
            mc_process.kill()
            return PlainTextResponse("Killed")
        return PlainTextResponse("Not running")
    return PlainTextResponse("Unknown action")

# ── Routes: File System ────────────────────────────────────────────
@app.get("/api/fs/disk")
def fs_disk():
    t, u, f = shutil.disk_usage(BASE_DIR)
    return {"total": t, "used": u, "free": f}

@app.get("/api/fs/list")
def list_fs(path: str = ""):
    t = get_path(path)
    if not os.path.isdir(t):
        return []
    items = []
    try:
        for name in os.listdir(t):
            fp = os.path.join(t, name)
            is_dir = os.path.isdir(fp)
            size = 0
            mtime = 0
            if not is_dir:
                try:
                    size = os.path.getsize(fp)
                    mtime = os.path.getmtime(fp)
                except OSError:
                    pass
            items.append({"name": name, "is_dir": is_dir, "size": size, "mtime": mtime})
    except PermissionError:
        pass
    return sorted(items, key=lambda k: (not k["is_dir"], k["name"].lower()))

@app.post("/api/fs/upload")
async def upload(path: str = Form(""), file: UploadFile = File(...)):
    dest = os.path.join(get_path(path), file.filename)
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return PlainTextResponse("ok")

@app.post("/api/fs/delete")
def delete_fs(path: str = Form(...)):
    t = get_path(path)
    if not os.path.exists(t):
        raise HTTPException(404, "Not found")
    if os.path.isdir(t):
        shutil.rmtree(t)
    else:
        os.remove(t)
    return PlainTextResponse("ok")

@app.post("/api/fs/rename")
def rename_fs(path: str = Form(...), new_name: str = Form(...)):
    t = get_path(path)
    if not os.path.exists(t):
        raise HTTPException(404, "Not found")
    parent = os.path.dirname(t)
    dest = os.path.join(parent, new_name)
    os.rename(t, dest)
    return PlainTextResponse("ok")

@app.post("/api/fs/new-folder")
def new_folder(path: str = Form(...), name: str = Form(...)):
    dest = os.path.join(get_path(path), name)
    os.makedirs(dest, exist_ok=True)
    return PlainTextResponse("ok")

@app.post("/api/fs/new-file")
def new_file(path: str = Form(...), name: str = Form(...)):
    dest = os.path.join(get_path(path), name)
    if os.path.exists(dest):
        raise HTTPException(409, "File already exists")
    with open(dest, "w") as f:
        f.write("")
    return PlainTextResponse("ok")

@app.get("/api/fs/read")
def read_fs(path: str):
    t = get_path(path)
    if not os.path.isfile(t):
        raise HTTPException(404, "Not found")
    try:
        with open(t, "r", encoding="utf-8", errors="replace") as f:
            return PlainTextResponse(f.read())
    except Exception:
        raise HTTPException(500, "Cannot read file")

@app.post("/api/fs/write")
def write_fs(path: str = Form(...), content: str = Form(...)):
    with open(get_path(path), "w", encoding="utf-8") as f:
        f.write(content)
    return PlainTextResponse("ok")

@app.get("/api/fs/download")
def download_fs(path: str):
    t = get_path(path)
    if not os.path.isfile(t):
        raise HTTPException(404, "Not found")
    return FileResponse(t, filename=os.path.basename(t))

# ── Routes: Plugins ────────────────────────────────────────────────
@app.post("/api/plugins/install")
def install_plugin(
    url: str = Form(...),
    filename: str = Form(...),
):
    dest = os.path.join(PLUGINS_DIR, filename)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MCPanel/Pro"})
        with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
    except Exception as e:
        raise HTTPException(500, f"Download failed: {e}")
    return PlainTextResponse("ok")

@app.get("/api/plugins/installed")
def get_installed_plugins():
    plugins = []
    if os.path.exists(PLUGINS_DIR):
        for f in os.listdir(PLUGINS_DIR):
            if f.endswith(".jar"):
                plugins.append({"name": f, "size": os.path.getsize(os.path.join(PLUGINS_DIR, f))})
    return plugins

# ── Main ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 7860)))