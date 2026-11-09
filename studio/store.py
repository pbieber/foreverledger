"""Episode planning storage: series, episodes and shots. Stdlib only."""
from __future__ import annotations

import difflib
import json
import re
import sqlite3
import time
from pathlib import Path

FORMATS = ("short", "long")
STATUSES = ("idea", "scripting", "recording", "editing", "published")
SOURCES = ("forever", "tbc", "mock")
CHARTS = ("", "start", "auction", "value", "costs", "revenue", "item", "compare")
ITEM_VIEWS = ("one", "compare")
VALUE_PARTS = ("total", "gold", "assets", "equipped")
MAX_COMPARED = 6
RANGES = ("window", "to_date")
AXIS_MODES = ("zero", "fit", "custom")


class NotFound(Exception):
    pass


class Invalid(Exception):
    pass


def connect(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS series (
      id INTEGER PRIMARY KEY, name TEXT NOT NULL, format TEXT NOT NULL, position INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS episodes (
      id INTEGER PRIMARY KEY, series_id INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
      title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'idea', position INTEGER NOT NULL,
      script TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'forever',
      window TEXT NOT NULL DEFAULT 'all', range TEXT NOT NULL DEFAULT 'to_date',
      created_at INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS shots (
      id INTEGER PRIMARY KEY, episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
      position INTEGER NOT NULL, voiceover TEXT NOT NULL DEFAULT '', visual TEXT NOT NULL DEFAULT '',
      chart TEXT NOT NULL DEFAULT '', done INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS files (
      source TEXT NOT NULL, path TEXT NOT NULL, removed INTEGER NOT NULL DEFAULT 0,
      PRIMARY KEY(source, path));
    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """)
    columns = {row["name"] for row in db.execute("PRAGMA table_info(episodes)")}
    if "chart_settings" not in columns:
        with db:
            db.execute("ALTER TABLE episodes ADD COLUMN chart_settings TEXT NOT NULL DEFAULT '{}'")
    if "visuals" not in columns:
        with db:
            db.execute("ALTER TABLE episodes ADD COLUMN visuals TEXT NOT NULL DEFAULT '[]'")
    return db


def _next_position(db, table, column, value):
    row = db.execute(f"SELECT COALESCE(MAX(position),-1)+1 FROM {table} WHERE {column}=?", (value,)).fetchone()
    return row[0]


def _text(value, field, *, allow_empty=False):
    if not isinstance(value, str):
        raise Invalid(f"{field} must be text")
    value = value.strip() if not allow_empty else value
    if not value and not allow_empty:
        raise Invalid(f"{field} cannot be empty")
    return value


def _choice(value, choices, field):
    if value not in choices:
        raise Invalid(f"{field} must be one of: {', '.join(c or 'none' for c in choices)}")
    return value


def _chart_settings(value):
    """Per chart: where its vertical axis starts, how long its animation runs, for the
    value chart whether it shows the total or one part, for the
    item chart which item it shows and whether it compares items instead, and for the
    comparison which items, in order."""
    if not isinstance(value, dict) or not set(value) <= set(CHARTS) - {""}:
        raise Invalid("Chart settings are not valid")
    clean = {}
    for chart, settings in value.items():
        if not isinstance(settings, dict):
            raise Invalid("Chart settings are not valid")
        entry = {"mode": _choice(settings.get("mode", "zero"), AXIS_MODES, "Axis start")}
        gold = settings.get("gold", 0)
        if isinstance(gold, bool) or not isinstance(gold, (int, float)) or not 0 <= gold < 1e12:
            raise Invalid("Axis start must be a positive number of gold")
        entry["gold"] = gold
        seconds = settings.get("seconds", 3)
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 0.5 <= seconds <= 60:
            raise Invalid("Animation length must be between 0.5 and 60 seconds")
        entry["seconds"] = seconds
        if chart in ("costs", "revenue"):
            # All characters together, or the chosen ones (none chosen means all) each in its colour.
            split, chosen = settings.get("split", False), settings.get("characters", [])
            if not isinstance(split, bool):
                raise Invalid("The character split is not valid")
            if (not isinstance(chosen, list) or len(chosen) > 200
                    or not all(isinstance(c, str) and 0 < len(c) <= 100 for c in chosen)):
                raise Invalid("The chosen characters are not valid")
            entry["split"], entry["characters"] = split, list(dict.fromkeys(chosen))
        if chart == "item" and "name" in settings:
            name = settings["name"]
            if not isinstance(name, str) or len(name) > 200:
                raise Invalid("The item name is not valid")
            entry["name"] = name
        if chart == "value" and "show" in settings:
            # The total, or one of the parts it adds up on its own.
            entry["show"] = _choice(settings["show"], VALUE_PARTS, "Value chart")
        if chart == "item" and "view" in settings:
            # The item section shows one item, or several side by side.
            entry["view"] = _choice(settings["view"], ITEM_VIEWS, "Item view")
        if chart == "compare" and "names" in settings:
            names = settings["names"]
            if (not isinstance(names, list) or len(names) > MAX_COMPARED
                    or not all(isinstance(n, str) and 0 < len(n) <= 200 for n in names)):
                raise Invalid("The items to compare are not valid")
            entry["names"] = list(dict.fromkeys(names))
        clean[chart] = entry
    return json.dumps(clean)


MAX_VISUALS = 100
PLACES = ("right", "below")
MAX_COPPER = 10 ** 15


def _visuals(value):
    """Item cards for the video: an item, a gold amount that can be a gain or a loss, and
    which optional tooltip lines it shows. A card with item ID None is the amount alone."""
    if not isinstance(value, list) or len(value) > MAX_VISUALS:
        raise Invalid(f"Visuals must be a list of at most {MAX_VISUALS}")
    clean = []
    for visual in value:
        if not isinstance(visual, dict):
            raise Invalid("A visual is not valid")
        key, item_id, name = visual.get("key"), visual.get("item_id"), visual.get("name")
        copper = visual.get("copper", 0)
        if not isinstance(key, str) or not 0 < len(key) <= 40:
            raise Invalid("A visual needs a key")
        if item_id is not None and (isinstance(item_id, bool) or not isinstance(item_id, int) or not 0 < item_id < 10 ** 9):
            raise Invalid("A visual needs an item ID")
        if not isinstance(name, str) or len(name) > 200:
            raise Invalid("The item name is not valid")
        if isinstance(copper, bool) or not isinstance(copper, int) or abs(copper) >= MAX_COPPER:
            raise Invalid("The gold amount is not valid")
        entry = {"key": key, "item_id": item_id, "name": name, "copper": copper,
                 "place": _choice(visual.get("place", "right"), PLACES, "Where the amount goes")}
        for flag in ("sell", "ilvl"):
            shown = visual.get(flag, True)
            if not isinstance(shown, bool):
                raise Invalid("A tooltip line choice is not valid")
            entry[flag] = shown
        clean.append(entry)
    if len({v["key"] for v in clean}) != len(clean):
        raise Invalid("Each visual needs its own key")
    return json.dumps(clean)


def tree(db):
    """Sidebar contents: every series with its episodes, in order."""
    episodes = {}
    for row in db.execute("SELECT id,series_id,title,status,position FROM episodes ORDER BY position,id"):
        episodes.setdefault(row["series_id"], []).append(dict(row))
    return [dict(s, episodes=episodes.get(s["id"], []))
            for s in db.execute("SELECT * FROM series ORDER BY position,id")]


def add_series(db, name, fmt):
    name, fmt = _text(name, "Name"), _choice(fmt, FORMATS, "Format")
    with db:
        cur = db.execute("INSERT INTO series(name,format,position) VALUES(?,?,?)",
                         (name, fmt, _next_position(db, "series", "format", fmt)))
    return cur.lastrowid


def update_series(db, series_id, name):
    with db:
        cur = db.execute("UPDATE series SET name=? WHERE id=?", (_text(name, "Name"), series_id))
    if not cur.rowcount:
        raise NotFound("Series not found")


def delete_series(db, series_id):
    with db:
        cur = db.execute("DELETE FROM series WHERE id=?", (series_id,))
    if not cur.rowcount:
        raise NotFound("Series not found")


def add_episode(db, series_id, title=None, source="forever"):
    series = db.execute("SELECT id FROM series WHERE id=?", (series_id,)).fetchone()
    if not series:
        raise NotFound("Series not found")
    position = _next_position(db, "episodes", "series_id", series_id)
    title = _text(title, "Title") if title is not None else f"Episode {position + 1}"
    with db:
        cur = db.execute(
            "INSERT INTO episodes(series_id,title,position,source,created_at) VALUES(?,?,?,?,?)",
            (series_id, title, position, _choice(source, SOURCES, "Source"), int(time.time())))
    return cur.lastrowid


def get_episode(db, episode_id):
    row = db.execute("""SELECT e.*, s.name AS series_name, s.format AS format
        FROM episodes e JOIN series s ON s.id=e.series_id WHERE e.id=?""", (episode_id,)).fetchone()
    if not row:
        raise NotFound("Episode not found")
    shots = db.execute("SELECT * FROM shots WHERE episode_id=? ORDER BY position,id", (episode_id,)).fetchall()
    return dict(row, chart_settings=json.loads(row["chart_settings"]), visuals=json.loads(row["visuals"]),
                shots=[dict(s, done=bool(s["done"])) for s in shots])


def update_episode(db, episode_id, fields):
    cleaners = {
        "title": lambda v: _text(v, "Title"),
        "status": lambda v: _choice(v, STATUSES, "Status"),
        "script": lambda v: _text(v, "Script", allow_empty=True),
        "source": lambda v: _choice(v, SOURCES, "Source"),
        "window": lambda v: _text(v, "Window"),
        "range": lambda v: _choice(v, RANGES, "Range"),
        "chart_settings": _chart_settings,
        "visuals": _visuals,
    }
    unknown = set(fields) - set(cleaners)
    if unknown:
        raise Invalid(f"Unknown fields: {', '.join(sorted(unknown))}")
    values = {key: cleaners[key](value) for key, value in fields.items()}
    # Windows belong to one source, so a new source starts from its whole history.
    if "source" in values and "window" not in values:
        values["window"] = "all"
    if values:
        assignments = ",".join(f'"{key}"=?' for key in values)
        with db:
            cur = db.execute(f"UPDATE episodes SET {assignments} WHERE id=?", (*values.values(), episode_id))
        if not cur.rowcount:
            raise NotFound("Episode not found")


def delete_episode(db, episode_id):
    with db:
        cur = db.execute("DELETE FROM episodes WHERE id=?", (episode_id,))
    if not cur.rowcount:
        raise NotFound("Episode not found")


def reorder_episodes(db, series_id, ids):
    """Set a series' full order. Episodes dragged in from another series move here."""
    if not db.execute("SELECT 1 FROM series WHERE id=?", (series_id,)).fetchone():
        raise NotFound("Series not found")
    if not isinstance(ids, list) or len(set(ids)) != len(ids):
        raise Invalid("Order must list each episode once")
    current = {r[0] for r in db.execute("SELECT id FROM episodes WHERE series_id=?", (series_id,))}
    if not current <= set(ids):
        raise Invalid("Order is missing episodes; reload and try again")
    found = {r[0] for r in db.execute(
        f"SELECT id FROM episodes WHERE id IN ({','.join('?' * len(ids))})", ids)} if ids else set()
    if found != set(ids):
        raise NotFound("Episode not found")
    with db:
        for position, episode_id in enumerate(ids):
            db.execute("UPDATE episodes SET series_id=?, position=? WHERE id=?", (series_id, position, episode_id))


def add_shot(db, episode_id, voiceover="", visual="", chart=""):
    if not db.execute("SELECT 1 FROM episodes WHERE id=?", (episode_id,)).fetchone():
        raise NotFound("Episode not found")
    with db:
        cur = db.execute(
            "INSERT INTO shots(episode_id,position,voiceover,visual,chart) VALUES(?,?,?,?,?)",
            (episode_id, _next_position(db, "shots", "episode_id", episode_id),
             _text(voiceover, "Voiceover", allow_empty=True), _text(visual, "Visual", allow_empty=True),
             _choice(chart, CHARTS, "Chart")))
    return cur.lastrowid


def update_shot(db, shot_id, fields):
    cleaners = {
        "voiceover": lambda v: _text(v, "Voiceover", allow_empty=True),
        "visual": lambda v: _text(v, "Visual", allow_empty=True),
        "chart": lambda v: _choice(v, CHARTS, "Chart"),
        "done": lambda v: 1 if v else 0,
    }
    unknown = set(fields) - set(cleaners)
    if unknown:
        raise Invalid(f"Unknown fields: {', '.join(sorted(unknown))}")
    values = {key: cleaners[key](value) for key, value in fields.items()}
    if values:
        assignments = ",".join(f"{key}=?" for key in values)
        with db:
            cur = db.execute(f"UPDATE shots SET {assignments} WHERE id=?", (*values.values(), shot_id))
        if not cur.rowcount:
            raise NotFound("Shot not found")


def delete_shot(db, shot_id):
    with db:
        cur = db.execute("DELETE FROM shots WHERE id=?", (shot_id,))
    if not cur.rowcount:
        raise NotFound("Shot not found")


def reorder_shots(db, episode_id, ids):
    current = {r[0] for r in db.execute("SELECT id FROM shots WHERE episode_id=?", (episode_id,))}
    if not isinstance(ids, list) or len(ids) != len(current) or set(ids) != current:
        raise Invalid("Order must list every shot once; reload and try again")
    with db:
        for position, shot_id in enumerate(ids):
            db.execute("UPDATE shots SET position=? WHERE id=?", (position, shot_id))


def split_script(script):
    """One shot per spoken sentence; a line break also ends a line."""
    lines = []
    for block in script.splitlines():
        lines.extend(part.strip() for part in re.split(r"(?<=[.!?])\s+", block) if part.strip())
    return lines


def _normalized(text):
    return re.sub(r"\W+", " ", text).strip().casefold()


def plan_from_script(script, shots):
    """Match script lines to existing shots so an edited line keeps its visual.

    Returns (rows, dropped): one row per script line, reusing the best existing
    shot of at least 60% similarity, plus the planned shots no line claimed.
    """
    lines = split_script(script)
    available = list(shots)
    matches = {}
    candidates = sorted(
        ((difflib.SequenceMatcher(None, _normalized(line), _normalized(shot["voiceover"])).ratio(), i, shot["id"])
         for i, line in enumerate(lines) for shot in available),
        key=lambda c: (-c[0], c[1], c[2]))
    used = set()
    by_id = {shot["id"]: shot for shot in available}
    for ratio, index, shot_id in candidates:
        if ratio >= 0.6 and index not in matches and shot_id not in used:
            matches[index] = by_id[shot_id]
            used.add(shot_id)
    rows = []
    for index, line in enumerate(lines):
        shot = matches.get(index)
        rows.append({"voiceover": line, "visual": shot["visual"] if shot else "",
                     "chart": shot["chart"] if shot else "", "done": shot["done"] if shot else False})
    dropped = [s for s in available if s["id"] not in used and (s["visual"].strip() or s["chart"])]
    return rows, dropped


def rebuild_shots(db, episode_id, *, dry_run=False):
    episode = get_episode(db, episode_id)
    rows, dropped = plan_from_script(episode["script"], episode["shots"])
    if not dry_run:
        with db:
            db.execute("DELETE FROM shots WHERE episode_id=?", (episode_id,))
            for position, row in enumerate(rows):
                db.execute(
                    "INSERT INTO shots(episode_id,position,voiceover,visual,chart,done) VALUES(?,?,?,?,?,?)",
                    (episode_id, position, row["voiceover"], row["visual"], row["chart"], 1 if row["done"] else 0))
    return {"lines": len(rows), "dropped": [s["voiceover"] or s["visual"] for s in dropped]}


INTRO_SHOTS = [
    ("I made [X] gold in TBC Anniversary. How much can I make in Forever, from 1 to 60?",
     "Gold total already filling the frame, then pan up to the Forever character.", ""),
    ("It paid for raiding on multiple characters, and a few small indulgences.",
     "Scarab Lord title with a large caption, cut in exactly on \"small indulgences\". Hold about a second.", ""),
    ("I also got stuck with bags full of worthless [material].", "Full bags of the worthless material.", ""),
    ("But I still came out ahead.", "Slow zoom on the TSM gold graph.", ""),
    ("The rules: reach 60 as fast as possible, with enough gold to buy what I need and still invest.",
     "Level-up, then the slow mount. Without Forever footage yet: new character with \"60 ASAP\" on screen.", ""),
    ("A fresh economy is a great place to start, and I'll show you how to set yourself up, no gold buying needed.",
     "Total value graph growing, labelled TBC. Stamp over a mock \"WTS gold\" whisper on \"no gold buying needed\".",
     "value"),
    ("Daily updates start now. Follow to see how Day 1 went.", "Gold counter ticking up from 0 in the bag.", ""),
]


def seed(db):
    """First run only: the series as planned so far, with the agreed intro draft."""
    if db.execute("SELECT 1 FROM meta WHERE key='seeded'").fetchone():
        return
    series_id = add_series(db, "Forever 1 to 60", "short")
    intro = add_episode(db, series_id, "Intro: from TBC to Forever", source="tbc")
    update_episode(db, intro, {"status": "scripting", "script": " ".join(line for line, _, _ in INTRO_SHOTS)})
    for voiceover, visual, chart in INTRO_SHOTS:
        add_shot(db, intro, voiceover, visual, chart)
    add_episode(db, series_id, "Day 1")
    long_id = add_series(db, "Forever 1 to 60: the full breakdown", "long")
    add_episode(db, long_id, "How I made gold from 1 to 60")
    with db:
        db.execute("INSERT INTO meta VALUES('seeded','1')")
