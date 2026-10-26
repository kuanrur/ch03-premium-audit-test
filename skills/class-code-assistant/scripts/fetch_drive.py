"""Download a publicly shared Google Drive folder into a local directory.

The premium audit team keeps the classification guide and the employer files in a
Drive folder shared as "anyone with the link can view". Drive's public embedded
folder view lists a folder's entries without signing in, and the public download
endpoint returns each file's bytes. Only the Python standard library is used.

Usage:
    python3 -I fetch_drive.py <folder_id> <dest_dir>
"""

from __future__ import annotations

import html
import re
import shutil
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

LIST_URL = "https://drive.google.com/embeddedfolderview?id={id}"
DOWNLOAD_URL = "https://drive.google.com/uc?export=download&id={id}"

ENTRY_RE = re.compile(
    r'<div class="flip-entry" id="entry-(?P<id>[A-Za-z0-9_-]+)".*?'
    r'<a href="(?P<href>[^"]+)".*?'
    r'<div class="flip-entry-title">(?P<title>[^<]*)</div>',
    re.S,
)


class FetchError(RuntimeError):
    pass


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "class-code-assistant/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()
    except urllib.error.URLError as exc:
        # python.org builds on macOS ship without a CA bundle; the system curl has one.
        if isinstance(exc.reason, ssl.SSLError) and shutil.which("curl"):
            done = subprocess.run(["curl", "-fsSL", "--max-time", "60", url], capture_output=True)
            if done.returncode == 0:
                return done.stdout
            raise FetchError(f"could not read {url}: curl exit {done.returncode}") from exc
        raise FetchError(f"could not read {url}: {exc}") from exc
    except Exception as exc:  # timeouts and other transport errors
        raise FetchError(f"could not read {url}: {exc}") from exc


def list_folder(folder_id: str) -> list[dict]:
    """Return the folder's entries as dicts with id, title and kind (folder, file, google-doc)."""
    page = _get(LIST_URL.format(id=folder_id)).decode("utf-8", "replace")
    if "flip-entries" not in page:
        raise FetchError(
            f"Drive folder {folder_id} is not publicly listable; check the link and its sharing setting"
        )
    entries = []
    for m in ENTRY_RE.finditer(page):
        href = html.unescape(m.group("href"))
        if "/drive/folders/" in href:
            kind = "folder"
        elif "/file/d/" in href:
            kind = "file"
        else:
            kind = "google-doc"
        entries.append({"id": m.group("id"), "title": html.unescape(m.group("title")).strip(), "kind": kind})
    return entries


def _safe_name(title: str) -> str:
    name = title.replace("/", "_").replace("\\", "_").strip()
    if name in ("", ".", ".."):
        raise FetchError(f"unsafe Drive entry name: {title!r}")
    return name


def fetch_folder(folder_id: str, dest: Path) -> list[Path]:
    """Mirror the folder (recursively) into dest. Google-native docs are skipped."""
    dest.mkdir(parents=True, exist_ok=True)
    written = []
    for entry in list_folder(folder_id):
        target = dest / _safe_name(entry["title"])
        if entry["kind"] == "folder":
            written.extend(fetch_folder(entry["id"], target))
        elif entry["kind"] == "file":
            data = _get(DOWNLOAD_URL.format(id=entry["id"]))
            if data[:15].lower().startswith(b"<!doctype html"):
                raise FetchError(f"Drive returned a web page instead of {entry['title']}; is it shared?")
            target.write_bytes(data)
            written.append(target)
    return written


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        files = fetch_folder(argv[1], Path(argv[2]))
    except FetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for f in files:
        print(f)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
