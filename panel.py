import os, asyncio, collections, shutil, urllib.request, json, logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, Form, UploadFile, File, HTTPException, Query, Body
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ── Config ─────────────────────────────────────────────────────────────────
logging.getLogger("uvicorn.access").setLevel(logging.CRITICAL)
logging.getLogger("uvicorn.error").setLevel(logging.CRITICAL)

BASE_DIR     = os.environ.get("SERVER_DIR", os.path.abspath("/app"))
PLUGINS_DIR  = os.path.join(BASE_DIR, "plugins")
CONFIG_FILE  = os.path.join(PLUGINS_DIR, "config.json")
PASS_SECRET  = os.environ.get("PASS", "admin")
PANEL_DIR    = os.path.dirname(os.path.abspath(__file__))

# ── Runtime state ──────────────────────────────────────────────────────────
mc_process = None
output_history: collections.deque = collections.deque(maxlen=1000)
connected_clients: set = set()

# ── Config I/O (source of truth: /plugins/config.json) ────────────────────
def cfg_read() -> dict:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"settings": {}, "players": {}}

def cfg_write(data: dict) -> None:
    os.makedirs(PLUGINS_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ── Process helpers ────────────────────────────────────────────────────────
async def stream_output(pipe):
    """Read server stdout and fan-out to all connected WebSocket clients."""
    try:
        while True:
            line = await pipe.readline()
            if not line:
                break
            txt = line.decode("utf-8", errors="replace").rstrip()
            output_history.append(txt)
            dead: set = set()
            for client in connected_clients:
                try:
                    await client.send_text(txt)
                except Exception:
                    dead.add(client)
            connected_clients.difference_update(dead)
    except Exception:
        pass

async def boot_mc() -> str:
    """Start Minecraft server. Scans for any valid jar if purpur.jar absent."""
    global mc_process
    if mc_process and mc_process.returncode is None:
        return "Already running"

    jar = os.path.join(BASE_DIR, "purpur.jar")
    if not os.path.exists(jar):
        for candidate in ["paper.jar", "server.jar", "spigot.jar", "minecraft_server.jar"]:
            alt = os.path.join(BASE_DIR, candidate)
            if os.path.exists(alt):
                jar = alt
                break
        else:
            output_history.append("⚠ [Panel] No server jar found — upload one via the Files tab.")
            return "No jar"

    output_history.append("🚀 [Panel] Starting Minecraft server...")
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

async def startup_sequence() -> None:
    """Optional world sync from Google Drive then start MC."""
    try:
        if os.environ.get("FOLDER_URL"):
            output_history.append("⏳ [Panel] Starting Google Drive sync...")
            proc = await asyncio.create_subprocess_exec(
                "python3", "download_world.py",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=BASE_DIR,
            )
            asyncio.create_task(stream_output(proc.stdout))
            await proc.wait()
            output_history.append("✅ [Panel] World sync finished.")
        await boot_mc()
    except Exception as exc:
        output_history.append(f"❌ [Panel] Startup error: {exc}")

# ── Lifespan ───────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(PLUGINS_DIR, exist_ok=True)
    asyncio.create_task(startup_sequence())
    yield

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# ── Path helper ────────────────────────────────────────────────────────────
def safe_path(p: str) -> str:
    resolved = os.path.abspath(os.path.join(BASE_DIR, (p or "").lstrip("/")))
    if not resolved.startswith(BASE_DIR):
        raise HTTPException(403, "Path out of bounds")
    return resolved

# ── Auth ───────────────────────────────────────────────────────────────────
@app.post("/api/auth")
def auth_check(password: str = Form(alias="pass")):
    if password != PASS_SECRET:
        raise HTTPException(401, "Invalid password")
    return {"status": "ok"}

# ── Serve panel UI ─────────────────────────────────────────────────────────
@app.get("/")
def index():
    html_path = os.path.join(PANEL_DIR, "panel.html")
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except FileNotFoundError:
        return HTMLResponse("<h1>panel.html not found</h1>", status_code=500)

# ── WebSocket console ──────────────────────────────────────────────────────
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket, password: str = Query(alias="pass", default="")):
    if password != PASS_SECRET:
        await ws.close(code=1008)
        return
    await ws.accept()
    connected_clients.add(ws)
    for line in output_history:
        try:
            await ws.send_text(line)
        except Exception:
            break
    try:
        while True:
            cmd = await ws.receive_text()
            if mc_process and mc_process.returncode is None and mc_process.stdin:
                mc_process.stdin.write((cmd + "\n").encode())
                await mc_process.stdin.drain()
    except Exception:
        connected_clients.discard(ws)

# ── MC process control ─────────────────────────────────────────────────────
@app.post("/api/mc/control")
async def mc_control(action: str = Form(...)):
    global mc_process
    if action == "start":
        return PlainTextResponse(await boot_mc())
    if action == "stop":
        if mc_process and mc_process.returncode is None and mc_process.stdin:
            mc_process.stdin.write(b"stop\n")
            await mc_process.stdin.drain()
            return PlainTextResponse("Stop sent")
        return PlainTextResponse("Not running")
    if action == "restart":
        if mc_process and mc_process.returncode is None and mc_process.stdin:
            mc_process.stdin.write(b"stop\n")
            await mc_process.stdin.drain()
            output_history.append("⏳ [Panel] Waiting for server to stop...")
            for _ in range(60):
                await asyncio.sleep(1)
                if mc_process.returncode is not None:
                    break
            await asyncio.sleep(2)
        return PlainTextResponse(f"Restart: {await boot_mc()}")
    if action == "kill":
        if mc_process and mc_process.returncode is None:
            mc_process.kill()
            return PlainTextResponse("Killed")
        return PlainTextResponse("Not running")
    return PlainTextResponse("Unknown action")

@app.get("/api/mc/status")
def mc_status():
    running = mc_process is not None and mc_process.returncode is None
    return JSONResponse({"running": running, "pid": mc_process.pid if running else None})

# ── Config persistence ─────────────────────────────────────────────────────
@app.get("/api/config")
def get_config():
    return JSONResponse(cfg_read())

@app.post("/api/config")
async def post_config(body: dict = Body(...)):
    cfg_write(body)
    return {"status": "ok"}

# ── File system ────────────────────────────────────────────────────────────
@app.get("/api/fs/disk")
def fs_disk():
    total, used, free = shutil.disk_usage(BASE_DIR)
    return {"total": total, "used": used, "free": free}

@app.get("/api/fs/list")
def list_fs(path: str = ""):
    target = safe_path(path)
    if not os.path.isdir(target):
        return []
    items = []
    try:
        for name in os.listdir(target):
            fp = os.path.join(target, name)
            is_dir = os.path.isdir(fp)
            size = 0 if is_dir else (os.path.getsize(fp) if os.path.isfile(fp) else 0)
            items.append({"name": name, "is_dir": is_dir, "size": size})
    except PermissionError:
        pass
    return sorted(items, key=lambda x: (not x["is_dir"], x["name"].lower()))

@app.post("/api/fs/upload")
async def upload(path: str = Form(""), file: UploadFile = File(...)):
    dest = os.path.join(safe_path(path), file.filename)
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return PlainTextResponse("ok")

@app.post("/api/fs/delete")
def delete_fs(path: str = Form(...)):
    target = safe_path(path)
    if not os.path.exists(target):
        raise HTTPException(404, "Not found")
    shutil.rmtree(target) if os.path.isdir(target) else os.remove(target)
    return PlainTextResponse("ok")

@app.post("/api/fs/rename")
def rename_fs(path: str = Form(...), new_name: str = Form(...)):
    target = safe_path(path)
    if not os.path.exists(target):
        raise HTTPException(404, "Not found")
    os.rename(target, os.path.join(os.path.dirname(target), new_name))
    return PlainTextResponse("ok")

@app.post("/api/fs/new-folder")
def new_folder(path: str = Form(...), name: str = Form(...)):
    os.makedirs(os.path.join(safe_path(path), name), exist_ok=True)
    return PlainTextResponse("ok")

@app.post("/api/fs/new-file")
def new_file(path: str = Form(...), name: str = Form(...)):
    dest = os.path.join(safe_path(path), name)
    if os.path.exists(dest):
        raise HTTPException(409, "File already exists")
    open(dest, "w").close()
    return PlainTextResponse("ok")

@app.get("/api/fs/read")
def read_fs(path: str):
    target = safe_path(path)
    if not os.path.isfile(target):
        raise HTTPException(404, "Not found")
    try:
        with open(target, "r", encoding="utf-8", errors="replace") as f:
            return PlainTextResponse(f.read())
    except Exception:
        raise HTTPException(500, "Cannot read file")

@app.post("/api/fs/write")
def write_fs(path: str = Form(...), content: str = Form(...)):
    with open(safe_path(path), "w", encoding="utf-8") as f:
        f.write(content)
    return PlainTextResponse("ok")

@app.get("/api/fs/download")
def download_fs(path: str):
    target = safe_path(path)
    if not os.path.isfile(target):
        raise HTTPException(404, "Not found")
    return FileResponse(target, filename=os.path.basename(target))

# ── Plugin installer ───────────────────────────────────────────────────────
@app.post("/api/plugins/install")
def install_plugin(
    url: str = Form(...),
    filename: str = Form(...),
    project_id: str = Form(""),
    version_id: str = Form(""),
    name: str = Form(""),
):
    dest = os.path.join(PLUGINS_DIR, filename)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MCPanel/2.0"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
            shutil.copyfileobj(resp, f)
    except Exception as exc:
        raise HTTPException(500, f"Download failed: {exc}")
    return PlainTextResponse("ok")

# ── Entry point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 7860)))