import sys

# ==============================================================================
# 🛑 PYTHON VERSION CHECK
# ==============================================================================
if sys.version_info[:2] != (3, 12):
    print(f"Error: This script strictly requires Python 3.12.")
    print(f"You are currently using Python {sys.version_info.major}.{sys.version_info.minor}.")
    print("Please run the script using the following command:")
    print("  py -3.12 mangadot_uploader.py")
    sys.exit(1)

import os
import re
import json
import base64
import time
import threading
import concurrent.futures
import logging
from pathlib import Path

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    import rookiepy
    from colorama import init, Fore, Style
    init(autoreset=True)  # Enable ANSI colors for Windows
except ImportError:
    print("Missing required libraries. Please run:")
    print("py -3.12 -m pip install -r requirements.txt")
    sys.exit(1)

# ==============================================================================
# ⚙️ CONFIGURATION
# ==============================================================================

BASE_URL = "https://mangadot.net"
TUS_ENDPOINT = f"{BASE_URL}/api/tus/"
BATCH_INIT_ENDPOINT = f"{BASE_URL}/api/uploads/batch/init"

MAX_BATCH_SIZE = 100
MAX_RETRIES = 3
RETRY_DELAY = 5
RETRYABLE_STATUSES = [429, 500, 502, 503, 504, 524]
DEFAULT_CHAPTERS_DIR = "chapters"

DEFAULT_USER_AGENTS = {
    "chrome": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    "firefox": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:151.0) Gecko/20100101 Firefox/151.0",
    "brave": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
    "edge": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36 Edg/137.0.0.0",
    "opera": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36 OPR/122.0.0.0",
    "vivaldi": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36 Vivaldi/7.4.3684.38"
}

class Colors:
    HEADER = '\033[95m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    RESET = Style.RESET_ALL
    BOLD = '\033[1m'

# --- Logger Setup ---
logging.basicConfig(
    filename='api_requests.log',
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

def log_request_response(response, *args, **kwargs):
    req = response.request
    logging.debug(f"=== HTTP {req.method} {req.url} ===")
    logging.debug("--- REQUEST HEADERS ---")
    for k, v in req.headers.items():
        logging.debug(f"{k}: {v}")
    
    if req.body:
        try:
            body_len = len(req.body)
            logging.debug(f"--- REQUEST BODY (Size: {body_len} bytes) ---")
            if body_len < 2000 and not isinstance(req.body, bytes):
                logging.debug(req.body)
            elif isinstance(req.body, bytes):
                logging.debug("<Binary Data / File Chunk>")
        except Exception:
            logging.debug("--- REQUEST BODY (Size: Unknown) ---")
            
    logging.debug(f"--- RESPONSE STATUS: {response.status_code} {response.reason} ---")
    logging.debug("--- RESPONSE HEADERS ---")
    for k, v in response.headers.items():
        logging.debug(f"{k}: {v}")
        
    logging.debug("--- RESPONSE BODY ---")
    try:
        resp_text = response.text
        if len(resp_text) > 1000:
            logging.debug(f"{resp_text[:1000]}... (truncated)")
        else:
            logging.debug(resp_text)
    except Exception:
        logging.debug("<Binary or Unreadable Response>")
    logging.debug("===============================================================\n")

# --- UI Renderer ---
class UIRenderer:
    def __init__(self, chapter_keys):
        self.lock = threading.Lock()
        self.sorted_keys = chapter_keys
        self.total_chapters = len(chapter_keys)
        self.processed_chapters = 0
        self.successful_chapters = 0
        self.status = {key: {"status": "Queued", "progress": 0.0} for key in chapter_keys}
        self.height = 0
        self.page_size = 25
        self.view_start_index = 0

    def _render(self):
        if self.height > 0:
            sys.stdout.write(f"\033[{self.height}A")
            
        overall_progress = self.processed_chapters / self.total_chapters if self.total_chapters > 0 else 0
        overall_bar = f"[{'#' * int(overall_progress * 40):<40}]"
        sys.stdout.write(f"{Colors.OKCYAN}--- Processing ({self.processed_chapters}/{self.total_chapters}) {overall_bar} {overall_progress*100:3.0f}% ---\033[K\n")
        
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
            
            was_done = self.status[chap_key]["progress"] >= 1.0
            self.status[chap_key]["status"] = status
            
            if progress is not None:
                self.status[chap_key]["progress"] = progress
                
            is_done = self.status[chap_key]["progress"] >= 1.0
            
            if not was_done and is_done:
                self.processed_chapters += 1
                if "✅" in status:
                    self.successful_chapters += 1
                self._check_and_scroll_view()
                
            self._render()

    def _check_and_scroll_view(self):
        end_index = min(self.view_start_index + self.page_size, self.total_chapters)
        visible_keys = self.sorted_keys[self.view_start_index:end_index]
        if all(self.status[key]["progress"] >= 1.0 for key in visible_keys):
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

def parse_filename_details(filename, upload_type="chapter"):
    name_without_ext = re.sub(r'\.(cbz|zip)$', '', filename, flags=re.IGNORECASE)
    
    parts = name_without_ext.split(' - ', 1)
    title = parts[1].strip() if len(parts) > 1 else None
    
    number_str = parts[0]
    
    if upload_type == "volume":
        match = re.search(r'(?:volume|vol\.?|v)\s*(\d+(?:\.\d+)?)', number_str, re.IGNORECASE)
    else:
        match = re.search(r'(?:chapter|ch\.?|c)\s*(\d+(?:\.\d+)?)', number_str, re.IGNORECASE)
        
    num = float(match.group(1)) if match else None
    if num is None:
        match = re.search(r'(\d+(?:\.\d+)?)', number_str)
        num = float(match.group(1)) if match else None

    # For volumes, always use "Vol. {number}.00" as the chapter title
    if upload_type == "volume" and num is not None:
        title = f"Vol. {num:g}.00"

    return num, title

def get_files_in_dir(directory, upload_type):
    valid_extensions = ('.cbz', '.zip')
    files_data = []
    for filename in os.listdir(directory):
        if not filename.lower().endswith(valid_extensions): continue
        filepath = os.path.join(directory, filename)
        if not os.path.isfile(filepath): continue
            
        num, title = parse_filename_details(filename, upload_type)
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
    res = session.get(f"{BASE_URL}/api/profile", timeout=15)
    if res.status_code == 200:
        data = res.json()
        if "profile" in data and "email" in data["profile"]:
            return data['profile']['email']
    return None

def search_manga(query, session):
    url = f"{BASE_URL}/search.data?search={query}"
    res = session.get(url, timeout=15)
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
    res = session.get(f"{BASE_URL}/api/groups?q={query}&limit=25", timeout=15)
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
    if scanlator_name: tus_metadata["scanlator_name"] = scanlator_name

    encoded_metadata = encode_tus_metadata(tus_metadata)
    headers = {"Tus-Resumable": "1.0.0", "Upload-Length": str(size), "Upload-Metadata": encoded_metadata}

    # Create TUS Upload
    upload_location = None
    for attempt in range(MAX_RETRIES):
        try:
            renderer.update_chapter_status(filename, "Creating upload...", 0.0)
            res = session.post(TUS_ENDPOINT, headers=headers, timeout=30)
            res.raise_for_status()
            upload_location = res.headers.get("Location")
            if not upload_location: raise ValueError("No Location header")
            break
        except Exception as e:
            logging.error(f"[{filename}] TUS Init Error (Attempt {attempt+1}): {e}")
            if attempt < MAX_RETRIES - 1:
                renderer.update_chapter_status(filename, f"Create Err... Retrying", 0.0)
                time.sleep(RETRY_DELAY)
            else:
                return {"key": filename, "success": False, "error": f"Init failed: {str(e)[:30]}"}

    # Upload Chunks
    chunk_size = 20 * 1024 * 1024
    offset = 0
    
    try:
        with open(filepath, 'rb') as f:
            while offset < size:
                f.seek(offset)
                chunk = f.read(chunk_size)
                
                for attempt in range(MAX_RETRIES):
                    patch_headers = {
                        "Tus-Resumable": "1.0.0",
                        "Upload-Offset": str(offset),
                        "Content-Type": "application/offset+octet-stream",
                    }
                    try:
                        renderer.update_chapter_status(filename, "Uploading...", offset/size)
                        patch_res = session.patch(upload_location, headers=patch_headers, data=chunk, timeout=60)
                        
                        if patch_res.status_code == 204:
                            offset += len(chunk)
                            break
                        elif patch_res.status_code in RETRYABLE_STATUSES:
                            raise requests.exceptions.HTTPError(f"HTTP {patch_res.status_code}")
                        else:
                            return {"key": filename, "success": False, "error": f"HTTP {patch_res.status_code}"}
                    except Exception as e:
                        logging.error(f"[{filename}] TUS Chunk Error (Attempt {attempt+1}): {e}")
                        if attempt < MAX_RETRIES - 1:
                            renderer.update_chapter_status(filename, f"Chunk Err... Retrying", offset/size)
                            time.sleep(RETRY_DELAY)
                            
                            # Server offset recovery query (True TUS Resumability)
                            try:
                                head_res = session.head(upload_location, headers={"Tus-Resumable": "1.0.0"}, timeout=15)
                                if head_res.status_code == 200 and "Upload-Offset" in head_res.headers:
                                    offset = int(head_res.headers["Upload-Offset"])
                                    f.seek(offset)
                                    chunk = f.read(chunk_size)
                            except Exception as head_err:
                                logging.error(f"[{filename}] TUS HEAD Recovery Error: {head_err}")
                        else:
                            return {"key": filename, "success": False, "error": f"Chunk failed: {str(e)[:30]}"}
                            
    except Exception as e:
        logging.error(f"[{filename}] Unknown Worker Error: {e}")
        return {"key": filename, "success": False, "error": str(e)[:30]}
        
    renderer.update_chapter_status(filename, "✅ Uploaded", 1.0)
    return {"key": filename, "success": True}

# ==============================================================================
# MAIN FUNCTION
# ==============================================================================
def main():
    print(f"{Colors.HEADER}{Colors.BOLD}")
    print("========================================")
    print("      MangaDot.net Batch Uploader       ")
    print("========================================")
    print(f"{Colors.RESET}")
    print_info("API requests are being logged to 'api_requests.log'")

    req_session = requests.Session()
    req_session.hooks['response'].append(log_request_response)
    
    # 🛡️ Bulletproof HTTP Retries for the entire Session (handles 502, 503, 429 globally)
    retry_strategy = Retry(
        total=4,
        backoff_factor=1.5,
        status_forcelist=RETRYABLE_STATUSES,
        allowed_methods=["HEAD", "GET", "OPTIONS", "POST", "PATCH"]
    )
    adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=retry_strategy)
    req_session.mount('http://', adapter)
    req_session.mount('https://', adapter)
    
    req_session.headers.update({
        "Origin": BASE_URL,
        "Referer": f"{BASE_URL}/"
    })
    
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
    # Authentication Loop
    # ---------------------------------------------------------
    while True:
        print_info(f"Attempting to extract cookies from {current_browser.title()}...")
        selected_ua = DEFAULT_USER_AGENTS.get(current_browser, DEFAULT_USER_AGENTS["chrome"])
        req_session.headers.update({"User-Agent": selected_ua})
        
        extracted_successfully = False
        try:
            req_session.cookies.clear()
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
            err_msg = str(e).lower()
            if "appbound" in err_msg or "admin" in err_msg:
                print_error(f"Chrome/Edge v130+ requires Admin Privileges to decrypt cookies.")
                print_warning(f"Please either Right Click -> Run as Administrator, or choose another browser like Firefox.")
            else:
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

    # Directory input handling
    while True:
        prompt_txt = "Enter the directory path containing your .cbz/.zip files"
        if os.path.isdir(DEFAULT_CHAPTERS_DIR):
            directory_raw = prompt(prompt_txt, default=DEFAULT_CHAPTERS_DIR)
        else:
            directory_raw = prompt(prompt_txt)
        
        directory = directory_raw.strip(' "\'')
        directory = os.path.normpath(directory)

        if os.path.isdir(directory): 
            break
            
        print_error(f"Directory '{directory}' does not exist. Please try again.")

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
    files = get_files_in_dir(directory, upload_type)
    if not files:
        print_error("No valid .cbz or .zip files found in the directory.")
        sys.exit(1)

    print_success(f"Found {len(files)} files to upload:\n")
    for f in files:
        title_str = f" - {f['title']}" if f['title'] else ""
        print(f"  -> {f['filename']} (Detected {upload_type.title()} {f['number']}{title_str})")
        
    print("")
    confirm = prompt("Proceed with upload? (y/n)", default="y").lower()
    if not confirm.startswith('y'):
        print_info("Upload aborted by user.")
        sys.exit(0)

    chunks = [files[i:i + MAX_BATCH_SIZE] for i in range(0, len(files), MAX_BATCH_SIZE)]
    
    file_keys = [f["filename"] for f in files]
    renderer = UIRenderer(file_keys)
    renderer.start()
    
    failed_chapters = []

    # --- Batch Process Loop ---
    for chunk_idx, chunk in enumerate(chunks, 1):
        
        # 🕒 Anti-spam delay between massive chunks
        if chunk_idx > 1:
            time.sleep(3)
            
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
        
        # 🛡️ Wrapped Batch Init in explicit manual retries just in case 
        # local connection errors are thrown that urllib3 Retry misses.
        batch_id = None
        for attempt in range(MAX_RETRIES):
            try:
                res = req_session.post(BATCH_INIT_ENDPOINT, json=init_payload, timeout=30)
                res.raise_for_status()
                batch_data = res.json()
                if not batch_data.get("success"): 
                    raise ValueError(f"API Error: {batch_data}")
                batch_id = batch_data["batch_id"]
                break
            except Exception as e:
                logging.error(f"[Batch {chunk_idx}] Init Error (Attempt {attempt+1}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)

        if not batch_id:
            for f in chunk: 
                renderer.update_chapter_status(f["filename"], f"❌ Init Err", 1.0)
                failed_chapters.append(f["filename"])
            continue

        with concurrent.futures.ThreadPoolExecutor(max_workers=thread_count) as executor:
            futures = [executor.submit(
                upload_file_tus_worker, req_session, renderer, f, manga_id, group_ids, upload_type, batch_id, language, scanlator_name
            ) for f in chunk]
            
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if not result['success']:
                    renderer.update_chapter_status(result['key'], f"❌ {result['error']}", 1.0)
                    failed_chapters.append(result['key'])

        # 🛡️ Wrap Batch Complete with explicit retries as well
        for attempt in range(MAX_RETRIES):
            try:
                comp_res = req_session.post(f"{BASE_URL}/api/uploads/batch/{batch_id}/complete", timeout=30)
                comp_res.raise_for_status()
                break
            except Exception as e:
                logging.error(f"[Batch {chunk_idx}] Complete Error (Attempt {attempt+1}): {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
            
    # Cleanup UI 
    print(f"\n{Colors.OKCYAN}--- 🎉 All operations complete. ---{Colors.RESET}")

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
