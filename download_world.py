#!/usr/bin/env python3

import os
import shutil
import zipfile
import sys
import gdown
import re

# Get environment variable for Google Drive folder URL
FOLDER_URL = os.getenv("FOLDER_URL")

# Directories for downloading and extracting
DOWNLOAD_DIR = "/tmp/gdrive_download"
EXTRACT_DIR = "/tmp/extracted_world"
APP_DIR = "/app"

def parse_backup_date(filename):
    # Safely parses timestamp from "Backup-world-2026-3-17--08-41.zip"
    # Returns a tuple for chronological sorting to always pick the newest backup
    match = re.search(r'-(\d{4})-(\d{1,2})-(\d{1,2})--(\d{1,2})-(\d{1,2})\.zip$', filename)
    if match:
        return tuple(map(int, match.groups()))
    return (0, 0, 0, 0, 0)

def download_and_extract():
    """Download world files from Google Drive and extract the latest backups"""
    
    print(">>> Starting world download from Google Drive...")
    
    if not FOLDER_URL:
        print("⚠️ FOLDER_URL environment variable not set. Skipping download.")
        print(">>> Minecraft will create a default world.")
        return False
    
    try:
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        shutil.rmtree(EXTRACT_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        os.makedirs(EXTRACT_DIR, exist_ok=True)
        
        print(f">>> Downloading from: {FOLDER_URL}")
        
        try:
            gdown.download_folder(
                url=FOLDER_URL,
                output=DOWNLOAD_DIR,
                use_cookies=False,
                quiet=False,
                remaining_ok=True
            )
            print("✅ Downloaded from Google Drive")
        except Exception as e:
            print(f"❌ Failed to download folder: {e}")
            print(">>> Minecraft will create a default world.")
            return False

        # Find all downloaded zip files
        all_zips = []
        for root, _, files in os.walk(DOWNLOAD_DIR):
            for f in files:
                if f.endswith(".zip"):
                    all_zips.append((f, os.path.join(root, f)))

        if not all_zips:
            print("⚠️ No zip files found in download")
            print(">>> Minecraft will create a default world.")
            return False

        categories = ["world", "world_nether", "world_the_end", "plugins"]
        latest_zips = {cat: None for cat in categories}

        # Group and find the latest zip for each specific category
        for cat in categories:
            cat_zips = []
            for f_name, f_path in all_zips:
                parent_dir = os.path.basename(os.path.dirname(f_path))
                # Match by explicit prefix (e.g. Backup-world-), exact name, or parent folder
                if f"Backup-{cat}-" in f_name or f"-{cat}-" in f_name or f_name == f"{cat}.zip" or parent_dir == cat:
                    cat_zips.append((f_name, f_path))
            
            if cat_zips:
                cat_zips.sort(key=lambda x: parse_backup_date(x[0]), reverse=True)
                latest_zips[cat] = cat_zips[0][1]

        copied_any = False

        for cat, zip_path in latest_zips.items():
            if not zip_path:
                print(f"⚠️ No backup found for {cat}")
                continue

            print(f">>> Extracting latest {cat} from {os.path.basename(zip_path)}...")
            cat_extract_dir = os.path.join(EXTRACT_DIR, cat)
            os.makedirs(cat_extract_dir, exist_ok=True)
            
            try:
                with zipfile.ZipFile(zip_path, 'r') as z:
                    z.extractall(cat_extract_dir)

                # Fix common typo for nether
                if cat == "world_nether":
                    bad_nether = os.path.join(cat_extract_dir, "world_nither")
                    good_nether = os.path.join(cat_extract_dir, "world_nether")
                    if os.path.exists(bad_nether) and os.path.isdir(bad_nether):
                        os.rename(bad_nether, good_nether)
                        print("✅ Fixed world_nether folder name typo")

                extracted_items = os.listdir(cat_extract_dir)
                src_path = cat_extract_dir
                
                # Check if the zip contained a single nested directory matching the category name 
                # (e.g. extracts to /plugins/plugins/) to avoid double nesting
                if len(extracted_items) == 1 and extracted_items[0] == cat:
                    potential_src = os.path.join(cat_extract_dir, cat)
                    if os.path.isdir(potential_src):
                        src_path = potential_src
                
                # Copy finalized folder to the app directory
                dst_path = os.path.join(APP_DIR, cat)
                if os.path.exists(dst_path):
                    shutil.rmtree(dst_path)
                
                shutil.copytree(src_path, dst_path)
                print(f"✅ Successfully restored {cat} to {dst_path}")
                copied_any = True

            except Exception as e:
                print(f"❌ Failed to extract or copy {cat}: {e}")

        # Clean up temporary directories
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        shutil.rmtree(EXTRACT_DIR, ignore_errors=True)
        
        if copied_any:
            print("✅ World data setup complete!")
            return True
        else:
            print("⚠️ Failed to restore any world folders")
            print(">>> Minecraft will create a default world.")
            return False

    except Exception as e:
        print(f"❌ Error during download/extraction: {e}")
        print(">>> Minecraft will create a default world.")
        return False

if __name__ == "__main__":
    success = download_and_extract()
    sys.exit(0 if success else 1)