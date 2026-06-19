import os
import re
import sys
import json
import base64
import time
import threading
import concurrent.futures
import argparse
import importlib.metadata
from pathlib import Path

# ==============================================================================
# ⚙️ DEPENDENCY CHECK & CONFIGURATION
# ==============================================================================

REQUIRED_PACKAGES = {
    "requests": "2.34.2",
    "urllib3": "2.7.0",
    "rookiepy": "0.5.6",
    "colorama": "0.4.6"
}

def check_dependencies():
    missing_or_outdated = []
    
    for pkg, min_version in REQUIRED_PACKAGES.items():
        try:
            installed_version = importlib.metadata.version(pkg)
            # Convert versions to tuples of integers for comparison (e.g., "2.7.0" -> (2, 7, 0))
            installed_tuple = tuple(map(int, installed_version.split('.')))
            min_tuple = tuple(map(int, min_version.split('.')))
            
            if installed_tuple < min_tuple:
                missing_or_outdated.append((pkg, min_version, installed_version))
        except importlib.metadata.PackageNotFoundError:
            missing_or_outdated.append((pkg, min_version, None))
        except Exception:
            # Fallback if version parsing fails for any reason
            missing_or_outdated.append((pkg, min_version, None))

    if missing_or_outdated:
        print("=" * 60)
        print(" ⚠️  DEPENDENCY CHECK FAILED")
        print("=" * 60)
        print("\nThe following required packages are missing or outdated:\n")
        
        for pkg, req_ver, inst_ver in missing_or_outdated:
            if inst_ver is None:
                print(f"  - {pkg}: (Not installed, requires >= {req_ver})")
            else:
                print(f"  - {pkg}: (Installed {inst_ver}, requires >= {req_ver})")
        
        print("\n" + "=" * 60)
        print(" HOW TO FIX THIS (Choose one method below):")
        print("=" * 60)
        print("\nMethod 1: Upgrade everything automatically (Recommended)")
        print("  Open your Command Prompt (Windows) or Terminal (Mac/Linux) and run:")
        print('  pip install --upgrade requests urllib3 rookiepy colorama')
        
        print("\nMethod 2: If 'pip' doesn't work, try:")
        print("  python -m pip install --upgrade requests urllib3 rookiepy colorama")
        
        print("\nMethod 3: If you have multiple Python versions, try:")
        print("  py -m pip install --upgrade requests urllib3 rookiepy colorama")
        print("\n" + "=" * 60 + "\n")
        sys.exit(1)

# Run the check before importing the external libraries
check_dependencies()

try:
    import requests
    from requests.adapters import HTTPAdapter
    import rookiepy
    from colorama import init, Fore, Style
    init(autoreset=True)  # Enable ANSI colors for Windows
except Exception as e:
    print(f"An unexpected error occurred during import: {e}")
    sys.exit(1)

# ==============================================================================
# ⚙️ CONFIGURATION - CODE BEGINS BELOW
# ==============================================================================

BASE_URL = "https://mangadot.net"
TUS_ENDPOINT = f"{BASE_URL}/api/tus/"
BATCH_INIT_ENDPOINT = f"{BASE_URL}/api/uploads/batch/init"

MAX_BATCH_SIZE = 100
MAX_RETRIES = 3
RETRY_DELAY = 5
RETRYABLE_STATUSES = [500, 502, 503, 504, 524]
DEFAULT_CHAPTERS_DIR = "chapters"

# Fallback User-Agents if dynamic detection fails (e.g., on Linux or if registry is locked)
DEFAULT_USER_AGENTS = {
    "chrome": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    "firefox": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0",
    "brave": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    "edge": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36 Edg/137.0.0.0",
    "opera": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36 OPR/122.0.0.0",
    "vivaldi": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36 Vivaldi/7.4.3684.38"
}

def get_dynamic_user_agent(browser):
    """
    Reads the exact installed version of the browser from the OS registry (Windows) 
    or plist (Mac) to perfectly match the User-Agent with the extracted cookies.
    No internet connection is used. Fallbacks to hardcoded defaults if missing.
    """
    import sys
    import re
    
    # Helper to strip out any garbage (like "(x64 en-US)") and keep ONLY the version numbers
    def clean_version(raw):
        if not raw: return None
        match = re.search(r'(\d+(?:\.\d+)*)', str(raw))
        return match.group(1) if match else None

    if sys.platform == 'win32':
        try:
            import winreg
            def get_reg_val(hive, path, key):
                try:
                    reg_key = winreg.OpenKey(hive, path)
                    val, _ = winreg.QueryValueEx(reg_key, key)
                    winreg.CloseKey(reg_key)
                    return val
                except Exception:
                    return None

            raw_version = None
            if browser == "chrome":
                raw_version = get_reg_val(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Google\Chrome\BLBeacon", "version")
            elif browser == "edge":
                raw_version = get_reg_val(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{56EB18F8-B008-4CBD-B6D2-8C97FE7E7558}", "pv")
            elif browser == "brave":
                raw_version = get_reg_val(winreg.HKEY_CURRENT_USER, r"SOFTWARE\BraveSoftware\Brave-Browser\BLBeacon", "version")
            elif browser == "firefox":
                raw_version = get_reg_val(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Mozilla\Mozilla Firefox", "CurrentVersion")
            elif browser == "opera":
                raw_version = get_reg_val(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Opera Software\BLBeacon", "version")
            elif browser == "vivaldi":
                raw_version = get_reg_val(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Vivaldi\BLBeacon", "version")
                
            version = clean_version(raw_version)
            
            if version:
                major = version.split('.')[0]
                if browser == "firefox":
                    return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:{version}) Gecko/20100101 Firefox/{version}"
                elif browser == "edge":
                    return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36 Edg/{major}.0.0.0"
                elif browser == "opera":
                    return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36 OPR/{major}.0.0.0"
                elif browser == "vivaldi":
                    return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36 Vivaldi/{major}.0.0.0"
                elif browser in ("chrome", "brave"):
                    return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
                    
        except Exception:
            pass # Fall through to hardcoded defaults if registry access fails
            
    elif sys.platform == 'darwin':
        import plistlib
        app_paths = {
            "chrome": "/Applications/Google Chrome.app/Contents/Info.plist",
            "edge": "/Applications/Microsoft Edge.app/Contents/Info.plist",
            "brave": "/Applications/Brave Browser.app/Contents/Info.plist",
            "firefox": "/Applications/Firefox.app/Contents/Info.plist",
            "opera": "/Applications/Opera.app/Contents/Info.plist",
            "vivaldi": "/Applications/Vivaldi.app/Contents/Info.plist"
        }
        path = app_paths.get(browser)
        if path and os.path.exists(path):
            try:
                with open(path, 'rb') as f:
                    plist = plistlib.load(f)
                    raw_version = plist.get('CFBundleShortVersionString')
                    version = clean_version(raw_version)
                    
                    if version:
                        major = version.split('.')[0]
                        if browser == "firefox":
                            return f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:{version}) Gecko/20100101 Firefox/{version}"
                        elif browser == "edge":
                            return f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36 Edg/{major}.0.0.0"
                        elif browser == "opera":
                            return f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36 OPR/{major}.0.0.0"
                        elif browser == "vivaldi":
                            return f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36 Vivaldi/{major}.0.0.0"
                        else:
                            return f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36"
            except Exception:
                pass

    # Fallback to hardcoded defaults if dynamic check fails or OS is Linux
    return DEFAULT_USER_AGENTS.get(browser, DEFAULT_USER_AGENTS["chrome"])

class Colors:
    HEADER = '\033[95m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    RESET = Style.RESET_ALL
    BOLD = '\033[1m'

# --- UI Renderer ---
class UIRenderer:
    def __init__(self, chapter_keys):
        self.lock = threading.Lock()
        self.sorted_keys = chapter_keys
        self.total_chapters = len(chapter_keys)
        self.completed_chapters = 0
        self.status = {key: {"status": "Queued", "progress": 0.0} for key in chapter_keys}
        self.height = 0
        self.page_size = 25
        self.view_start_index = 0

    def _render(self):
        if self.height > 0:
            sys.stdout.write(f"\033[{self.height}A")
            
        overall_progress = self.completed_chapters / self.total_chapters if self.total_chapters > 0 else 0
        overall_bar = f"[{'#' * int(overall_progress * 40):<40}]"
        sys.stdout.write(f"{Colors.OKCYAN}--- Uploading ({self.completed_chapters}/{self.total_chapters}) {overall_bar} {overall_progress*100:3.0f}% ---\033[K\n")
        
        end_index = min(self.view_start_index + self.page_size, self.total_chapters)
        chapters_to_display = self.sorted_keys[self.view_start_index:end_index]
        
        for key in chapters_to_display:
            info = self.status[key]
            status_text, progress = info["status"], info["progress"]
            
            bar_color = Colors.OKGREEN if progress == 1.0 and ("✅" in status_text) else (Colors.FAIL if "❌" in status_text else Colors.WARNING)
            bar = f"[{bar_color}{'#' * int(progress * 20):<20}{Colors.RESET}]"
            status_color = Colors.OKGREEN if "✅" in status_text else (Colors.FAIL if "❌" in status_text else "")
            
            line = f"  {key:<30.30}: {status_color}{status_text:<25.25}{Colors.RESET} {bar} {progress*100:3.0f}%"
            sys.stdout.write(f"{line}\033[K\n")
            
        self.height = 1 + len(chapters_to_display)
        sys.stdout.flush()

    def update_chapter_status(self, chap_key, status, progress=None):
        with self.lock:
            if chap_key not in self.status: return
            self.status[chap_key]["status"] = status
            if progress is not None:
                self.status[chap_key]["progress"] = progress
            if self.status[chap_key]["progress"] >= 1.0 and "✅" in status:
                self.completed_chapters += 1
                self._check_and_scroll_view()
            self._render()

    def _check_and_scroll_view(self):
        end_index = min(self.view_start_index + self.page_size, self.total_chapters)
        visible_keys = self.sorted_keys[self.view_start_index:end_index]
        if all(self.status[key]["progress"] == 1.0 for key in visible_keys):
            next_incomplete_index = next((i for i, k in enumerate(self.sorted_keys) if self.status[k]["progress"] < 1.0), -1)
            if next_incomplete_index != -1:
                self.view_start_index = next_incomplete_index
            else:
                self.view_start_index = max(0, self.total_chapters - self.page_size)

    def start(self):
        self.height = 1 + min(self.total_chapters, self.page_size)
        sys.stdout.write("\n" * self.height)
        with self.lock:
            self._render()

# --- Helper Functions ---
def print_success(msg): print(f"{Colors.OKGREEN}[+]{Colors.RESET} {msg}")
def print_info(msg): print(f"{Colors.OKCYAN}[*]{Colors.RESET} {msg}")
def print_warning(msg): print(f"{Colors.WARNING}[!]{Colors.RESET} {msg}")
def print_error(msg): print(f"{Colors.FAIL}[-]{Colors.RESET} {msg}")

def prompt(text, default=None, required=True):
    while True:
        prompt_text = f"{text} [{default}]: " if default else f"{text}: "
        user_input = input(prompt_text).strip()
        if not user_input and default is not None: return default
        if required and not user_input:
            print_warning("This field is required.")
            continue
        return user_input

def natural_sort_key(s): 
    return [float(text) if re.match(r'^-?\d+(?:\.\d+)?$', text) else text.lower() for text in re.split(r'(-?\d+(?:\.\d+)?)', str(s))]

def encode_tus_metadata(meta_dict):
    pairs = []
    for k, v in meta_dict.items():
        if v is None: continue
        val_str = json.dumps(v) if isinstance(v, list) else str(v)
        encoded_val = base64.b64encode(val_str.encode('utf-8')).decode('utf-8')
        pairs.append(f"{k} {encoded_val}")
    return ",".join(pairs)

def parse_filename_details(filename, upload_type="chapter", chapter_naming="extract"):
    name_without_ext = re.sub(r'\.(cbz|zip)$', '', filename, flags=re.IGNORECASE)
    
    # 1. Search the ENTIRE string for the volume/chapter number first
    if upload_type == "volume":
        match = re.search(r'(?:volume|vol\.?|v)\s*(\d+(?:\.\d+)?)', name_without_ext, re.IGNORECASE)
    else:
        match = re.search(r'(?:chapter|ch\.?|c)\s*(\d+(?:\.\d+)?)', name_without_ext, re.IGNORECASE)
        
    num = float(match.group(1)) if match else None
    
    if num is None:
        # Fallback: find the first number in the string if no specific prefix was matched
        match = re.search(r'(\d+(?:\.\d+)?)', name_without_ext)
        num = float(match.group(1)) if match else None

    if num is None:
        return None, None

    # 2. For volumes, format the number to always have exactly 2 decimal places
    # e.g. 5 becomes "Vol. 5.00", 5.5 becomes "Vol. 5.50"
    if upload_type == "volume" and num is not None:
        title = f"Vol. {num:.2f}"
        return num, title

    # 3. Chapter Naming Preset — override messy filenames with clean "Chapter X"
    if chapter_naming == "preset" and num is not None:
        return num, f"Chapter {num:g}"

    # 4. For chapters (Auto-detect), extract a meaningful title by removing the matched number portion
    title = None
    parts = name_without_ext.split(' - ', 1)
    
    if len(parts) > 1:
        # Check which part contains the chapter number by using the match's exact position
        split_idx = name_without_ext.find(' - ')
        part0_has_num = match.start() < split_idx if match else False
            
        if part0_has_num:
            # Number is in the first part (e.g. "c07 - Title")
            title = parts[1].strip()
        else:
            # Number is in the second part (e.g. "Title - c07")
            title = parts[0].strip()
            # If there's text after the chapter number in the second part, append it
            # E.g. "Title - c07 - Extra" becomes "Title - Extra"
            if match:
                remaining = parts[1].replace(match.group(0), '').strip(' -_')
                if remaining:
                    title = f"{title} - {remaining}"
    else:
        # No dash, just remove the matched chapter identifier to isolate the title
        if match:
            title = name_without_ext.replace(match.group(0), '').strip(' -_')
            if not title: 
                title = None
        else:
            title = None

    return num, title

def get_files_in_dir(directory, upload_type, chapter_naming="extract"):
    valid_extensions = ('.cbz', '.zip')
    files_data = []
    
    for filename in os.listdir(directory):
        if not filename.lower().endswith(valid_extensions): continue
        filepath = os.path.join(directory, filename)
        if not os.path.isfile(filepath): continue
            
        num, title = parse_filename_details(filename, upload_type, chapter_naming)
        if num is None:
            print_warning(f"Could not detect {upload_type} number from '{filename}'. Skipping.")
            continue
            
        files_data.append({
            "filepath": filepath,
            "filename": filename,
            "number": num,
            "title": title,
            "size": os.path.getsize(filepath)
        })
        
    files_data.sort(key=lambda x: x["number"])
    return files_data

def validate_session(session):
    res = session.get(f"{BASE_URL}/api/profile", timeout=30)
    if res.status_code == 200:
        data = res.json()
        if "profile" in data and "email" in data["profile"]:
            return data['profile']['email']
    return None

def search_manga(query, session):
    url = f"{BASE_URL}/search.data?search={query}"
    res = session.get(url, timeout=30)
    if res.status_code != 200: return []
    try: arr = res.json()
    except: return []
        
    mangas = []
    for item in arr:
        if isinstance(item, dict):
            decoded = {}
            for k, v in item.items():
                if k.startswith('_') and k[1:].isdigit():
                    key_idx = int(k[1:])
                    if key_idx < len(arr):
                        key_str = arr[key_idx]
                        val = arr[v] if isinstance(v, int) and v < len(arr) else v
                        decoded[key_str] = val
                else: decoded[k] = v
            
            if "id" in decoded and "title" in decoded and isinstance(decoded["id"], int):
                if "photo" in decoded or "status" in decoded: mangas.append(decoded)
                    
    seen = set()
    return [m for m in mangas if not (m["id"] in seen or seen.add(m["id"]))]

def search_groups(query, session):
    res = session.get(f"{BASE_URL}/api/groups?q={query}&limit=25", timeout=30)
    if res.status_code != 200: return []
    try: return res.json().get("groups", [])
    except: return []

# --- Worker Function for TUS ---
def upload_file_tus_worker(session, renderer, file_info, manga_id, group_ids, upload_type, batch_id, language, scanlator_name):
    filename = file_info["filename"]
    filepath = file_info["filepath"]
    size = file_info["size"]
    
    tus_metadata = {
        "manga_id": manga_id,
        "chapter_number": "0" if upload_type == "volume" else file_info["number"],
        "language": language,
        "group_ids": group_ids,
        "group_id": group_ids[0] if group_ids else 0,
        "upload_type": upload_type,
        "batch_id": batch_id,
        "name": filename,
        "type": "application/zip",
        "filetype": "application/zip",
        "filename": filename
    }
    
    if upload_type == "volume": tus_metadata["volume_number"] = file_info["number"]
    if file_info.get("title"): tus_metadata["chapter_title"] = file_info["title"]
    if scanlator_name: tus_metadata["scanlator_name"] = scanlator_name

    encoded_metadata = encode_tus_metadata(tus_metadata)
    headers = {"Tus-Resumable": "1.0.0", "Upload-Length": str(size), "Upload-Metadata": encoded_metadata}

    # Create TUS Upload
    for attempt in range(MAX_RETRIES):
        try:
            renderer.update_chapter_status(filename, "Creating upload...", 0.0)
            res = session.post(TUS_ENDPOINT, headers=headers, timeout=600)
            res.raise_for_status()
            upload_location = res.headers.get("Location")
            if not upload_location: raise ValueError("No Location header")
            break
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                renderer.update_chapter_status(filename, f"Create Err... Retrying", 0.0)
                time.sleep(RETRY_DELAY)
            else:
                return {"key": filename, "success": False, "error": f"Init failed: {str(e)[:30]}"}

    # Upload Chunks — 4.9 MB to stay well within server limits
    chunk_size = int(4.9 * 1024 * 1024)
    offset = 0
    
    try:
        with open(filepath, 'rb') as f:
            while offset < size:
                chunk = f.read(chunk_size)
                
                for attempt in range(MAX_RETRIES):
                    patch_headers = {
                        "Tus-Resumable": "1.0.0",
                        "Upload-Offset": str(offset),
                        "Content-Type": "application/offset+octet-stream",
                    }
                    try:
                        renderer.update_chapter_status(filename, "Uploading...", offset/size)
                        patch_res = session.patch(upload_location, headers=patch_headers, data=chunk, timeout=600)
                        
                        if patch_res.status_code == 204:
                            offset += len(chunk)
                            break
                        elif patch_res.status_code in RETRYABLE_STATUSES:
                            raise requests.exceptions.HTTPError(f"HTTP {patch_res.status_code}")
                        else:
                            return {"key": filename, "success": False, "error": f"HTTP {patch_res.status_code}"}
                    except Exception as e:
                        if attempt < MAX_RETRIES - 1:
                            renderer.update_chapter_status(filename, f"Chunk Err... Retrying", offset/size)
                            time.sleep(RETRY_DELAY)
                        else:
                            return {"key": filename, "success": False, "error": f"Chunk failed: {str(e)[:30]}"}
                            
    except Exception as e:
        return {"key": filename, "success": False, "error": str(e)[:30]}
        
    renderer.update_chapter_status(filename, "✅ Uploaded", 1.0)
    return {"key": filename, "success": True}

# ==============================================================================
# MAIN FUNCTION
# ==============================================================================
def print_files_table(files, upload_type):
    # Print a formatted table of parsed files — shared by dry-run and real upload.
    total_size = sum(f["size"] for f in files)
    size_mb = total_size / (1024 * 1024)

    print_success(f"Found {len(files)} file(s)  ({size_mb:.1f} MB total)\n")

    col_file  = max((len(f["filename"]) for f in files), default=8)
    col_file  = max(col_file, 8)
    col_num   = 10
    col_title = 30

    header = (
        f"  {'Filename':<{col_file}}  "
        f"{'Number':<{col_num}}  "
        f"{'Title':<{col_title}}  "
        f"{'Size':>10}"
    )
    print(f"{Colors.OKCYAN}{header}{Colors.RESET}")
    print(f"  {'-' * col_file}  {'-' * col_num}  {'-' * col_title}  {'-' * 10}")

    for f in files:
        num_str   = str(f["number"])
        title_str = f["title"] if f["title"] else "-"
        sz_str    = f"{f['size'] / (1024 * 1024):.2f} MB"
        print(
            f"  {f['filename']:<{col_file}}  "
            f"{num_str:<{col_num}}  "
            f"{title_str:<{col_title}}  "
            f"{sz_str:>10}"
        )
    print("")


def run_dry_run():
    # Dry-run mode: scan a directory and show parsed chapters without any login or network calls.
    print(f"{Colors.HEADER}{Colors.BOLD}")
    print("========================================")
    print("   MangaDot.net Batch Uploader          ")
    print("   *** DRY RUN MODE (no upload) ***     ")
    print("========================================")
    print(f"{Colors.RESET}")

    # --- Directory ---
    while True:
        prompt_txt = "Enter the directory path containing your .cbz/.zip files"
        if os.path.isdir(DEFAULT_CHAPTERS_DIR):
            directory = prompt(prompt_txt, default=DEFAULT_CHAPTERS_DIR)
        else:
            directory = prompt(prompt_txt)
        if os.path.isdir(directory):
            break
        print_error("Directory does not exist. Please try again.")

    # --- Upload type (affects number parsing) ---
    upload_type_choice = prompt("Upload type? (1) Chapter  (2) Volume", default="1")
    upload_type = "volume" if upload_type_choice == "2" else "chapter"

    # --- Chapter Naming Preset ---
    chapter_naming = "extract"
    if upload_type == "chapter":
        naming_choice = prompt("Chapter naming format? (1) Auto-detect title  (2) Force 'Chapter X'", default="2")
        chapter_naming = "preset" if naming_choice == "2" else "extract"

    # --- Scan Files ---
    print("\n" + "-"*40 + "\n")
    print_info("Scanning directory for files...")
    files = get_files_in_dir(directory, upload_type, chapter_naming)
    if not files:
        print_error("No valid .cbz or .zip files found in the directory.")
        sys.exit(1)

    print_files_table(files, upload_type)

    # --- Missing Sequence Warning ---
    numbers = [f["number"] for f in files]
    int_numbers = sorted(list(set(int(n) for n in numbers if n == int(n))))
    
    missing = []
    if len(int_numbers) > 1:
        for i in range(len(int_numbers) - 1):
            if int_numbers[i+1] - int_numbers[i] > 1:
                missing.extend(range(int_numbers[i] + 1, int_numbers[i+1]))
                
    if missing:
        term = "chapters" if upload_type == "chapter" else "volumes"
        if len(missing) <= 15:
            missing_str = ", ".join(map(str, missing))
            print_warning(f"Missing {term} detected in sequence: {missing_str}")
        else:
            print_warning(f"Missing {term} detected: {len(missing)} {term} are missing between {missing[0]} and {missing[-1]}.")
        print_warning("Please verify this is intentional before proceeding.\n")

    print(f"{Colors.OKGREEN}[Dry run complete — no files were uploaded.]{Colors.RESET}")
    input(f"\n{Colors.WARNING}Press Enter to exit...{Colors.RESET}")
    sys.exit(0)

def main():
    parser = argparse.ArgumentParser(description="MangaDot.net Batch Uploader")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scan a directory and preview parsed chapters without logging in or uploading anything."
    )
    args, _ = parser.parse_known_args()

    if args.dry_run:
        run_dry_run()

    print(f"{Colors.HEADER}{Colors.BOLD}")
    print("========================================")
    print("      MangaDot.net Batch Uploader       ")
    print("========================================")
    print(f"{Colors.RESET}")

    req_session = requests.Session()
    req_session.headers.update({
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/"
    })

    # ── Mount a plain HTTPAdapter with NO urllib3-level retries. ──
    # This prevents urllib3 from filtering PATCH/POST out of its
    # allowed_methods, which would silently swallow retries.
    # All retry logic is handled by the script's own manual loops.
    no_retry_adapter = HTTPAdapter(max_retries=0)
    req_session.mount("https://", no_retry_adapter)
    req_session.mount("http://", no_retry_adapter)
    
    # Supported rookiepy browser functions mapped to index
    supported_browsers = {
        "1": ("chrome", rookiepy.chrome),
        "2": ("firefox", rookiepy.firefox),
        "3": ("brave", rookiepy.brave),
        "4": ("edge", rookiepy.edge),
        "5": ("opera", rookiepy.opera),
        "6": ("vivaldi", rookiepy.vivaldi)
    }
    
    current_browser = "firefox"
    
    # ---------------------------------------------------------
    # Authentication & Cookie Extraction Loop
    # ---------------------------------------------------------
    while True:
        print_info(f"Attempting to extract cookies from {current_browser.title()}...")
        
        # Dynamically align User-Agent based on selected browser's actual installed version
        selected_ua = get_dynamic_user_agent(current_browser)
        req_session.headers.update({"User-Agent": selected_ua})
        
        extracted_successfully = False
        try:
            # Clear previous failed attempts
            req_session.cookies.clear()
            
            # Find the rookiepy function matching current_browser
            get_cookies_fn = next((fn for name, fn in supported_browsers.values() if name == current_browser), None)
            
            if get_cookies_fn:
                browser_cookies = get_cookies_fn(domains=["mangadot.net", ".mangadot.net"])
                if browser_cookies:
                    for cookie in browser_cookies:
                        req_session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])
                    extracted_successfully = True
                else:
                    print_warning(f"No Mangadot.net cookies found in {current_browser.title()}.")
            else:
                print_error(f"Internal Error: browser mapping not found.")
                
        except Exception as e:
            print_warning(f"Failed to extract cookies from {current_browser.title()}: {e}")
            print_warning(f"Note: If using {current_browser.title()}, make sure the browser is fully CLOSED before running this script.")
            
        if extracted_successfully:
            print_info("Validating session with Mangadot...")
            email = validate_session(req_session)
            if email:
                print_success(f"Successfully authenticated as: {email}")
                break
            else:
                print_warning("Cookies extracted, but session validation failed (unauthorized or expired).")
                print_warning("Ensure you have passed the Cloudflare check and are logged in on your browser.")
        
        # If we failed to extract or validate, prompt to switch browser
        print_info("\nAuthentication failed. Please select an option to retry:")
        for key, (name, _) in supported_browsers.items():
            active_marker = f" {Colors.OKCYAN}(active){Colors.RESET}" if name == current_browser else ""
            print(f"  [{key}] {name.title()}{active_marker}")
        print("  [q] Quit script")
        
        choice = prompt("Select an option", default="1").lower()
        if choice == 'q':
            print_info("Exiting script.")
            sys.exit(0)
        elif choice in supported_browsers:
            current_browser = supported_browsers[choice][0]
        else:
            print_error("Invalid selection. Defaulting back to Chrome.")
            current_browser = "chrome"

    print("\n" + "-"*40 + "\n")

    # Directory
    while True:
        prompt_txt = "Enter the directory path containing your .cbz/.zip files"
        if os.path.isdir(DEFAULT_CHAPTERS_DIR):
            directory = prompt(prompt_txt, default=DEFAULT_CHAPTERS_DIR)
        else:
            directory = prompt(prompt_txt)
            
        if os.path.isdir(directory): break
        print_error("Directory does not exist. Please try again.")

    # Manga ID
    manga_id = None
    while not manga_id:
        m_input = prompt("Enter the Target Manga ID (or type 's' to search)")
        if m_input.lower() == 's':
            q = prompt("Enter manga title to search")
            results = search_manga(q, req_session)
            if not results:
                print_warning("No manga found. Try another search.")
                continue
            for i, m in enumerate(results): print(f"  [{i+1}] {m['title']} (ID: {m['id']})")
            sel = prompt(f"Select a number 1-{len(results)} (or type 'c' to cancel)")
            if sel.lower() == 'c': continue
            try:
                sel_idx = int(sel) - 1
                manga_id = results[sel_idx]['id']
                print_success(f"Selected Manga: {results[sel_idx]['title']} (ID: {manga_id})")
            except (ValueError, IndexError): print_error("Invalid selection.")
        else:
            try: manga_id = int(m_input)
            except ValueError: print_error("Invalid ID.")

    req_session.headers.update({"Referer": f"{BASE_URL}/manga/{manga_id}/upload"})

    upload_type_choice = prompt("Upload type? (1) Chapter (2) Volume", default="1")
    upload_type = "volume" if upload_type_choice == "2" else "chapter"

    # --- Chapter Naming Preset ---
    chapter_naming = "extract"
    if upload_type == "chapter":
        naming_choice = prompt("Chapter naming format? (1) Auto-detect title  (2) Force 'Chapter X'", default="2")
        chapter_naming = "preset" if naming_choice == "2" else "extract"

    language = prompt("Language code", default="en")

    is_group = prompt("Upload as a Group? (y/n)", default="y").lower().startswith('y')
    group_id = 0
    group_ids = []
    scanlator_name = None

    if is_group:
        while not group_ids:
            g_input = prompt("Enter Scanlation Group ID (or type 's' to search)")
            if g_input.lower() == 's':
                q = prompt("Enter group name to search")
                results = search_groups(q, req_session)
                if not results:
                    print_warning("No groups found. Try another search.")
                    continue
                for i, g in enumerate(results): print(f"  [{i+1}] {g['name']} (ID: {g['id']})")
                sel = prompt(f"Select a number 1-{len(results)} (or type 'c' to cancel)")
                if sel.lower() == 'c': continue
                try:
                    sel_idx = int(sel) - 1
                    group_id = results[sel_idx]['id']
                    group_ids = [group_id]
                    print_success(f"Selected Group: {results[sel_idx]['name']} (ID: {group_id})")
                except (ValueError, IndexError): print_error("Invalid selection.")
            else:
                try:
                    group_id = int(g_input)
                    group_ids = [group_id]
                except ValueError: print_error("Invalid ID.")
    else:
        scanlator_name = prompt("Enter your individual Scanlator Name")

    while True:
        try:
            threads_str = prompt("Enter number of parallel uploads (1-10)", default="3")
            thread_count = int(threads_str)
            if 1 <= thread_count <= 10: break
            else: print_error("Please enter a number between 1 and 10.")
        except ValueError: print_error("Invalid input.")

        # --- Scan Files ---
    print("\n" + "-"*40 + "\n")
    print_info("Scanning directory for files...")
    files = get_files_in_dir(directory, upload_type, chapter_naming)
    if not files:
        print_error("No valid .cbz or .zip files found in the directory.")
        sys.exit(1)

    print_files_table(files, upload_type)

    # --- Missing Sequence Warning ---
    numbers = [f["number"] for f in files]
    int_numbers = sorted(list(set(int(n) for n in numbers if n == int(n))))
    
    missing = []
    if len(int_numbers) > 1:
        for i in range(len(int_numbers) - 1):
            if int_numbers[i+1] - int_numbers[i] > 1:
                missing.extend(range(int_numbers[i] + 1, int_numbers[i+1]))
                
    if missing:
        term = "chapters" if upload_type == "chapter" else "volumes"
        if len(missing) <= 15:
            missing_str = ", ".join(map(str, missing))
            print_warning(f"Missing {term} detected in sequence: {missing_str}")
        else:
            print_warning(f"Missing {term} detected: {len(missing)} {term} are missing between {missing[0]} and {missing[-1]}.")
        print_warning("Please verify this is intentional before proceeding.\n")

    confirm = prompt("Proceed with upload? (y/n)", default="y").lower()
    if not confirm.startswith('y'):
        print_info("Upload aborted by user.")
        sys.exit(0)

    chunks = [files[i:i + MAX_BATCH_SIZE] for i in range(0, len(files), MAX_BATCH_SIZE)]
    total_chunks = len(chunks)
    
    file_keys = [f["filename"] for f in files]
    renderer = UIRenderer(file_keys)
    renderer.start()
    
    failed_chapters = []

    # --- Batch Process Loop ---
    for chunk_idx, chunk in enumerate(chunks, 1):
        # 1. Initialize Batch
        chapters_payload = []
        for f in chunk:
            chapters_payload.append({
                "chapter_number": f["number"] if upload_type == "chapter" else 0,
                "volume_number": f["number"] if upload_type == "volume" else None,
                "chapter_title": f["title"]
            })
            
        init_payload = {
            "manga_id": manga_id,
            "language": language,
            "group_ids": group_ids,
            "type": upload_type,
            "scanlator_name": scanlator_name,
            "chapters": chapters_payload
        }
        
        try:
            res = req_session.post(BATCH_INIT_ENDPOINT, json=init_payload, timeout=600)
            res.raise_for_status()
            batch_data = res.json()
            if not batch_data.get("success"): raise Exception(str(batch_data))
            batch_id = batch_data["batch_id"]
        except Exception as e:
            for f in chunk: 
                renderer.update_chapter_status(f["filename"], f"❌ Batch Init Failed", 1.0)
                failed_chapters.append(f["filename"])
            continue

        # 2. Upload chunk via TUS with ThreadPoolExecutor
        with concurrent.futures.ThreadPoolExecutor(max_workers=thread_count) as executor:
            futures = [executor.submit(
                upload_file_tus_worker, req_session, renderer, f, manga_id, group_ids, upload_type, batch_id, language, scanlator_name
            ) for f in chunk]
            
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if not result['success']:
                    renderer.update_chapter_status(result['key'], f"❌ {result['error']}", 1.0)
                    failed_chapters.append(result['key'])

        # 3. Complete Batch
        try:
            comp_res = req_session.post(f"{BASE_URL}/api/uploads/batch/{batch_id}/complete", timeout=600)
            comp_res.raise_for_status()
        except Exception as e:
            # Just log it silently via the renderer logic
            pass
            
    # Cleanup UI
    sys.stdout.write("\n" * (renderer.height + 1))
    print(f"{Colors.OKCYAN}--- 🎉 All operations complete. ---{Colors.RESET}")

    if failed_chapters:
        print(f"{Colors.FAIL}⚠️ {len(failed_chapters)} chapters failed to upload after all retries.{Colors.RESET}")
        try:
            with open("failed.txt", "w", encoding="utf-8") as f:
                for chap in sorted(failed_chapters, key=natural_sort_key):
                    f.write(f"{chap}\n")
            print(f"A list of failed chapters has been saved to {Colors.OKCYAN}`failed.txt`{Colors.RESET}.")
        except Exception as e:
            print(f"{Colors.FAIL}Could not write to `failed.txt`: {e}")
    else:
        print(f"{Colors.OKGREEN}✅ All chapters were processed successfully!")

    input(f"\n{Colors.WARNING}Press Enter to exit...{Colors.RESET}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n" + Colors.WARNING + "[!] Script interrupted by user." + Colors.RESET)
        sys.exit(0)