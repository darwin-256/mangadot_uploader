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

## Prerequisites

- **Python 3.12** (The script is built specifically for 3.12).
- You must be **logged in** to [MangaDot.net](https://mangadot.net) on your web browser.

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/YOUR_USERNAME/mangadot_uploader.git
   cd mangadot_uploader

2.  Install the required Python dependencies specifically for Python 3.12:
    py -3.12 -m pip install -r requirements.txt

### Usage

1.  Put your .cbz or .zip files into the chapters/ folder. (Note: Ensure your
    files are named reasonably, e.g., Chapter 1 - The Beginning.cbz or
    Volume 2.cbz)
2.  Make sure your web browser is fully CLOSED (to allow the script to read the
    cookie database).
3.  Run the script using Python 3.12:
    py -3.12 mangadot_uploader.py
4.  Follow the on-screen prompts to select your browser, search for the target
    Manga, assign Scanlation groups, and start the upload!

Troubleshooting Cookies (Windows): If you are using Chrome or Edge v130+,
they require Administrator Privileges to extract cookies. Right-click your
terminal and select "Run as Administrator", or use Firefox instead.

### Log Files

If any uploads fail permanently, the script will generate a failed.txt file
listing the chapters that didn't go through. Detailed HTTP request data is also
logged locally to api_requests.log for debugging.

### License

Distributed under the MIT License. See LICENSE for more information.
