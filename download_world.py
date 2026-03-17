#!/usr/bin/env python3
import os, shutil, zipfile, sys, gdown

FOLDER_URL = os.getenv("FOLDER_URL")
DOWNLOAD_DIR = "/tmp/gdrive_download"
EXTRACT_DIR = "/tmp/extracted_world"
APP_DIR = "/app"

def log(msg):
    # flush=True ensures real-time piping to the Panel WebSocket
    print(msg, flush=True)

def download_and_extract():
    log(">>> Starting world download from Google Drive...")
    if not FOLDER_URL:
        log("⚠️ FOLDER_URL environment variable not set. Skipping download.")
        return False
        
    shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
    shutil.rmtree(EXTRACT_DIR, ignore_errors=True)
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    os.makedirs(EXTRACT_DIR, exist_ok=True)
    
    try:
        log(f">>> Connecting to Google Drive...")
        gdown.download_folder(url=FOLDER_URL, output=DOWNLOAD_DIR, use_cookies=False, quiet=True, remaining_ok=True)
        log("✅ Downloaded files successfully.")
    except Exception as e:
        log(f"❌ Failed to download folder: {e}")
        return False
        
    zips = []
    for root, _, files in os.walk(DOWNLOAD_DIR):
        for f in files:
            if f.endswith(".zip"):
                zips.append(os.path.join(root, f))
    
    # Sorting ensures chronological ordering (e.g. 08-41 comes after 03-41)
    zips.sort()
    if not zips:
        log("⚠️ No zip files found. Using default world.")
        return False
        
    targets = ["world", "world_nether", "world_the_end", "plugins"]
    copied = False
    
    for t in targets:
        temp_ext = os.path.join(EXTRACT_DIR, f"temp_{t}")
        os.makedirs(temp_ext, exist_ok=True)
        
        # Filter zips for the specific target
        valid_zips = [z for z in zips if t in os.path.basename(z).lower()]
        if t == "world": # Prevent 'world' from matching 'world_nether'
            valid_zips = [z for z in valid_zips if "nether" not in os.path.basename(z).lower() and "end" not in os.path.basename(z).lower()]
            
        if not valid_zips:
            log(f"⚠️ No backup found for {t}")
            continue
        
        # Grab the newest zip based on our sort
        latest_zip = valid_zips[-1]
        log(f">>> Extracting {t} from {os.path.basename(latest_zip)}...")
        
        try:
            with zipfile.ZipFile(latest_zip, 'r') as z:
                z.extractall(temp_ext)
                
            target_src = None
            # Scan inside the extracted temp folder to find the actual directory
            for root, dirs, _ in os.walk(temp_ext):
                if t in dirs:
                    target_src = os.path.join(root, t)
                    break
                if t == "world_nether" and "world_nither" in dirs:
                    target_src = os.path.join(root, "world_nither")
                    break
                    
            # If no sub-folder was found, assume the files are directly inside the temp root
            if not target_src:
                target_src = temp_ext
                
            dst = os.path.join(APP_DIR, t)
            if os.path.exists(dst): 
                shutil.rmtree(dst)
            shutil.copytree(target_src, dst)
            log(f"✅ Restored {t}")
            copied = True
            
        except Exception as e:
            log(f"❌ Failed to process {t}: {e}")
            
    shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
    shutil.rmtree(EXTRACT_DIR, ignore_errors=True)
    return copied

if __name__ == "__main__":
    download_and_extract()