"""Forever Ledger Studio: a local website for planning episodes and charting ledger data.

Run:  python studio/studio.py        then open http://127.0.0.1:8765
Python 3.10+, standard library only. It listens on this computer only, and only ever
reads WoW's files. TBC, Forever and mock data each stay in their own database. The only
thing it sends out is item IDs, item names and item search words, to Wowhead for icons and
tooltips it doesn't have (--offline stops that).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "ForeverLedger-tools"))

import analytics  # noqa: E402
import icons  # noqa: E402
import ledger  # noqa: E402
import mockdata  # noqa: E402
import store  # noqa: E402
import tooltips  # noqa: E402

SOURCE_LABELS = {"forever": "Forever", "tbc": "TBC Anniversary", "mock": "Mock data"}
CLIENT_FOLDERS = {"tbc": "_anniversary_", "forever": "_forever_"}
DEFAULT_PUGGER_ICONS = HERE.parent.parent / "Pugger" / "PuggerClaude" / "public" / "icons"
DEFAULT_WOW_ROOTS = (r"C:\Program Files (x86)\World of Warcraft", r"C:\Program Files\World of Warcraft",
                     r"C:\Games\World of Warcraft", r"D:\World of Warcraft", r"D:\Games\World of Warcraft")
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/styles.css": ("styles.css", "text/css; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/charts.js": ("charts.js", "text/javascript; charset=utf-8"),
          "/coins.js": ("coins.js", "text/javascript; charset=utf-8"),
          "/mp4.js": ("mp4.js", "text/javascript; charset=utf-8"),
          "/visuals.js": ("visuals.js", "text/javascript; charset=utf-8")}


class Conflict(Exception):
    pass


class Studio:
    """Paths and import state shared by every request."""

    def __init__(self, data_dir, wow_roots=None, *, pugger_icons=DEFAULT_PUGGER_ICONS, online=True):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.icons = icons.IconStore(self.data_dir / "icons", pugger_icons, online=online)
        self.tooltips = tooltips.TooltipStore(self.data_dir / "tooltips", online=online)
        self.plan_path = self.data_dir / "studio.sqlite"
        self.wow_roots = [Path(p) for p in (wow_roots if wow_roots is not None else DEFAULT_WOW_ROOTS)]
        self.import_lock = threading.Lock()
        self.status = {}
        self.seen_path = self.data_dir / "imported-files.json"
        self.seen = self._load_seen()
        with self.plan() as db:
            store.seed(db)
        if not self.ledger_path("mock").exists():
            self.regenerate_mock()

    def plan(self):
        return _Closing(store.connect(self.plan_path))

    def _load_seen(self):
        """When each file was last imported, so a restart doesn't parse unchanged files again."""
        try:
            entries = json.loads(self.seen_path.read_text(encoding="utf-8"))
            return {(entry["source"], entry["path"]): entry["stamp"] for entry in entries}
        except (OSError, ValueError, KeyError, TypeError):
            return {}

    def _save_seen(self):
        entries = [{"source": source, "path": path, "stamp": stamp} for (source, path), stamp in self.seen.items()]
        self.seen_path.write_text(json.dumps(entries), encoding="utf-8")

    def ledger_path(self, source):
        return self.data_dir / f"ledger-{source}.sqlite"

    def read_ledger(self, source):
        """A read-only connection, or None before anything was imported.

        ledger.connect rewrites a view on opening, which would wait on a running import.
        """
        path = self.ledger_path(source)
        if not path.exists():
            return None
        db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=30)
        return _Closing(db)

    def detect_files(self):
        """Register each client's SavedVariables, unless the user removed that file."""
        found = []
        for root in self.wow_roots:
            for source, folder in CLIENT_FOLDERS.items():
                found.extend((source, str(p)) for p in (root / folder / "WTF" / "Account").glob(
                    "*/SavedVariables/ForeverLedger.lua"))
        if found:
            with self.plan() as db, db:
                db.executemany("INSERT OR IGNORE INTO files(source,path) VALUES(?,?)", found)

    def files(self, source):
        with self.plan() as db:
            return [r[0] for r in db.execute(
                "SELECT path FROM files WHERE source=? AND removed=0 ORDER BY path", (source,))]

    def add_file(self, source, path):
        if source not in CLIENT_FOLDERS:
            raise store.Invalid("Mock data has no files")
        path = str(path).strip().strip('"')
        if not Path(path).is_file():
            raise store.Invalid(f"No file at {path}")
        with self.plan() as db, db:
            db.execute("INSERT INTO files(source,path) VALUES(?,?) ON CONFLICT(source,path) DO UPDATE SET removed=0",
                       (source, path))
        self.import_path(source, path)

    def remove_file(self, source, path):
        with self.plan() as db, db:
            db.execute("UPDATE files SET removed=1 WHERE source=? AND path=?", (source, path))
        self.status.pop((source, path), None)
        self.seen.pop((source, path), None)
        self._save_seen()

    def _claimed_elsewhere(self, source, source_id):
        for other in SOURCE_LABELS:
            if other == source:
                continue
            reader = self.read_ledger(other)
            if reader:
                with reader as db:
                    if db.execute("SELECT 1 FROM sources WHERE source_id=?", (source_id,)).fetchone():
                        return other
        return None

    def import_path(self, source, path):
        """Import one file. An account already in another source is refused, keeping the data apart."""
        key = (source, path)
        self.status[key] = {"ok": True, "importing": True, "at": int(time.time())}
        try:
            stamp = Path(path).stat().st_mtime_ns
            with self.import_lock:
                export = ledger.read_export(path)
                other = self._claimed_elsewhere(source, export["sourceID"])
                if other:
                    raise Conflict(f"This account's data is already in {SOURCE_LABELS[other]}. "
                                   "Data sources are kept separate, so it was not imported.")
                db = ledger.connect(self.ledger_path(source))
                try:
                    added = ledger.import_file(db, path, export)
                finally:
                    db.close()
            self.seen[key] = stamp
            self._save_seen()
            self.status[key] = {"ok": True, "added": added, "at": int(time.time())}
        except (OSError, ValueError, KeyError, sqlite3.Error, Conflict) as err:
            self.status[key] = {"ok": False, "error": str(err), "at": int(time.time())}
        return self.status[key]

    def import_changed(self):
        """Import files WoW has saved since the last look. Only touches WoW's files by reading."""
        self.detect_files()
        for source in CLIENT_FOLDERS:
            for path in self.files(source):
                try:
                    stamp = Path(path).stat().st_mtime_ns
                except OSError as err:
                    self.status[(source, path)] = {"ok": False, "error": str(err), "at": int(time.time())}
                    continue
                if self.seen.get((source, path)) != stamp or not self.ledger_path(source).exists():
                    self.import_path(source, path)

    def regenerate_mock(self):
        with self.import_lock:
            path = self.ledger_path("mock")
            if path.exists():
                path.unlink()
            export = self.data_dir / "mock-export.json"
            export.write_text(json.dumps(mockdata.build_export()), encoding="utf-8")
            db = ledger.connect(path)
            try:
                ledger.import_file(db, export)
            finally:
                db.close()

    def describe_sources(self):
        result = []
        for source, label in SOURCE_LABELS.items():
            info = {"id": source, "label": label, "records": 0, "first": None, "last": None, "accounts": 0,
                    "files": [{"path": path, "status": self.status.get((source, path))} for path in self.files(source)]}
            reader = self.read_ledger(source)
            if reader:
                with reader as db:
                    row = db.execute("SELECT COUNT(*),MIN(time),MAX(time),COUNT(DISTINCT source_id) FROM events").fetchone()
                    info.update(records=row[0], first=row[1], last=row[2], accounts=row[3])
            result.append(info)
        return result


class _Closing:
    """`with` closes the connection, which sqlite3's own context manager does not do."""

    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *_):
        self.db.close()


def _source(value):
    if value not in SOURCE_LABELS:
        raise store.NotFound("Unknown data source")
    return value


ROUTES = []


def route(method, pattern):
    def register(handler):
        ROUTES.append((method, re.compile(f"^{pattern}$"), handler))
        return handler
    return register


@route("GET", "/api/tree")
def get_tree(app, body, query):
    with app.plan() as db:
        return {"series": store.tree(db)}


@route("POST", "/api/series")
def post_series(app, body, query):
    with app.plan() as db:
        return {"id": store.add_series(db, body.get("name"), body.get("format"))}


@route("PATCH", r"/api/series/(\d+)")
def patch_series(app, body, query, series_id):
    with app.plan() as db:
        store.update_series(db, int(series_id), body.get("name"))
    return {}


@route("DELETE", r"/api/series/(\d+)")
def del_series(app, body, query, series_id):
    with app.plan() as db:
        store.delete_series(db, int(series_id))
    return {}


@route("POST", r"/api/series/(\d+)/episodes")
def post_episode(app, body, query, series_id):
    with app.plan() as db:
        return {"id": store.add_episode(db, int(series_id), body.get("title"))}


@route("POST", r"/api/series/(\d+)/order")
def post_episode_order(app, body, query, series_id):
    with app.plan() as db:
        store.reorder_episodes(db, int(series_id), body.get("ids"))
    return {}


@route("GET", r"/api/episodes/(\d+)")
def get_episode(app, body, query, episode_id):
    with app.plan() as db:
        return store.get_episode(db, int(episode_id))


@route("PATCH", r"/api/episodes/(\d+)")
def patch_episode(app, body, query, episode_id):
    with app.plan() as db:
        store.update_episode(db, int(episode_id), body)
    return {}


@route("DELETE", r"/api/episodes/(\d+)")
def del_episode(app, body, query, episode_id):
    with app.plan() as db:
        store.delete_episode(db, int(episode_id))
    return {}


@route("POST", r"/api/episodes/(\d+)/shots")
def post_shot(app, body, query, episode_id):
    with app.plan() as db:
        return {"id": store.add_shot(db, int(episode_id))}


@route("POST", r"/api/episodes/(\d+)/shots/order")
def post_shot_order(app, body, query, episode_id):
    with app.plan() as db:
        store.reorder_shots(db, int(episode_id), body.get("ids"))
    return {}


@route("POST", r"/api/episodes/(\d+)/shots/rebuild")
def post_rebuild(app, body, query, episode_id):
    with app.plan() as db:
        return store.rebuild_shots(db, int(episode_id), dry_run=bool(body.get("dry_run")))


@route("PATCH", r"/api/shots/(\d+)")
def patch_shot(app, body, query, shot_id):
    with app.plan() as db:
        store.update_shot(db, int(shot_id), body)
    return {}


@route("DELETE", r"/api/shots/(\d+)")
def del_shot(app, body, query, shot_id):
    with app.plan() as db:
        store.delete_shot(db, int(shot_id))
    return {}


@route("GET", "/api/sources")
def get_sources(app, body, query):
    return {"sources": app.describe_sources()}


@route("POST", r"/api/sources/(\w+)/files")
def post_source_file(app, body, query, source):
    app.add_file(_source(source), body.get("path", ""))
    return {"sources": app.describe_sources()}


@route("POST", r"/api/sources/(\w+)/files/remove")
def post_source_file_remove(app, body, query, source):
    app.remove_file(_source(source), body.get("path", ""))
    return {"sources": app.describe_sources()}


@route("POST", r"/api/sources/(\w+)/import")
def post_source_import(app, body, query, source):
    _source(source)
    if source == "mock":
        app.regenerate_mock()
    else:
        for path in app.files(source):
            app.import_path(source, path)
    return {"sources": app.describe_sources()}


@route("GET", r"/api/data/(\w+)/windows")
def get_windows(app, body, query, source):
    reader = app.read_ledger(_source(source))
    if not reader:
        return {"windows": []}
    with reader as db:
        return {"windows": analytics.windows(db)}


@route("GET", r"/api/data/(\w+)/figures")
def get_figures(app, body, query, source):
    reader = app.read_ledger(_source(source))
    if not reader:
        return {"empty": True}
    window = query.get("window", ["all"])[0]
    chart_range = store._choice(query.get("range", ["to_date"])[0], store.RANGES, "Range")
    with reader as db:
        try:
            result = analytics.figures(db, window, chart_range)
        except analytics.UnknownWindow:
            if not db.execute("SELECT 1 FROM events LIMIT 1").fetchone():
                return {"empty": True}
            result = dict(analytics.figures(db, "all", chart_range), window_missing=window)
    app.icons.attach(result["auction"]["top"], source)
    return result


@route("GET", r"/api/data/(\w+)/item")
def get_item(app, body, query, source):
    """One item's analysis, and the items with activity in the window to choose from."""
    reader = app.read_ledger(_source(source))
    if not reader:
        return {"empty": True}
    window_id = query.get("window", ["all"])[0]
    name = query.get("name", [""])[0].strip()[:200] or None
    with reader as db:
        try:
            window = analytics.resolve_window(db, window_id)
        except analytics.UnknownWindow:
            if not db.execute("SELECT 1 FROM events LIMIT 1").fetchone():
                return {"empty": True}
            window = analytics.resolve_window(db, "all")
        result = analytics.item_figure(db, window, name)
    item = result["item"]
    if item:
        app.icons.attach([item, *(item["recipe"] or {}).get("reagents", [])], source)
    return result


@route("GET", r"/api/data/(\w+)/compare")
def get_compare(app, body, query, source):
    """Items side by side, and the items with activity in the window to choose from.
    Each `name` is one item. Without `chosen`, nothing has been picked yet and the best
    sellers are compared."""
    reader = app.read_ledger(_source(source))
    if not reader:
        return {"empty": True}
    window_id = query.get("window", ["all"])[0]
    names = None
    if "chosen" in query:
        names = [name.strip()[:200] for name in query.get("name", [])[:analytics.MAX_COMPARED_ITEMS * 2]]
    with reader as db:
        try:
            window = analytics.resolve_window(db, window_id)
        except analytics.UnknownWindow:
            if not db.execute("SELECT 1 FROM events LIMIT 1").fetchone():
                return {"empty": True}
            window = analytics.resolve_window(db, "all")
        result = analytics.compare_figure(db, window, names)
    app.icons.attach(result["items"], source)
    return result


@route("GET", r"/api/data/(\w+)/periods")
def get_periods(app, body, query, source):
    """One item in two windows side by side. The two `period` windows are those chosen;
    without both, the episode's `window` and the one before it are compared."""
    reader = app.read_ledger(_source(source))
    if not reader:
        return {"empty": True}
    window_id = query.get("window", ["all"])[0]
    chosen = list(dict.fromkeys(query.get("period", [])))[:2]
    name = query.get("name", [""])[0].strip()[:200] or None
    with reader as db:
        if not db.execute("SELECT 1 FROM events LIMIT 1").fetchone():
            return {"empty": True}
        periods = []
        for period in chosen:
            try:
                periods.append(analytics.resolve_window(db, period))
            except analytics.UnknownWindow:
                pass
        if len(periods) < 2:
            periods = analytics.default_periods(db, window_id)
        result = analytics.periods_figure(db, periods, name)
    app.icons.attach(result["items"], source)
    return result


def _item_id(query):
    try:
        item_id = int(query.get("id", [""])[0])
    except ValueError:
        raise store.Invalid("An item ID is a whole number") from None
    if not 0 < item_id < 10 ** 9:
        raise store.Invalid("An item ID is a whole number")
    return item_id


@route("GET", r"/api/visual/(\w+)/search")
def get_visual_search(app, body, query, source):
    """Items to show: this source's own items first, then anything Wowhead knows by those words."""
    words = query.get("q", [""])[0][:100]
    found = []
    reader = app.read_ledger(_source(source))
    if reader:
        with reader as db:
            found = [dict(item, in_ledger=True) for item in analytics.item_catalog(db, words)]
    if len(words.strip()) >= 2:
        known = {item["item_id"] for item in found}
        found += [dict(item, in_ledger=False) for item in app.tooltips.search(words, source)
                  if item["item_id"] not in known]
    return {"items": found, "online": app.tooltips.online}


@route("GET", r"/api/visual/(\w+)/top")
def get_visual_top(app, body, query, source):
    """The items with the most sales, profit and loss in the window, with their icons."""
    reader = app.read_ledger(_source(source))
    if not reader:
        return {"empty": True}
    window_id = query.get("window", ["all"])[0]
    with reader as db:
        try:
            window = analytics.resolve_window(db, window_id)
        except analytics.UnknownWindow:
            if not db.execute("SELECT 1 FROM events LIMIT 1").fetchone():
                return {"empty": True}
            window = analytics.resolve_window(db, "all")
        result = analytics.top_items(db, window)
    unique = {row["item_id"]: row for key in ("sales", "profit", "loss") for row in result[key]}
    app.icons.attach(list(unique.values()), source)
    return result


@route("GET", r"/api/visual/(\w+)/item")
def get_visual_item(app, body, query, source):
    """One item's icon and tooltip lines. Without a tooltip, only its name is known."""
    item_id = _item_id(query)
    tip = app.tooltips.item(item_id, _source(source))
    fallback = query.get("name", [""])[0].strip()[:200] or f"Item {item_id}"
    item = {"item_id": item_id, "name": (tip or {}).get("name") or fallback, "quality": (tip or {}).get("quality", 1),
            "lines": (tip or {}).get("lines") or [], "found": tip is not None,
            "icon_name": (tip or {}).get("icon_name")}
    app.icons.attach([item], source)
    return item


class QuietServer(ThreadingHTTPServer):
    """A browser closing a connection early is normal, not an error worth printing."""
    daemon_threads = True

    def handle_error(self, request, client_address):
        if not isinstance(sys.exc_info()[1], ConnectionError):
            super().handle_error(request, client_address)


def make_handler(app, port):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass

        def _send(self, status, payload, content_type="application/json; charset=utf-8"):
            data = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def _trusted(self, method):
            # Other websites must not reach this server through the browser: the Host check
            # stops DNS rebinding, and requiring JSON forces a preflight this server never grants.
            if self.headers.get("Host") not in allowed_hosts:
                return False
            if method == "GET":
                return True
            origin = self.headers.get("Origin")
            if origin and urlsplit(origin).netloc not in allowed_hosts:
                return False
            return (self.headers.get("Content-Type") or "").startswith("application/json")

        def _handle(self, method):
            url = urlsplit(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            if not self._trusted(method):
                return self._send(403, {"error": "Request refused"})
            if method == "GET" and url.path in STATIC:
                name, content_type = STATIC[url.path]
                return self._send(200, (HERE / "static" / name).read_bytes(), content_type)
            for route_method, pattern, handler in ROUTES:
                match = pattern.match(url.path)
                if match and route_method == method:
                    try:
                        body = json.loads(raw or b"{}")
                        if not isinstance(body, dict):
                            raise store.Invalid("Expected a JSON object")
                        return self._send(200, handler(app, body, parse_qs(url.query), *match.groups()))
                    except store.NotFound as err:
                        return self._send(404, {"error": str(err)})
                    except (store.Invalid, json.JSONDecodeError) as err:
                        return self._send(400, {"error": str(err)})
                    except sqlite3.Error as err:
                        return self._send(500, {"error": f"Database error: {err}"})
            self._send(404, {"error": "Not found"})

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def do_PATCH(self):
            self._handle("PATCH")

        def do_DELETE(self):
            self._handle("DELETE")

    return Handler


def watch(app, interval=5):
    while True:
        try:
            app.import_changed()
        except Exception as err:  # A background import must never stop the website.
            print(f"Import check failed: {err}", file=sys.stderr)
        time.sleep(interval)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data", default=str(HERE / "data"), help="Folder for the studio's own databases")
    parser.add_argument("--wow-root", action="append", help="World of Warcraft folder, if not in a usual place")
    parser.add_argument("--pugger-icons", default=str(DEFAULT_PUGGER_ICONS), help="Pugger's public/icons folder")
    parser.add_argument("--offline", action="store_true", help="Never look up item icons on Wowhead")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    roots = (args.wow_root or []) + list(DEFAULT_WOW_ROOTS) if args.wow_root else None
    app = Studio(args.data, roots, pugger_icons=args.pugger_icons, online=not args.offline)
    server = QuietServer(("127.0.0.1", args.port), make_handler(app, args.port))
    threading.Thread(target=watch, args=(app,), daemon=True).start()
    url = f"http://127.0.0.1:{args.port}"
    print(f"Forever Ledger Studio: {url}  (Ctrl+C to stop)")
    if not args.no_browser and not os.environ.get("CI"):
        threading.Timer(0.5, webbrowser.open, (url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
