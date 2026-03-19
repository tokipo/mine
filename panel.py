import os, asyncio, collections, shutil, urllib.request, json
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, Form, UploadFile, File, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

BASE_DIR = os.environ.get("SERVER_DIR", os.path.abspath("."))
PLUGINS_DIR = os.path.join(BASE_DIR, "plugins")
CONFIG_PATH = os.path.join(PLUGINS_DIR, "config.json")
PASS_SECRET = os.environ.get("PASS", "admin")
PANEL_DIR = os.path.dirname(os.path.abspath(__file__))

mc_process = None
output_history = collections.deque(maxlen=1000)
connected_clients = set()

async def stream_output(pipe):
    try:
        while True:
            line = await pipe.readline()
            if not line: break
            txt = line.decode("utf-8", errors="replace").rstrip()
            output_history.append(txt)
            dead = set()
            for c in connected_clients:
                try: await c.send_text(txt)
                except: dead.add(c)
            connected_clients.difference_update(dead)
    except Exception: pass

async def boot_mc():
    global mc_process
    if mc_process and mc_process.returncode is None: return "Already running"
    jar = os.path.join(BASE_DIR, "purpur.jar") # Adjust jar name as needed
    if not os.path.exists(jar):
        output_history.append(">> [PANEL] Server JAR not found.")
        return "No jar"
    mc_process = await asyncio.create_subprocess_exec(
        "java", "-Xmx4G", "-Xms1G", "-jar", jar, "--nogui",
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT, cwd=BASE_DIR
    )
    asyncio.create_task(stream_output(mc_process.stdout))
    return "Starting"

@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(PLUGINS_DIR, exist_ok=True)
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w") as f: f.write('{"players":{},"settings":{}}')
    asyncio.create_task(boot_mc())
    yield

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

def get_path(p: str) -> str:
    safe = os.path.abspath(os.path.join(BASE_DIR, (p or "").strip("/")))
    if not safe.startswith(BASE_DIR): raise HTTPException(403, "Out of bounds")
    return safe

@app.post("/api/auth")
def auth_check(password: str = Form(alias="pass")):
    if password == PASS_SECRET: return {"status": "ok"}
    raise HTTPException(401, "Invalid")

@app.get("/")
def index():
    try:
        with open(os.path.join(PANEL_DIR, "panel.html"), "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    except Exception: return HTMLResponse("panel.html missing", 500)

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket, password: str = Query(alias="pass", default="")):
    if password != PASS_SECRET:
        await ws.close(code=1008)
        return
    await ws.accept()
    connected_clients.add(ws)
    for line in output_history:
        try: await ws.send_text(line)
        except: break
    try:
        while True:
            cmd = await ws.receive_text()
            if mc_process and mc_process.returncode is None and mc_process.stdin:
                mc_process.stdin.write((cmd + "\n").encode())
                await mc_process.stdin.drain()
    except Exception:
        connected_clients.discard(ws)

@app.post("/api/mc/control")
async def mc_control(action: str = Form(...)):
    global mc_process
    if action == "start": return PlainTextResponse(await boot_mc())
    elif action == "stop":
        if mc_process and mc_process.returncode is None and mc_process.stdin:
            mc_process.stdin.write(b"stop\n")
            await mc_process.stdin.drain()
            return PlainTextResponse("Stopping")
    elif action == "kill":
        if mc_process and mc_process.returncode is None:
            mc_process.kill()
            return PlainTextResponse("Killed")
    return PlainTextResponse("Unknown")

# --- Fast File CRUD ---
@app.get("/api/fs/list")
def list_fs(path: str = ""):
    t = get_path(path)
    if not os.path.isdir(t): return []
    items =[]
    for name in os.listdir(t):
        fp = os.path.join(t, name)
        is_dir = os.path.isdir(fp)
        items.append({"name": name, "is_dir": is_dir, "size": os.path.getsize(fp) if not is_dir else 0})
    return sorted(items, key=lambda k: (not k["is_dir"], k["name"].lower()))

@app.post("/api/fs/delete")
def delete_fs(path: str = Form(...)):
    t = get_path(path)
    shutil.rmtree(t) if os.path.isdir(t) else os.remove(t)
    return PlainTextResponse("ok")

@app.post("/api/fs/rename")
def rename_fs(path: str = Form(...), new_name: str = Form(...)):
    os.rename(get_path(path), os.path.join(os.path.dirname(get_path(path)), new_name))
    return PlainTextResponse("ok")

@app.post("/api/fs/new")
def new_fs(path: str = Form(...), name: str = Form(...), is_dir: str = Form("false")):
    dest = os.path.join(get_path(path), name)
    if is_dir == "true": os.makedirs(dest, exist_ok=True)
    else: open(dest, "w").close()
    return PlainTextResponse("ok")

@app.get("/api/fs/read")
def read_fs(path: str):
    with open(get_path(path), "r", encoding="utf-8", errors="replace") as f: return PlainTextResponse(f.read())

@app.post("/api/fs/write")
def write_fs(path: str = Form(...), content: str = Form(...)):
    with open(get_path(path), "w", encoding="utf-8") as f: f.write(content)
    return PlainTextResponse("ok")

@app.post("/api/plugins/install")
def install_plugin(url: str = Form(...), filename: str = Form(...)):
    dest = os.path.join(PLUGINS_DIR, filename)
    req = urllib.request.Request(url, headers={"User-Agent": "MCPanel/3.0"})
    with urllib.request.urlopen(req, timeout=30) as r, open(dest, "wb") as f: shutil.copyfileobj(r, f)
    return PlainTextResponse("ok")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 7860)))