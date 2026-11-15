"""Moore Maps in-app updater (same design as Moore PC Mechanic's UpdateService).

Checks GitHub Releases for a newer version, downloads the new MooreMaps.exe,
verifies its size and SHA-256 fingerprint, swaps it in place of the running
.exe, and relaunches.

How the swap works: Windows won't let you overwrite a running .exe, but it
DOES let you rename it. So the running file is renamed to "MooreMaps.exe.old",
the download is moved into its place, the new copy is started, and this one
closes. The next launch deletes the .old file.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime

from . import __version__, EXE_NAME

# ---- Settings -------------------------------------------------------------
# GitHub account and repo the app updates from (github.com/moorejohnedward/Moore-Maps)
GITHUB_OWNER = "moorejohnedward"
GITHUB_REPO = "Moore-Maps"
EXE_ASSET = EXE_NAME
SHA_ASSET = EXE_NAME + ".sha256"
# ----------------------------------------------------------------------------

USER_AGENT = "MooreMaps-Updater"


@dataclass
class UpdateInfo:
    version: tuple
    tag: str
    notes: str
    download_url: str
    size: int
    sha256_url: str | None
    page_url: str

    @property
    def version_text(self) -> str:
        return ".".join(str(x) for x in self.version)


def parse_version(tag: str) -> tuple | None:
    t = tag.strip().lstrip("vV").split("-")[0]
    try:
        parts = [int(x) for x in t.split(".")]
    except ValueError:
        return None
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


CURRENT_VERSION = parse_version(__version__) or (0, 0, 0)


def is_frozen() -> bool:
    """True when running as the built MooreMaps.exe (not from source)."""
    return bool(getattr(sys, "frozen", False))


def current_exe() -> str:
    return sys.executable


def _get(url: str, timeout: float = 20):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout)


class NoReleasesYet(Exception):
    pass


def check(timeout: float = 15, quiet: bool = True) -> UpdateInfo | None:
    """Newest release if it's newer than this copy, otherwise None.
    quiet=True: network problems also return None. quiet=False: they raise, so a
    "Check for updates" click can say what went wrong."""
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
    try:
        with _get(url, timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if quiet:
            return None
        if e.code == 404:
            raise NoReleasesYet("No releases have been published yet.") from e
        raise
    except Exception:
        if quiet:
            return None
        raise
    latest = parse_version(data.get("tag_name", ""))
    if latest is None or latest <= CURRENT_VERSION:
        return None
    exe_url = sha_url = None
    size = 0
    for a in data.get("assets", []):
        name = (a.get("name") or "").lower()
        if name == EXE_ASSET.lower():
            exe_url = a.get("browser_download_url")
            size = int(a.get("size") or 0)
        elif name == SHA_ASSET.lower():
            sha_url = a.get("browser_download_url")
    if not exe_url:
        return None
    return UpdateInfo(latest, data.get("tag_name", ""), data.get("body") or "", exe_url, size, sha_url,
                      data.get("html_url") or f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases")


def cleanup_after_update():
    """Call once at startup: removes the old .exe left behind by the last update."""
    if not is_frozen():
        return
    exe = current_exe()
    folder, name = os.path.split(exe)
    try:
        for f in os.listdir(folder):
            if f.lower().startswith((name + ".old").lower()):
                p = os.path.join(folder, f)
                for _ in range(10):
                    try:
                        os.remove(p)
                        break
                    except OSError:
                        time.sleep(0.3)   # previous copy may still be closing
        if os.path.exists(exe + ".new"):
            os.remove(exe + ".new")
    except OSError:
        pass


def download_and_install(info: UpdateInfo, progress=None):
    """Downloads, verifies and swaps in the new .exe, then starts it.
    The caller should close the app right after this returns."""
    if not is_frozen():
        raise RuntimeError("You're running Moore Maps from source code. Use 'git pull' to update, "
                           "or download MooreMaps.exe from the Releases page.")
    exe = current_exe()
    new_file = exe + ".new"
    old_file = exe + ".old"

    # 1) Download next to the current .exe
    with _get(info.download_url, timeout=60) as r, open(new_file, "wb") as out:
        total = int(r.headers.get("Content-Length") or info.size or 0)
        done = 0
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress and total:
                progress(done / total)

    # 2) Verify: right size, and matches the published SHA-256 fingerprint
    if info.size and os.path.getsize(new_file) != info.size:
        os.remove(new_file)
        raise IOError("The download was incomplete. Please try again.")
    if info.sha256_url:
        with _get(info.sha256_url) as r:
            expected = r.read().decode("ascii", "ignore").split()[0].strip().lower()
        h = hashlib.sha256()
        with open(new_file, "rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                h.update(block)
        if expected and h.hexdigest().lower() != expected:
            os.remove(new_file)
            raise IOError("The download didn't pass its safety check, so it wasn't installed.")

    # 3) Swap: move the running exe out of the way, move the new one in.
    if os.path.exists(old_file):
        try:
            os.remove(old_file)
        except OSError:
            old_file = exe + ".old-" + datetime.now().strftime("%Y%m%d%H%M%S")
    try:
        os.rename(exe, old_file)
    except PermissionError:
        os.remove(new_file)
        raise PermissionError("Windows blocked the update in this folder. Move MooreMaps.exe to a folder "
                              "you own (for example C:\\Moore\\Apps) and try again.")
    try:
        os.rename(new_file, exe)
    except OSError:
        os.rename(old_file, exe)          # put the original back if anything went wrong
        raise

    # 4) Start the new version. A one-file PyInstaller app passes hidden settings to
    #    child processes; reset them so the new copy unpacks itself fresh.
    env = os.environ.copy()
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    for k in list(env):
        if k.startswith("_PYI") or k == "_MEIPASS2":
            env.pop(k, None)
    if os.name != "nt":
        os.chmod(exe, 0o755)
    flags = (0x00000008 | 0x00000200) if os.name == "nt" else 0   # DETACHED_PROCESS | NEW_PROCESS_GROUP
    subprocess.Popen([exe, "--updated"], env=env, close_fds=True, creationflags=flags)


# ---- "Skip this version" and auto-check preferences -----------------------
def settings_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    d = os.path.join(base, "Moore Maps")
    os.makedirs(d, exist_ok=True)
    return d


def _settings_file():
    return os.path.join(settings_dir(), "update-settings.json")


def _load() -> dict:
    try:
        with open(_settings_file(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(d: dict):
    try:
        with open(_settings_file(), "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
    except Exception:
        pass


def get_check_on_startup() -> bool:
    return bool(_load().get("check_on_startup", True))


def set_check_on_startup(v: bool):
    d = _load()
    d["check_on_startup"] = bool(v)
    _save(d)


def is_skipped(info: UpdateInfo) -> bool:
    return _load().get("skipped_version") == info.version_text


def skip(info: UpdateInfo):
    d = _load()
    d["skipped_version"] = info.version_text
    _save(d)
