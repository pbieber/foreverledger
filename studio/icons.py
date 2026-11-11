"""Item icons for the charts, kept in a local cache so each is only found once.

Wowhead names an item's icon, in the source's own section, and Pugger's icon folder or
Wowhead supplies the picture. Pugger's pictures matched only by item name can show
another item, so they stand in when Wowhead can't answer and are checked again later.
Only item IDs and names are sent, and any failure leaves a blank slot.
"""
from __future__ import annotations

import base64
import json
import re
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ICON_NAME = re.compile(r"^[A-Za-z0-9_ -]{1,80}$")
NOT_FOUND_RETRY = 3600
OFFLINE_RETRY = 300
MAX_BYTES = 2_000_000
# Which part of Wowhead has the source's items. Mock data uses ordinary item names.
WOWHEAD_SECTION = {"forever": "forever", "tbc": "tbc", "mock": "forever"}


def _download(url):
    request = urllib.request.Request(url, headers={"User-Agent": "LedgerStudio"})
    with urllib.request.urlopen(request, timeout=4) as response:
        return response.read(MAX_BYTES + 1)


def _mime(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None


def _not_found(err):
    """Wowhead answers 404 for an item or icon it doesn't have. That isn't a network failure."""
    return isinstance(err, urllib.error.HTTPError) and err.code == 404


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.casefold().replace("'", "")).strip("-")


class IconStore:
    def __init__(self, folder, pugger=None, *, online=True, fetch=_download, budget=6):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.pugger = Path(pugger) if pugger else None
        self.online, self.fetch, self.budget = online, fetch, budget
        self.index_path = self.folder / "index.json"
        self.lock = threading.Lock()
        self.offline_until = 0
        self._pugger_names = None
        try:
            self.index = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.index = {}

    def _save(self):
        self.index_path.write_text(json.dumps(self.index), encoding="utf-8")

    def _as_data_uri(self, filename):
        try:
            data = (self.folder / Path(filename).name).read_bytes()
        except OSError:
            return None
        mime = _mime(data)
        return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}" if mime else None

    def _copy_in(self, source, name):
        target = f"{name}{source.suffix.lower()}"
        shutil.copyfile(source, self.folder / target)
        return target

    def _from_pugger_items(self, name):
        if not self.pugger:
            return None
        source = self.pugger / "items" / f"{slug(name)}.png"
        return self._copy_in(source, f"item-{slug(name)}") if source.is_file() else None

    def _pugger_icon(self, icon):
        if not self.pugger:
            return None
        if self._pugger_names is None:
            folder = self.pugger / "allwow"
            self._pugger_names = {p.stem.casefold(): p for p in folder.glob("*.png")} if folder.is_dir() else {}
        return self._pugger_names.get(icon.casefold())

    def _icon_name_online(self, name, item_id, source):
        """Wowhead's name for this item's icon. Network errors propagate to the caller.

        New Forever items exist only in Forever's section, and older items can have
        another icon in retail, so the ID is looked up in the source's section.
        """
        section = WOWHEAD_SECTION.get(source, "forever")
        if item_id:
            try:
                data = json.loads(self.fetch(f"https://nether.wowhead.com/{section}/tooltip/item/{int(item_id)}"))
            except urllib.error.HTTPError as err:
                if not _not_found(err):
                    raise
                data = None
            if isinstance(data, dict) and data.get("icon"):
                return data["icon"]
        query = urllib.parse.quote_plus(name)
        data = json.loads(self.fetch(f"https://www.wowhead.com/{section}/search/suggestions-template?q={query}"))
        for result in data.get("results", []):
            if result.get("type") == 3 and str(result.get("name", "")).casefold() == name.casefold():
                return result.get("icon")
        return None

    def _file_for_icon(self, icon):
        """A cached file for a named icon, from Pugger if possible."""
        if not ICON_NAME.match(icon):  # This name came from a website, and becomes a file name.
            return None
        local = self._pugger_icon(icon)
        if local:
            return self._copy_in(local, f"icon-{slug(icon)}")
        data = self.fetch(f"https://wow.zamimg.com/images/wow/icons/large/{urllib.parse.quote(icon.casefold())}.jpg")
        if len(data) > MAX_BYTES or not _mime(data):
            return None
        target = f"icon-{slug(icon)}.jpg"
        (self.folder / target).write_bytes(data)
        return target

    def _find(self, name, item_id, source, deadline, icon_name=None):
        key = name.casefold()
        entry = self.index.get(key, {})
        # An entry with an icon name came from Wowhead. One without was matched by item
        # name, by Pugger or an earlier version, and is only kept until Wowhead answers.
        if entry.get("file") and entry.get("icon"):
            found = self._as_data_uri(entry["file"])
            if found:
                return found
        now = time.time()
        waiting = max(entry.get("missing_until", 0), entry.get("retry_after", 0)) > now and not icon_name
        ask = self.online and self.offline_until <= now <= deadline and not waiting
        icon = filename = None
        answered = False
        if ask:
            try:
                icon = icon_name or self._icon_name_online(name, item_id, source)
                filename = self._file_for_icon(icon) if isinstance(icon, str) else None
                answered = True
            except OSError as err:  # Includes every network failure: try again in a few minutes.
                if _not_found(err):
                    answered = True
                else:
                    self.offline_until = time.time() + OFFLINE_RETRY
            except (ValueError, TypeError):  # An unexpected reply counts as not found.
                answered = True
        if filename:
            self.index[key] = {"file": filename, "icon": icon}
        else:
            kept = entry.get("file")
            filename = kept if kept and (self.folder / Path(kept).name).is_file() else self._from_pugger_items(name)
            if filename:
                self.index[key] = {"file": filename, **({"retry_after": now + NOT_FOUND_RETRY} if answered else {})}
            elif answered:
                self.index[key] = {"missing_until": now + NOT_FOUND_RETRY}
            else:
                return None
        self._save()
        return self._as_data_uri(filename) if filename else None

    def attach(self, rows, source):
        """Give each row an `icon` data URI, or None. Takes a few seconds at most.

        A row that already knows Wowhead's name for its icon (`icon_name`) skips looking it up.
        """
        deadline = time.time() + self.budget
        with self.lock:
            for row in rows:
                row["icon"] = self._find(row["name"], row.get("item_id"), source, deadline, row.pop("icon_name", None))
