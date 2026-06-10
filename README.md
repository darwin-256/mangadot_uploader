# MangaDot.net Batch Uploader

A fast, concurrent, and resumable batch uploader for [MangaDot.net](https://mangadot.net). 
This tool automatically extracts your session cookies directly from your web browser, bypasses basic protections, and securely uploads massive batches of `.cbz` or `.zip` chapters/volumes using the TUS upload protocol.

## Features
- **No Manual Cookies Needed:** Automatically extracts your active MangaDot session from Chrome, Firefox, Brave, Edge, Opera, or Vivaldi.
- **TUS Resumability:** True resumable uploads. If your internet drops on a 200MB volume, it resumes exactly where it left off.
- **Concurrent Uploads:** Upload multiple chapters at the same time (up to 10 threads).
- **Bulletproof Retries:** Handles 502/503/429 Cloudflare and server errors gracefully.
- **Volume & Chapter Support:** Automatically formats titles and numbers properly (e.g., `Vol. 1.00`).
- **Live Terminal UI:** Beautiful progress bars and status updates in the console.

---

## Option 1: Quick Download (Windows .exe)
If you are on Windows, you don't need to install Python. 

1. Go to the [Releases page](../../releases/latest) and download `mangadot_uploader.exe`.
2. Place the `.exe` in a folder.
3. Create a folder named `chapters` next to the `.exe` and put your `.cbz` or `.zip` files inside.
4. Make sure your web browser is fully **CLOSED** so the tool can read your cookies.
5. Double-click `mangadot_uploader.exe` to run it!

> **Note:** Windows Defender might flag the `.exe` as suspicious because it's a new, unassigned program that reads browser cookies. This is a false positive. You may need to click "More Info" -> "Run anyway".

---

## Option 2: Run from Source (Python / Mac / Linux)

### Prerequisites
- **Python 3.12** 
- You must be **logged in** to [MangaDot.net](https://mangadot.net) on your web browser.

### Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/darwin-256/mangadot_uploader.git
   cd mangadot_uploader

2.  Install the required dependencies:
    py -3.12 -m pip install -r requirements.txt
3.  Put your files in the chapters/ folder.
4.  Run the script:
    py -3.12 mangadot_uploader.py

### Log Files

If any uploads fail permanently, the script will generate a failed.txt file
listing the chapters that didn't go through. Detailed HTTP request data is also
logged locally to api_requests.log for debugging.

### License

Distributed under the MIT License. See LICENSE for more information.
