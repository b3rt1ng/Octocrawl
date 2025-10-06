import sys
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from urllib.request import urlopen, Request

GITHUB_USER = "b3rt1ng"
GITHUB_REPO = "OctoCrawl"
GITHUB_ARCHIVE_URL = f"https://github.com/{GITHUB_USER}/{GITHUB_REPO}/archive/refs/heads/main.zip"

def get_current_version(project_root):
    version_file = project_root / "version.txt"
    try:
        if version_file.exists():
            return version_file.read_text().strip()
        return "unknown"
    except Exception as e:
        print(f"Error reading version file: {e}")
        return "unknown"

def get_latest_version():
    version_url = f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/main/version.txt"
    try:
        req = Request(version_url)
        req.add_header('User-Agent', 'OctoCrawl-Updater')
        
        with urlopen(req, timeout=10) as response:
            return response.read().decode().strip()
    except Exception as e:
        print(f"Error fetching latest version: {e}")
        return None

def download_latest_version(temp_dir):
    try:
        print("📥 Downloading latest version from GitHub...")
        req = Request(GITHUB_ARCHIVE_URL)
        req.add_header('User-Agent', 'OctoCrawl-Updater')
        
        zip_path = Path(temp_dir) / "octocrawl.zip"
        
        with urlopen(req, timeout=30) as response:
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            chunk_size = 8192
            
            with open(zip_path, 'wb') as f:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        print(f"\r   Progress: {percent:.1f}%", end='', flush=True)
        
        print("\n✅ Download complete!")
        return zip_path
    except Exception as e:
        print(f"\n❌ Error downloading update: {e}")
        return None

def extract_and_update(zip_path, project_root):
    try:
        print("📦 Extracting update...")
        
        backup_dir = project_root.parent / f"{project_root.name}_backup"
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        
        print("💾 Creating backup...")
        shutil.copytree(project_root, backup_dir)
        
        with tempfile.TemporaryDirectory() as extract_dir:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            
            extracted_items = list(Path(extract_dir).iterdir())
            if len(extracted_items) == 1 and extracted_items[0].is_dir():
                source_dir = extracted_items[0]
            else:
                source_dir = Path(extract_dir)
            
            items_to_update = ['src', 'main.py', 'install.py', 'version.txt', 'README.md']
            
            print("🔄 Applying update...")
            for item_name in items_to_update:
                source_item = source_dir / item_name
                target_item = project_root / item_name
                
                if source_item.exists():
                    if target_item.exists():
                        if target_item.is_dir():
                            shutil.rmtree(target_item)
                        else:
                            target_item.unlink()
                    
                    if source_item.is_dir():
                        shutil.copytree(source_item, target_item)
                    else:
                        shutil.copy2(source_item, target_item)
                    print(f"   ✓ Updated: {item_name}")
        
        print("\n✅ Update applied successfully!")
        print(f"💾 Backup saved at: {backup_dir}")
        return True
        
    except Exception as e:
        print(f"\n❌ Error applying update: {e}")
        print("🔙 Attempting to restore from backup...")
        try:
            if backup_dir.exists():
                for item in project_root.iterdir():
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
                
                for item in backup_dir.iterdir():
                    target = project_root / item.name
                    if item.is_dir():
                        shutil.copytree(item, target)
                    else:
                        shutil.copy2(item, target)
                
                print("✅ Backup restored successfully!")
        except Exception as restore_error:
            print(f"❌ Error restoring backup: {restore_error}")
            print(f"⚠️  Please manually restore from: {backup_dir}")
        return False

def check_and_update(project_root):
    print("🔍 Checking for updates...")
    
    current_version = get_current_version(project_root)
    print(f"   Current version: {current_version}")
    
    latest_version = get_latest_version()
    if latest_version is None:
        print("❌ Could not fetch latest version information.")
        return False
    
    print(f"   Latest version:  {latest_version}")
    
    if current_version == latest_version:
        print("✅ You are already using the latest version!")
        return True
    
    print(f"\n🆕 New version available: {current_version} → {latest_version}")
    
    try:
        response = input("\nDo you want to update? [Y/n]: ").strip().lower()
        if response and response not in ['y', 'yes']:
            print("Update cancelled.")
            return False
    except KeyboardInterrupt:
        print("\nUpdate cancelled.")
        return False
    
    with tempfile.TemporaryDirectory() as temp_dir:
        zip_path = download_latest_version(temp_dir)
        if zip_path is None:
            return False
        
        success = extract_and_update(zip_path, project_root)
        
        if success:
            new_version = get_current_version(project_root)
            print(f"\n🎉 Successfully updated to version {new_version}!")
            print("Please launch the install script now.")
        
        return success

def update_command(project_root):
    try:
        return check_and_update(project_root)
    except KeyboardInterrupt:
        print("\n\nUpdate cancelled by user.")
        return False
    except Exception as e:
        print(f"\n❌ Unexpected error during update: {e}")
        return False