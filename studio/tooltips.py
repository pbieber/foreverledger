"""Item tooltips and item search for the Visuals tab, kept in a local cache.

Wowhead supplies each item's tooltip as HTML. It is turned into plain lines of
coloured text here, so nothing from the website ever reaches the page as markup.
Only item IDs and search words are sent, and any failure leaves just the item's name.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path

from icons import WOWHEAD_SECTION, _download

OFFLINE_RETRY = 300
NOT_FOUND_RETRY = 3600
MAX_LINES = 60
MAX_TEXT = 400
COLOURS = {"q", "q0", "q1", "q2", "q3", "q4", "q5", "q6", "q7"}
COINS = {"moneygold": "gold", "moneysilver": "silver", "moneycopper": "copper"}
BREAKS = {"br", "tr", "table", "div", "p"}


class _TooltipParser(HTMLParser):
    """Wowhead tooltip HTML to lines: [{"left": [span], "right": [span], "sell": bool}].

    A span is {"text", "color"} or {"text", "coin"}. A table header cell is the right
    column, as in the game ("Two-Hand ... Sword"). Every line break, row and table ends a line.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines = []
        self.current = self._new_line()
        self.stack = []  # (tag, colour or None, coin or None)
        self.right = 0
        self.sell = 0

    @staticmethod
    def _new_line():
        return {"left": [], "right": [], "sell": False}

    def _end_line(self):
        line = self.current
        for side in ("left", "right"):
            spans = line[side]
            while spans and not spans[0]["text"].strip():
                spans.pop(0)
            if spans:
                spans[0]["text"] = spans[0]["text"].lstrip()
            while spans and not spans[-1]["text"].strip():
                spans.pop()
            if spans:
                spans[-1]["text"] = spans[-1]["text"].rstrip()
        if (line["left"] or line["right"]) and len(self.lines) < MAX_LINES:
            self.lines.append(line)
        self.current = self._new_line()

    def handle_starttag(self, tag, attrs):
        classes = set((dict(attrs).get("class") or "").split())
        if tag in BREAKS:
            self._end_line()
        if tag == "th":
            self.right += 1
        if tag == "div" and "whtt-sellprice" in classes:
            self.sell += 1
        if tag in ("br", "img", "hr", "input", "meta", "wbr"):
            return
        colour = next((c for c in classes if c in COLOURS), None)
        coin = next((COINS[c] for c in classes if c in COINS), None)
        self.stack.append((tag, colour, coin))

    def handle_endtag(self, tag):
        if tag == "th":
            self.right = max(0, self.right - 1)
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break
        if tag in BREAKS:
            self._end_line()
        if tag == "div" and self.sell:
            self.sell -= 1

    def handle_data(self, data):
        if any(tag in ("script", "style") for tag, _, _ in self.stack):
            return
        text = re.sub(r"\s+", " ", data.replace("\xa0", " "))
        if not text:
            return
        colour = next((c for _, c, _ in reversed(self.stack) if c), None)
        coin = next((c for _, _, c in reversed(self.stack) if c), None)
        spans = self.current["right" if self.right else "left"]
        if self.sell:
            self.current["sell"] = True
        if coin and text.strip():
            spans.append({"text": text.strip()[:MAX_TEXT], "coin": coin})
        elif spans and "color" in spans[-1] and spans[-1]["color"] == colour:
            spans[-1]["text"] = (spans[-1]["text"] + text)[:MAX_TEXT]
        else:
            spans.append({"text": text[:MAX_TEXT], "color": colour})

    def close(self):
        super().close()
        self._end_line()
        return self.lines


def parse_tooltip(markup):
    parser = _TooltipParser()
    parser.feed(markup if isinstance(markup, str) else "")
    return parser.close()


def _quality(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 7 else 1


class TooltipStore:
    """Wowhead tooltips by source section and item ID, remembered across restarts."""

    def __init__(self, folder, *, online=True, fetch=_download):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.online, self.fetch = online, fetch
        self.path = self.folder / "tooltips.json"
        self.lock = threading.Lock()
        self.offline_until = 0
        try:
            self.cache = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.cache = {}

    def _save(self):
        self.path.write_text(json.dumps(self.cache), encoding="utf-8")

    def _can_ask(self):
        return self.online and time.time() >= self.offline_until

    def item(self, item_id, source):
        """{"name", "quality", "icon_name", "lines"}, or None when it can't be found right now."""
        section = WOWHEAD_SECTION.get(source, "forever")
        key = f"{section}:{int(item_id)}"
        with self.lock:
            entry = self.cache.get(key)
            if entry is None or entry.get("missing_until", 0) and entry["missing_until"] <= time.time():
                if not self._can_ask():
                    return None
                try:
                    data = json.loads(self.fetch(f"https://nether.wowhead.com/{section}/tooltip/item/{int(item_id)}"))
                    if not isinstance(data, dict) or not isinstance(data.get("tooltip"), str):
                        raise ValueError("no tooltip")
                    entry = {"name": str(data.get("name") or "")[:200], "quality": _quality(data.get("quality")),
                             "icon": data.get("icon") if isinstance(data.get("icon"), str) else None,
                             "tooltip": data["tooltip"][:100_000]}
                except OSError:  # Every network failure: try again in a few minutes.
                    self.offline_until = time.time() + OFFLINE_RETRY
                    return None
                except (ValueError, TypeError):
                    entry = {"missing_until": time.time() + NOT_FOUND_RETRY}
                self.cache[key] = entry
                self._save()
        if "tooltip" not in entry:
            return None
        return {"name": entry["name"], "quality": entry["quality"], "icon_name": entry["icon"],
                "lines": parse_tooltip(entry["tooltip"])}

    def search(self, words, source, limit=15):
        """Items Wowhead knows by these words: [{"item_id", "name", "quality"}]. Empty when offline."""
        if not self._can_ask() or len(words.strip()) < 2:
            return []
        section = WOWHEAD_SECTION.get(source, "forever")
        query = urllib.parse.quote_plus(words.strip()[:100])
        try:
            data = json.loads(self.fetch(f"https://www.wowhead.com/{section}/search/suggestions-template?q={query}"))
        except OSError:
            self.offline_until = time.time() + OFFLINE_RETRY
            return []
        except (ValueError, TypeError):
            return []
        found = []
        for result in data.get("results", []) if isinstance(data, dict) else []:
            item_id = result.get("id") if isinstance(result, dict) else None
            if (result.get("type") == 3 and isinstance(item_id, int) and not isinstance(item_id, bool)
                    and item_id > 0 and isinstance(result.get("name"), str)):
                found.append({"item_id": item_id, "name": result["name"][:200], "quality": _quality(result.get("quality"))})
            if len(found) >= limit:
                break
        return found
