import os,asyncio,collections,shutil,urllib.request,json,logging,re,time
from contextlib import asynccontextmanager
from fastapi import FastAPI,WebSocket,Form,UploadFile,File,HTTPException,Query
from fastapi.responses import HTMLResponse,FileResponse,JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# ── Config ──────────────────────────────────────────────────────────
logging.getLogger("uvicorn.access").setLevel(logging.CRITICAL)
logging.getLogger("uvicorn.error").setLevel(logging.CRITICAL)

BASE_DIR=os.environ.get("SERVER_DIR",os.path.abspath("/app"))
PLUGINS_DIR=os.path.join(BASE_DIR,"plugins")
PASS_SECRET=os.environ.get("PASS","admin")
PANEL_DIR=os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE=os.path.join(PLUGINS_DIR,"panel_config.json")
HISTORY_FILE=os.path.join(PLUGINS_DIR,"panel_history.json")

# ── State ───────────────────────────────────────────────────────────
mc_process=None
output_history=collections.deque(maxlen=2000)
connected_clients:set=set()
player_sessions={}
ip_tracker=collections.defaultdict(list)
server_start_time=None
server_version="1.21.x"
detected_server_ip=""
current_players=set()

# ── Config Management ──────────────────────────────────────────────
def load_config()->dict:
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE,'r')as f:return json.load(f)
    except:pass
    return{"theme":"dark","serverIP":"","autoBackup":True,"backupOnEmpty":True,"notifications":True,"consoleTimestamps":False}

def save_config(cfg:dict):
    with open(CONFIG_FILE,'w')as f:json.dump(cfg,f,indent=2)

def load_history()->dict:
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE,'r')as f:return json.load(f)
    except:pass
    return{"playerLogs":[],"ipLogs":[],"commandLogs":[]}

def save_history(h:dict):
    with open(HISTORY_FILE,'w')as f:json.dump(h,f,indent=2)

def log_player(player:str,action:str,ip:str=""):
    global current_players
    h=load_history()
    ts=time.strftime("%Y-%m-%d %H:%M:%S")
    if player:
        h["playerLogs"].append({"player":player,"action":action,"ip":ip,"time":ts})
        if player not in player_sessions:player_sessions[player]={"join_time":ts,"ips":[],"kills":0,"deaths":0,"play_time":0}
        if ip and ip not in player_sessions[player]["ips"]:player_sessions[player]["ips"].append(ip)
        if ip:ip_tracker[ip].append({"player":player,"action":action,"time":ts})
        if action=="join":current_players.add(player)
        elif action=="leave":current_players.discard(player)
    h["playerLogs"]=h["playerLogs"][-500:]
    save_history(h)

def parse_console_line(line:str):
    global mc_process,server_version,detected_server_ip
    # Extract server version
    ver_match=re.search(r'Starting Minecraft server version ([\d.]+)',line)
    if ver_match:server_version=ver_match.group(1)
    paper_match=re.search(r'Paper ([\d.]+)',line)
    if paper_match:server_version=f"Paper {paper_match.group(1)}"
    # Extract public IP from connect plugin
    ip_match=re.search(r'public address: (.+)',line)
    if ip_match:detected_server_ip=ip_match.group(1).strip()
    # Extract player join with IP
    join_match=re.search(r'(\w+)\[/([\d.]+)',line)
    if join_match and "logged in" in line:
        player=join_match.group(1)
        ip=join_match.group(2)
        log_player(player,"join",ip)
        return
    # Detect player joins
    if" joined the game"in line:
        m=re.search(r'^.*?\]: (.+?) joined',line)
        if m:log_player(m.group(1),"join")
    elif" left the game"in line:
        m=re.search(r'^.*?\]: (.+?) left',line)
        if m:log_player(m.group(1),"leave")
    elif"] Killed "in line or"] was killed"in line.lower():
        m=re.search(r'^\[.*?\]: \[(.+?): Killed (.+?)\]',line)
        if m:log_player(m.group(1),"kill")
    elif" issued server command: /kill"in line:
        m=re.search(r'^\[.*?\]: (.+?) issued server command: /kill',line)
        if m and m.group(1) in current_players:
            if m.group(1) in player_sessions:player_sessions[m.group(1)]["deaths"]+=1
    # Check for empty server to trigger backup
    if mc_process and mc_process.returncode is None:
        cfg=load_config()
        if cfg.get("backupOnEmpty")and" there are 0 players"in line.lower()or"0 players online"in line.lower():
            asyncio.create_task(run_backup())

async def run_backup():
    global mc_process
    if mc_process and mc_process.returncode is None and mc_process.stdin:
        mc_process.stdin.write(b"drivebackup backup\n")
        await mc_process.stdin.drain()
        output_history.append("\U0001f4e6 [Panel] Auto-backup triggered (server empty)")

def log_command(cmd:str):
    h=load_history()
    h["commandLogs"].append({"cmd":cmd,"time":time.strftime("%Y-%m-%d %H:%M:%S")})
    h["commandLogs"]=h["commandLogs"][-200:]
    save_history(h)

# ── Process helpers ─────────────────────────────────────────────────
async def stream_output(pipe):
    try:
        while True:
            line=await pipe.readline()
            if not line:break
            txt=line.decode("utf-8",errors="replace").rstrip()
            output_history.append(txt)
            parse_console_line(txt)
            dead=set()
            for c in connected_clients:
                try:await c.send_text(txt)
                except:dead.add(c)
            connected_clients.difference_update(dead)
    except:pass

async def boot_mc():
    global mc_process,server_start_time,current_players
    if mc_process and mc_process.returncode is None:return"Already running"
    jar=os.path.join(BASE_DIR,"purpur.jar")
    if not os.path.exists(jar):
        output_history.append("\u26a0 [Panel] purpur.jar not found. Upload via Files.")
        return"No jar"
    output_history.append("\U0001f680 [Panel] Starting server...")
    mc_process=await asyncio.create_subprocess_exec("java","-Xmx4G","-Xms1G","-Dfile.encoding=UTF-8","-XX:+UseG1GC","-jar",jar,"--nogui",stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.STDOUT,cwd=BASE_DIR)
    asyncio.create_task(stream_output(mc_process.stdout))
    server_start_time=time.time()
    current_players=set()
    return"Starting"

async def startup_sequence():
    try:
        if os.environ.get("FOLDER_URL"):
            output_history.append("\u23f3 [Panel] Starting Google Drive sync...")
            proc=await asyncio.create_subprocess_exec("python3","download_world.py",stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.STDOUT,cwd=BASE_DIR)
            asyncio.create_task(stream_output(proc.stdout))
            await proc.wait()
            output_history.append("\u2705 [Panel] World sync finished.")
        await boot_mc()
    except Exception as e:output_history.append(f"\u274c [Panel] Startup error: {e}")

@asynccontextmanager
async def lifespan(app:FastAPI):
    os.makedirs(PLUGINS_DIR,exist_ok=True)
    asyncio.create_task(startup_sequence())
    yield

app=FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_credentials=True,allow_methods=["*"],allow_headers=["*"])

# ── Helpers ─────────────────────────────────────────────────────────
def get_path(p:str)->str:
    safe=os.path.abspath(os.path.join(BASE_DIR,(p or"").strip("/")))
    if not safe.startswith(BASE_DIR):raise HTTPException(403,"Path out of bounds")
    return safe

# ── Routes: Auth ────────────────────────────────────────────────────
@app.post("/api/auth")
def auth_check(password:str=Form(alias="pass")):
    if password==PASS_SECRET:return{"status":"ok"}
    raise HTTPException(401,"Invalid password")

@app.get("/")
def index():
    html_path=os.path.join(PANEL_DIR,"panel.html")
    try:
        with open(html_path,"r",encoding="utf-8")as f:return HTMLResponse(f.read())
    except FileNotFoundError:return HTMLResponse("<h1>panel.html not found</h1>",status_code=500)

# ── Routes: WebSocket Console ───────────────────────────────────────
@app.websocket("/ws")
async def ws_endpoint(ws:WebSocket,password:str=Query(alias="pass",default="")):
    if password!=PASS_SECRET:await ws.close(code=1008);return
    await ws.accept()
    connected_clients.add(ws)
    for line in output_history:
        try:await ws.send_text(line)
        except:break
    try:
        while True:
            cmd=await ws.receive_text()
            if mc_process and mc_process.returncode is None and mc_process.stdin:
                mc_process.stdin.write((cmd+"\n").encode())
                await mc_process.stdin.drain()
    except:connected_clients.discard(ws)

# ── Routes: MC Control ─────────────────────────────────────────────
@app.post("/api/mc/control")
async def mc_control(action:str=Form(...)):
    global mc_process
    if action=="start":result=await boot_mc();return JSONResponse({"status":result})
    elif action=="stop":
        if mc_process and mc_process.returncode is None and mc_process.stdin:
            mc_process.stdin.write(b"stop\n");await mc_process.stdin.drain()
            return JSONResponse({"status":"Stop command sent"})
        return JSONResponse({"status":"Not running"})
    elif action=="restart":
        if mc_process and mc_process.returncode is None and mc_process.stdin:
            mc_process.stdin.write(b"stop\n");await mc_process.stdin.drain()
            output_history.append("\u23f3 [Panel] Waiting for server to stop...")
            for _ in range(60):
                await asyncio.sleep(1)
                if mc_process.returncode is not None:break
            await asyncio.sleep(2)
        result=await boot_mc()
        return JSONResponse({"status":f"Restart: {result}"})
    elif action=="kill":
        if mc_process and mc_process.returncode is None:
            mc_process.kill();return JSONResponse({"status":"Killed"})
        return JSONResponse({"status":"Not running"})
    elif action=="status":
        running=mc_process and mc_process.returncode is None
        uptime=int(time.time()-server_start_time)if server_start_time else 0
        cfg=load_config()
        display_ip=cfg.get("serverIP")or detected_server_ip or"---"
        return JSONResponse({
            "running":running,
            "players":len(current_players),
            "playerList":list(current_players),
            "uptime":uptime,
            "version":server_version,
            "serverIP":display_ip
        })
    return JSONResponse({"status":"Unknown action"})

# ── Routes: Config ──────────────────────────────────────────────────
@app.get("/api/config")
def get_config():return JSONResponse(load_config())

@app.post("/api/config")
def update_config(cfg:dict=Form(...)):
    c=load_config()
    c.update(cfg)
    save_config(c)
    return JSONResponse({"status":"ok"})

# ── Routes: History ─────────────────────────────────────────────────
@app.get("/api/history")
def get_history():
    h=load_history()
    cfg=load_config()
    h["serverIP"]=cfg.get("serverIP")or detected_server_ip
    return JSONResponse(h)

@app.get("/api/players/sessions")
def get_player_sessions():
    return JSONResponse(player_sessions)

@app.get("/api/ip/tracker")
def get_ip_tracker():
    return JSONResponse(dict(ip_tracker))

# ── Routes: File System ────────────────────────────────────────────
@app.get("/api/fs/disk")
def fs_disk():
    t,u,f=shutil.disk_usage(BASE_DIR)
    return JSONResponse({"total":t,"used":u,"free":f})

@app.get("/api/fs/list")
def list_fs(path:str=""):
    t=get_path(path)
    if not os.path.isdir(t):return JSONResponse([])
    items=[]
    try:
        for name in os.listdir(t):
            fp=os.path.join(t,name)
            is_dir=os.path.isdir(fp)
            size=0
            if not is_dir:
                try:size=os.path.getsize(fp)
                except OSError:pass
            items.append({"name":name,"is_dir":is_dir,"size":size})
    except PermissionError:pass
    return JSONResponse(sorted(items,key=lambda k:(not k["is_dir"],k["name"].lower())))

@app.post("/api/fs/upload")
async def upload(path:str=Form(""),file:UploadFile=File(...)):
    dest=os.path.join(get_path(path),file.filename)
    with open(dest,"wb")as f:shutil.copyfileobj(file.file,f)
    return JSONResponse({"status":"ok"})

@app.post("/api/fs/delete")
def delete_fs(path:str=Form(...)):
    t=get_path(path)
    if not os.path.exists(t):raise HTTPException(404,"Not found")
    if os.path.isdir(t):shutil.rmtree(t)
    else:os.remove(t)
    return JSONResponse({"status":"ok"})

@app.post("/api/fs/rename")
def rename_fs(path:str=Form(...),new_name:str=Form(...)):
    t=get_path(path)
    if not os.path.exists(t):raise HTTPException(404,"Not found")
    parent=os.path.dirname(t)
    dest=os.path.join(parent,new_name)
    os.rename(t,dest)
    return JSONResponse({"status":"ok"})

@app.post("/api/fs/new-folder")
def new_folder(path:str=Form(...),name:str=Form(...)):
    dest=os.path.join(get_path(path),name)
    os.makedirs(dest,exist_ok=True)
    return JSONResponse({"status":"ok"})

@app.post("/api/fs/new-file")
def new_file(path:str=Form(...),name:str=Form(...)):
    dest=os.path.join(get_path(path),name)
    if os.path.exists(dest):raise HTTPException(409,"File exists")
    with open(dest,"w")as f:f.write("")
    return JSONResponse({"status":"ok"})

@app.get("/api/fs/read")
def read_fs(path:str):
    t=get_path(path)
    if not os.path.isfile(t):raise HTTPException(404,"Not found")
    try:
        with open(t,"r","utf-8",errors="replace")as f:return JSONResponse({"content":f.read()})
    except Exception:raise HTTPException(500,"Cannot read file")

@app.post("/api/fs/write")
def write_fs(path:str=Form(...),content:str=Form(...)):
    with open(get_path(path),"w","utf-8")as f:f.write(content)
    return JSONResponse({"status":"ok"})

@app.get("/api/fs/download")
def download_fs(path:str):
    t=get_path(path)
    if not os.path.isfile(t):raise HTTPException(404,"Not found")
    return FileResponse(t,filename=os.path.basename(t))

# ── Routes: Plugins ────────────────────────────────────────────────
@app.post("/api/plugins/install")
def install_plugin(url:str=Form(...),filename:str=Form(...),project_id:str=Form(""),version_id:str=Form(""),name:str=Form("")):
    dest=os.path.join(PLUGINS_DIR,filename)
    try:
        req=urllib.request.Request(url,headers={"User-Agent":"MCPanel/2.0"})
        with urllib.request.urlopen(req,timeout=60)as r,open(dest,"wb")as f:shutil.copyfileobj(r,f)
    except Exception as e:raise HTTPException(500,f"Download failed: {e}")
    return JSONResponse({"status":"ok"})

@app.get("/api/plugins/list")
def list_plugins():
    plugins=[]
    if os.path.isdir(PLUGINS_DIR):
        for f in os.listdir(PLUGINS_DIR):
            if f.endswith(".jar"):
                fp=os.path.join(PLUGINS_DIR,f)
                plugins.append({"name":f,"size":os.path.getsize(fp),"modified":os.path.getmtime(fp)})
    return JSONResponse(plugins)

@app.post("/api/plugins/delete")
def delete_plugin(filename:str=Form(...)):
    fp=os.path.join(PLUGINS_DIR,filename)
    if os.path.exists(fp):os.remove(fp)
    return JSONResponse({"status":"ok"})

if __name__=="__main__":uvicorn.run(app,host="0.0.0.0",port=int(os.environ.get("PORT",7860)))
