#!/usr/bin/env python3

import os
import shutil
import zipfile
import sys
import gdown

# Get environment variable for Google Drive folder URL
FOLDER_URL = os.getenv("FOLDER_URL")

# Directories for downloading and extracting
DOWNLOAD_DIR = "/tmp/gdrive_download"
EXTRACT_DIR = "/tmp/extracted_world"
APP_DIR = "/app"

def download_and_extract():
    """Download world files from Google Drive and extract them"""
    
    print(">>> Starting world download from Google Drive...")
    
    # Check if FOLDER_URL is set
    if not FOLDER_URL:
        print("⚠️ FOLDER_URL environment variable not set. Skipping download.")
        print(">>> Minecraft will create a default world.")
        return False
    
    try:
        # Clean up and create directories
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        shutil.rmtree(EXTRACT_DIR, ignore_errors=True)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        os.makedirs(EXTRACT_DIR, exist_ok=True)
        
        print(f">>> Downloading from: {FOLDER_URL}")
        
        # Download from Google Drive
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
            print(">>> Make sure the folder is public (Anyone with link)")
            print(">>> Minecraft will create a default world.")
            return False
        
        # Check if any files were downloaded
        if not os.listdir(DOWNLOAD_DIR):
            print("⚠️ No files found in Google Drive folder")
            print(">>> Minecraft will create a default world.")
            return False
        
        # Extract all zip files
        zip_found = False
        for root, _, files in os.walk(DOWNLOAD_DIR):
            for f in files:
                if f.endswith(".zip"):
                    zip_found = True
                    zip_path = os.path.join(root, f)
                    print(f">>> Extracting: {f}")
                    with zipfile.ZipFile(zip_path, 'r') as z:
                        z.extractall(EXTRACT_DIR)
                    print(f"✅ Extracted: {f}")
        
        if not zip_found:
            print("⚠️ No zip files found in download")
            # Try to copy non-zip files directly
            for item in os.listdir(DOWNLOAD_DIR):
                src = os.path.join(DOWNLOAD_DIR, item)
                dst = os.path.join(EXTRACT_DIR, item)
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
        
        # Fix common typo in world_nether folder name
        bad_nether = os.path.join(EXTRACT_DIR, "world_nither")
        good_nether = os.path.join(EXTRACT_DIR, "world_nether")
        if os.path.exists(bad_nether) and not os.path.exists(good_nether):
            os.rename(bad_nether, good_nether)
            print("✅ Fixed world_nether folder name typo")
        
        # Copy world folders to app directory
        world_folders = {
            "world": os.path.join(EXTRACT_DIR, "world"),
            "world_nether": os.path.join(EXTRACT_DIR, "world_nether"),
            "world_the_end": os.path.join(EXTRACT_DIR, "world_the_end"),
            "plugins": os.path.join(EXTRACT_DIR, "plugins")
        }
        
        copied_any = False
        for name, src_path in world_folders.items():
            if os.path.exists(src_path):
                dst_path = os.path.join(APP_DIR, name)
                # Remove existing folder if it exists
                if os.path.exists(dst_path):
                    shutil.rmtree(dst_path)
                shutil.copytree(src_path, dst_path)
                print(f"✅ Copied {name} to /app/")
                copied_any = True
            else:
                print(f"⚠️ {name} not found in extracted files")
        
        # Clean up temporary directories
        shutil.rmtree(DOWNLOAD_DIR, ignore_errors=True)
        shutil.rmtree(EXTRACT_DIR, ignore_errors=True)
        
        if copied_any:
            print("✅ World data setup complete!")
            return True
        else:
            print("⚠️ No world folders found in extracted files")
            print(">>> Minecraft will create a default world.")
            return False
            
    except Exception as e:
        print(f"❌ Error during download/extraction: {e}")
        print(">>> Minecraft will create a default world.")
        return False

if __name__ == "__main__":
    success = download_and_extract()
    sys.exit(0 if success else 1)