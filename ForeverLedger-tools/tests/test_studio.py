"""Studio tests: episode storage, keeping data sources apart, and chart arithmetic."""
import base64
import http.client
import json
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "studio"))
sys.path.insert(0, str(ROOT / "ForeverLedger-tools"))

import analytics  # noqa: E402
import icons  # noqa: E402
import ledger  # noqa: E402
import mockdata  # noqa: E402
import store  # noqa: E402
import studio  # noqa: E402
import tooltips  # noqa: E402

SOURCE = "Test:1:1"
GUID, BANK_GUID = "Player-1", "Player-2"


class Events:
    """Builds a ledger database from a compact list of events."""

    def __init__(self):
        self.events = []

    def add(self, kind, data, at, character=(GUID, "Main-Realm"), source=SOURCE):
        sequence = sum(1 for e in self.events if e["sourceID"] == source) + 1
        self.events.append({"schema": 1, "sourceID": source, "sequence": sequence, "id": f"{source}:{sequence}",
                            "character": character[0], "characterName": character[1], "realm": "Realm",
                            "time": at, "kind": kind, "data": data})
        return f"{source}:{sequence}"

    def balance(self, before, after, at, **kw):
        return self.add("balance", {"before": before, "after": after, "delta": after - before}, at, **kw)

    def activity(self, category, amount, at, **details):
        character = details.pop("character", (GUID, "Main-Realm"))
        return self.add("activity", {"category": category, "amount": amount, **details}, at, character=character)

    def database(self, folder):
        db = ledger.connect(Path(folder) / "ledger.sqlite")
        for source in sorted({e["sourceID"] for e in self.events}):
            path = Path(folder) / f"export-{abs(hash(source))}.json"
            events = [e for e in self.events if e["sourceID"] == source]
            path.write_text(json.dumps({"schema": 1, "sourceID": source, "events": events}), encoding="utf-8")
            ledger.import_file(db, path)
        return db


class StudioTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)


class StoreTests(StudioTestCase):
    def setUp(self):
        super().setUp()
        self.db = store.connect(self.folder / "plan.sqlite")
        self.addCleanup(self.db.close)
        self.series = store.add_series(self.db, "Series", "short")

    def test_series_need_a_known_format_and_a_name(self):
        with self.assertRaises(store.Invalid):
            store.add_series(self.db, "Series", "medium")
        with self.assertRaises(store.Invalid):
            store.add_series(self.db, "   ", "short")

    def test_new_episodes_get_a_title_that_can_be_changed(self):
        first = store.add_episode(self.db, self.series)
        self.assertEqual(store.get_episode(self.db, first)["title"], "Episode 1")
        store.update_episode(self.db, first, {"title": "Launch day"})
        self.assertEqual(store.get_episode(self.db, first)["title"], "Launch day")

    def test_reordering_is_kept(self):
        ids = [store.add_episode(self.db, self.series) for _ in range(3)]
        store.reorder_episodes(self.db, self.series, [ids[2], ids[0], ids[1]])
        order = [e["id"] for e in store.tree(self.db)[0]["episodes"]]
        self.assertEqual(order, [ids[2], ids[0], ids[1]])

    def test_an_episode_can_be_dragged_to_another_series(self):
        moved = store.add_episode(self.db, self.series)
        other = store.add_series(self.db, "Other", "long")
        store.reorder_episodes(self.db, other, [moved])
        tree = {s["id"]: s for s in store.tree(self.db)}
        self.assertEqual(tree[self.series]["episodes"], [])
        self.assertEqual([e["id"] for e in tree[other]["episodes"]], [moved])

    def test_a_stale_order_cannot_lose_an_episode(self):
        ids = [store.add_episode(self.db, self.series) for _ in range(2)]
        with self.assertRaises(store.Invalid):
            store.reorder_episodes(self.db, self.series, [ids[0]])

    def test_deleting_a_series_deletes_its_episodes_and_shots(self):
        episode = store.add_episode(self.db, self.series)
        store.add_shot(self.db, episode)
        store.delete_series(self.db, self.series)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM episodes").fetchone()[0], 0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM shots").fetchone()[0], 0)

    def test_shots_reorder(self):
        episode = store.add_episode(self.db, self.series)
        a, b = store.add_shot(self.db, episode, "a"), store.add_shot(self.db, episode, "b")
        store.reorder_shots(self.db, episode, [b, a])
        self.assertEqual([s["voiceover"] for s in store.get_episode(self.db, episode)["shots"]], ["b", "a"])

    def test_script_splits_into_one_line_per_sentence(self):
        self.assertEqual(store.split_script("One here. Two? Three!\nFour line"),
                         ["One here.", "Two?", "Three!", "Four line"])

    def test_rebuilding_keeps_visuals_of_edited_lines_and_reports_dropped_ones(self):
        episode = store.add_episode(self.db, self.series)
        kept = store.add_shot(self.db, episode, "I made a lot of gold in TBC.", "Gold shot", "value")
        store.add_shot(self.db, episode, "This line gets removed entirely now.", "Removed shot")
        store.update_shot(self.db, kept, {"done": True})
        store.update_episode(self.db, episode, {"script": "I made so much gold in TBC. A brand new line appears."})
        preview = store.rebuild_shots(self.db, episode, dry_run=True)
        self.assertEqual(preview["dropped"], ["This line gets removed entirely now."])
        self.assertEqual(len(store.get_episode(self.db, episode)["shots"]), 2, "dry run changes nothing")
        store.rebuild_shots(self.db, episode)
        first, second = store.get_episode(self.db, episode)["shots"]
        self.assertEqual((first["visual"], first["chart"], first["done"]), ("Gold shot", "value", True))
        self.assertEqual((second["voiceover"], second["visual"]), ("A brand new line appears.", ""))

    def test_changing_source_resets_the_window(self):
        episode = store.add_episode(self.db, self.series)
        store.update_episode(self.db, episode, {"window": "marker:Day 1"})
        store.update_episode(self.db, episode, {"source": "tbc"})
        self.assertEqual(store.get_episode(self.db, episode)["window"], "all")

    def test_seed_runs_once_and_survives_deleting_everything(self):
        store.seed(self.db)
        titles = [e["title"] for s in store.tree(self.db) for e in s["episodes"]]
        self.assertIn("Intro: from TBC to Forever", titles)
        for series in store.tree(self.db):
            store.delete_series(self.db, series["id"])
        store.seed(self.db)
        self.assertEqual(store.tree(self.db), [])


class ChartSettingsTests(StudioTestCase):
    def setUp(self):
        super().setUp()
        self.db = store.connect(self.folder / "plan.sqlite")
        self.addCleanup(self.db.close)
        self.episode = store.add_episode(self.db, store.add_series(self.db, "Series", "short"))

    def test_settings_are_kept_per_chart(self):
        settings = {"start": {"mode": "custom", "gold": 110000, "seconds": 5}, "value": {"mode": "fit"}}
        store.update_episode(self.db, self.episode, {"chart_settings": settings})
        saved = store.get_episode(self.db, self.episode)["chart_settings"]
        self.assertEqual(saved["start"], {"mode": "custom", "gold": 110000, "seconds": 5})
        self.assertEqual(saved["value"], {"mode": "fit", "gold": 0, "seconds": 3})

    def test_the_item_chart_keeps_its_item(self):
        store.update_episode(self.db, self.episode, {"chart_settings": {"item": {"name": "Linen Bag", "seconds": 5}}})
        saved = store.get_episode(self.db, self.episode)["chart_settings"]
        self.assertEqual(saved["item"], {"mode": "zero", "gold": 0, "seconds": 5, "name": "Linen Bag"})
        for bad in ({"item": {"name": 5}}, {"item": {"name": "x" * 201}}):
            with self.assertRaises(store.Invalid, msg=bad):
                store.update_episode(self.db, self.episode, {"chart_settings": bad})

    def test_the_value_chart_keeps_which_part_it_shows(self):
        store.update_episode(self.db, self.episode, {"chart_settings": {"value": {"show": "gold"}}})
        saved = store.get_episode(self.db, self.episode)["chart_settings"]
        self.assertEqual(saved["value"], {"mode": "zero", "gold": 0, "seconds": 3, "show": "gold"})
        for bad in ({"value": {"show": "silver"}}, {"value": {"show": 1}}):
            with self.assertRaises(store.Invalid, msg=bad):
                store.update_episode(self.db, self.episode, {"chart_settings": bad})

    def test_the_revenue_chart_keeps_its_own_character_split(self):
        settings = {"revenue": {"split": True, "characters": ["Player-2"]}, "costs": {"split": False}}
        store.update_episode(self.db, self.episode, {"chart_settings": settings})
        saved = store.get_episode(self.db, self.episode)["chart_settings"]
        self.assertEqual((saved["revenue"]["split"], saved["revenue"]["characters"]), (True, ["Player-2"]))
        self.assertFalse(saved["costs"]["split"])

    def test_the_cost_chart_keeps_its_character_split(self):
        chosen = {"costs": {"split": True, "characters": ["Player-1", "Player-2", "Player-1"]}}
        store.update_episode(self.db, self.episode, {"chart_settings": chosen})
        saved = store.get_episode(self.db, self.episode)["chart_settings"]["costs"]
        self.assertEqual((saved["split"], saved["characters"]), (True, ["Player-1", "Player-2"]))
        store.update_episode(self.db, self.episode, {"chart_settings": {"costs": {"seconds": 5}}})
        saved = store.get_episode(self.db, self.episode)["chart_settings"]["costs"]
        self.assertEqual((saved["split"], saved["characters"]), (False, []))
        for bad in ({"split": "yes"}, {"characters": "Player-1"}, {"characters": [""]}, {"characters": [7]}):
            with self.assertRaises(store.Invalid, msg=bad):
                store.update_episode(self.db, self.episode, {"chart_settings": {"costs": bad}})

    def test_a_new_episode_has_no_settings(self):
        self.assertEqual(store.get_episode(self.db, self.episode)["chart_settings"], {})

    def test_bad_settings_are_refused(self):
        for bad in ({"nope": {}}, {"start": {"mode": "nope"}}, {"start": {"gold": -1}}, {"start": {"gold": "x"}},
                    {"start": {"seconds": 0}}, {"start": "zero"}, []):
            with self.assertRaises(store.Invalid, msg=bad):
                store.update_episode(self.db, self.episode, {"chart_settings": bad})

    def test_a_database_from_before_settings_is_upgraded_and_keeps_its_episodes(self):
        path = self.folder / "old.sqlite"
        old = sqlite3.connect(path)
        old.executescript("""
            CREATE TABLE series (id INTEGER PRIMARY KEY, name TEXT NOT NULL, format TEXT NOT NULL, position INTEGER NOT NULL);
            CREATE TABLE episodes (
              id INTEGER PRIMARY KEY, series_id INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
              title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'idea', position INTEGER NOT NULL,
              script TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'forever',
              window TEXT NOT NULL DEFAULT 'all', range TEXT NOT NULL DEFAULT 'to_date',
              created_at INTEGER NOT NULL);
            INSERT INTO series VALUES (1, 'Old', 'short', 0);
            INSERT INTO episodes(id, series_id, title, position, created_at) VALUES (7, 1, 'Keep me', 0, 1);
        """)
        old.close()
        upgraded = store.connect(path)
        self.addCleanup(upgraded.close)
        loaded = store.get_episode(upgraded, 7)
        self.assertEqual((loaded["title"], loaded["chart_settings"]), ("Keep me", {}))


class VisualsStoreTests(StudioTestCase):
    def setUp(self):
        super().setUp()
        self.db = store.connect(self.folder / "plan.sqlite")
        self.addCleanup(self.db.close)
        self.episode = store.add_episode(self.db, store.add_series(self.db, "Series", "short"))

    def test_cards_keep_their_item_signed_amount_and_choices(self):
        cards = [{"key": "a", "item_id": 2589, "name": "Linen Cloth", "copper": -120000},
                 {"key": "b", "item_id": 19019, "name": "Thunderfury", "copper": 15000000, "place": "below", "sell": False}]
        store.update_episode(self.db, self.episode, {"visuals": cards})
        saved = store.get_episode(self.db, self.episode)["visuals"]
        self.assertEqual(saved[0], {"key": "a", "item_id": 2589, "name": "Linen Cloth", "copper": -120000,
                                    "place": "right", "sell": True, "ilvl": True})
        self.assertEqual((saved[1]["place"], saved[1]["sell"], saved[1]["copper"]), ("below", False, 15000000))

    def test_a_card_without_an_item_is_the_gold_amount_alone(self):
        store.update_episode(self.db, self.episode, {"visuals": [{"key": "g", "item_id": None, "name": "", "copper": 52000}]})
        saved = store.get_episode(self.db, self.episode)["visuals"][0]
        self.assertEqual((saved["item_id"], saved["name"], saved["copper"]), (None, "", 52000))

    def test_a_new_episode_has_no_cards(self):
        self.assertEqual(store.get_episode(self.db, self.episode)["visuals"], [])

    def test_bad_cards_are_refused(self):
        good = {"key": "a", "item_id": 1, "name": "x", "copper": 5}
        for bad in ({}, [dict(good, item_id=0)], [dict(good, item_id=True)], [dict(good, item_id="1")], [dict(good, copper=1.5)],
                    [dict(good, copper=10 ** 15)], [dict(good, key="")], [dict(good, place="left")],
                    [dict(good, sell="no")], [good, good], [good] * 101, ["card"]):
            with self.assertRaises(store.Invalid, msg=bad):
                store.update_episode(self.db, self.episode, {"visuals": bad})


THUNDERFURY = ('<table><tr><td><!--nstart--><b class="q5">Thunderfury</b><!--nend--><span class="q"><br>Item Level '
               '<!--ilvl-->80</span><br>Binds when picked up<table width="100%"><tr><td>One-Hand</td><th>'
               '<span class="q1">Sword</span></th></tr></table><span class="q2">Chance on hit: <a href="/x" '
               'class="q2">Blasts&nbsp;your enemy.</a></span><script>alert(1)</script><br><div class="whtt-sellprice">'
               'Sell Price: <span class="moneygold">25</span> <span class="moneysilver">53</span></div></td></tr></table>')


class TooltipTests(StudioTestCase):
    def setUp(self):
        super().setUp()
        self.requests = []
        self.replies = {}

    def fetch(self, url):
        self.requests.append(url)
        for fragment, reply in self.replies.items():
            if fragment in url:
                return reply
        raise OSError("unexpected request")

    def tips(self, **options):
        return tooltips.TooltipStore(self.folder / "tips", fetch=self.fetch, **options)

    def test_tooltip_html_becomes_coloured_lines_with_a_right_column_and_coins(self):
        lines = tooltips.parse_tooltip(THUNDERFURY)
        text = lambda spans: "".join(s["text"] for s in spans)
        self.assertEqual([text(line["left"]) for line in lines],
                         ["Thunderfury", "Item Level 80", "Binds when picked up", "One-Hand",
                          "Chance on hit: Blasts your enemy.", "Sell Price: 25 53"])
        self.assertEqual(lines[0]["left"][0]["color"], "q5")
        self.assertEqual(lines[1]["left"][0]["color"], "q")
        self.assertEqual(lines[3]["right"], [{"text": "Sword", "color": "q1"}])
        self.assertEqual(lines[4]["left"][0]["color"], "q2")
        self.assertTrue(lines[5]["sell"])
        self.assertEqual([s.get("coin") for s in lines[5]["left"] if s.get("coin")], ["gold", "silver"])
        self.assertFalse(any(line["sell"] for line in lines[:5]))

    def test_tooltips_are_fetched_from_the_sources_section_once(self):
        self.replies["forever/tooltip/item/19019"] = json.dumps(
            {"name": "Thunderfury", "quality": 5, "icon": "inv_sword_39", "tooltip": THUNDERFURY}).encode()
        tip = self.tips().item(19019, "mock")
        self.assertEqual((tip["name"], tip["quality"], tip["icon_name"]), ("Thunderfury", 5, "inv_sword_39"))
        self.assertEqual(self.tips().item(19019, "mock")["lines"], tip["lines"])
        self.assertEqual(len(self.requests), 1)

    def test_no_network_gives_nothing_and_stops_trying_for_a_while(self):
        store_ = self.tips()
        self.assertIsNone(store_.item(1, "tbc"))
        self.assertIsNone(store_.item(2, "tbc"))
        self.assertEqual(store_.search("linen", "tbc"), [])
        self.assertEqual(len(self.requests), 1)

    def test_a_garbled_reply_counts_as_not_found_for_a_while(self):
        self.replies["tooltip"] = b"not json"
        store_ = self.tips()
        self.assertIsNone(store_.item(1, "tbc"))
        self.assertIsNone(store_.item(1, "tbc"))
        self.assertEqual(len(self.requests), 1)

    def test_offline_never_makes_a_request(self):
        store_ = self.tips(online=False)
        self.assertIsNone(store_.item(1, "tbc"))
        self.assertEqual(store_.search("linen", "tbc"), [])
        self.assertEqual(self.requests, [])

    def test_search_keeps_only_items(self):
        self.replies["tbc/search"] = json.dumps({"results": [
            {"type": 3, "id": 2589, "name": "Linen Cloth", "quality": 1},
            {"type": 6, "id": 7, "name": "Linen spell"},
            {"type": 3, "id": "x", "name": "Bad id"},
            {"type": 3, "id": 4238, "name": "Linen Bag", "quality": 99}]}).encode()
        found = self.tips().search("linen", "tbc")
        self.assertEqual(found, [{"item_id": 2589, "name": "Linen Cloth", "quality": 1},
                                 {"item_id": 4238, "name": "Linen Bag", "quality": 1}])


class ItemCatalogTests(StudioTestCase):
    def test_named_items_match_the_words_with_name_starts_first(self):
        e = Events()
        e.add("loot_message", {"text": "You receive loot: |cffffffff|Hitem:2589::::::::|h[Linen Cloth]|h|r"}, 100)
        e.add("auction_sale", {"item": {"id": 4238, "name": "Linen Bag"}}, 110)
        e.add("auction_sale", {"item": {"id": 5762, "name": "Red Linen Bag"}}, 120)
        e.add("auction_sale", {"item": {"id": 2840, "name": "Copper Bar"}}, 130)
        db = e.database(self.folder)
        self.addCleanup(db.close)
        self.assertEqual([i["name"] for i in analytics.item_catalog(db, "linen")],
                         ["Linen Bag", "Linen Cloth", "Red Linen Bag"])
        self.assertEqual(len(analytics.item_catalog(db, "")), 4)
        self.assertEqual(analytics.item_catalog(db, "bar")[0], {"item_id": 2840, "name": "Copper Bar"})


PNG = b"\x89PNG\r\n\x1a\n" + b"icon"
JPEG = b"\xff\xd8\xff" + b"icon"


class IconTests(StudioTestCase):
    def setUp(self):
        super().setUp()
        self.pugger = self.folder / "pugger"
        (self.pugger / "items").mkdir(parents=True)
        (self.pugger / "allwow").mkdir()
        self.requests = []
        self.replies = {}

    def fetch(self, url):
        self.requests.append(url)
        for fragment, reply in self.replies.items():
            if fragment in url:
                if isinstance(reply, Exception):
                    raise reply
                return reply
        raise OSError("unexpected request")

    @staticmethod
    def not_found(url="https://nether.wowhead.com/"):
        return urllib.error.HTTPError(url, 404, "Not Found", {}, None)

    def store(self, **options):
        return icons.IconStore(self.folder / "cache", self.pugger, fetch=self.fetch, **options)

    @staticmethod
    def rows(name="Iron Bar", item_id=None):
        return [{"name": name, "item_id": item_id}]

    def test_pugger_item_by_name_is_used_offline(self):
        (self.pugger / "items" / "adepts-elixir.png").write_bytes(PNG)
        rows = self.rows("Adept's Elixir")
        self.store(online=False).attach(rows, "tbc")
        self.assertEqual(rows[0]["icon"], "data:image/png;base64," + base64.b64encode(PNG).decode())
        self.assertEqual(self.requests, [])

    def test_pugger_item_by_name_is_used_when_wowhead_does_not_know_the_item(self):
        (self.pugger / "items" / "adepts-elixir.png").write_bytes(PNG)
        self.replies["search"] = json.dumps({"results": []}).encode()
        rows = self.rows("Adept's Elixir")
        self.store().attach(rows, "tbc")
        self.assertTrue(rows[0]["icon"].startswith("data:image/png"))

    def test_wowheads_icon_wins_over_a_pugger_picture_with_the_same_name(self):
        (self.pugger / "items" / "elixir-of-minor-agility.png").write_bytes(PNG)
        self.replies["tbc/tooltip/item/2457"] = json.dumps({"icon": "inv_potion_91"}).encode()
        self.replies["large/inv_potion_91.jpg"] = JPEG
        rows = self.rows("Elixir of Minor Agility", 2457)
        self.store().attach(rows, "tbc")
        self.assertTrue(rows[0]["icon"].startswith("data:image/jpeg"))

    def test_a_picture_matched_by_name_is_checked_again_online(self):
        (self.pugger / "items" / "elixir-of-minor-agility.png").write_bytes(PNG)
        self.store(online=False).attach(self.rows("Elixir of Minor Agility", 2457), "forever")
        self.replies["forever/tooltip/item/2457"] = json.dumps({"icon": "inv_potion_91"}).encode()
        self.replies["large/inv_potion_91.jpg"] = JPEG
        rows = self.rows("Elixir of Minor Agility", 2457)
        self.store().attach(rows, "forever")
        self.assertTrue(rows[0]["icon"].startswith("data:image/jpeg"))

    def test_an_item_id_is_looked_up_in_the_sources_own_section(self):
        self.replies["forever/tooltip/item/249409"] = json.dumps({"icon": "inv_inscription_inkcerulean01"}).encode()
        self.replies["large/inv_inscription_inkcerulean01.jpg"] = JPEG
        rows = self.rows("Cerulean Dye", 249409)
        self.store().attach(rows, "forever")
        self.assertTrue(rows[0]["icon"].startswith("data:image/jpeg"))
        self.assertEqual(self.requests[0], "https://nether.wowhead.com/forever/tooltip/item/249409")

    def test_an_id_wowhead_does_not_have_falls_back_to_the_name_and_is_no_network_failure(self):
        self.replies["tooltip/item/249410"] = self.not_found()
        self.replies["forever/search"] = json.dumps({"results": [
            {"type": 3, "name": "Sulfuric Acid", "icon": "trade_alchemy"}]}).encode()
        self.replies["large/trade_alchemy.jpg"] = JPEG
        icon_store = self.store()
        rows = self.rows("Sulfuric Acid", 249410)
        icon_store.attach(rows, "forever")
        self.assertTrue(rows[0]["icon"].startswith("data:image/jpeg"))
        self.assertEqual(icon_store.offline_until, 0)

    def test_an_icon_wowhead_cannot_supply_is_not_found_rather_than_offline(self):
        self.replies["tooltip"] = json.dumps({"icon": "inv_gone"}).encode()
        self.replies["large/inv_gone.jpg"] = self.not_found()
        icon_store = self.store()
        rows = self.rows("Gone", 1)
        icon_store.attach(rows, "forever")
        self.assertIsNone(rows[0]["icon"])
        self.assertEqual(icon_store.offline_until, 0)

    def test_item_id_names_the_icon_and_pugger_supplies_it_whatever_its_case(self):
        (self.pugger / "allwow" / "INV_Ingot_02.png").write_bytes(PNG)
        self.replies["tooltip/item/2840"] = json.dumps({"icon": "inv_ingot_02"}).encode()
        rows = self.rows("Copper Bar", 2840)
        self.store().attach(rows, "tbc")
        self.assertTrue(rows[0]["icon"].startswith("data:image/png"))
        self.assertEqual(len(self.requests), 1)

    def test_a_name_alone_is_searched_in_the_right_section_and_must_match_exactly(self):
        self.replies["forever/search"] = json.dumps({"results": [
            {"type": 3, "name": "Iron Bar Mold", "icon": "wrong"},
            {"type": 6, "name": "Iron Bar", "icon": "spell_wrong"},
            {"type": 3, "name": "iron bar", "icon": "inv_right"}]}).encode()
        self.replies["large/inv_right.jpg"] = JPEG
        rows = self.rows()
        self.store().attach(rows, "forever")
        self.assertTrue(rows[0]["icon"].startswith("data:image/jpeg"))

    def test_found_icons_are_remembered_across_restarts(self):
        (self.pugger / "allwow" / "inv_ingot_iron.png").write_bytes(PNG)
        self.replies["tooltip/item/3575"] = json.dumps({"icon": "inv_ingot_iron"}).encode()
        self.store().attach(self.rows("Iron Bar", 3575), "tbc")
        (self.pugger / "allwow" / "inv_ingot_iron.png").unlink()
        self.requests.clear()
        rows = self.rows("Iron Bar", 3575)
        self.store().attach(rows, "tbc")
        self.assertIsNotNone(rows[0]["icon"])
        self.assertEqual(self.requests, [])

    def test_an_unknown_item_is_not_looked_up_again_soon(self):
        self.replies["search"] = json.dumps({"results": []}).encode()
        icon_store = self.store()
        for _ in range(2):
            rows = self.rows()
            icon_store.attach(rows, "tbc")
            self.assertIsNone(rows[0]["icon"])
        self.assertEqual(len(self.requests), 1)

    def test_no_network_gives_blank_icons_and_stops_trying_for_a_while(self):
        rows = [{"name": f"Item {i}", "item_id": None} for i in range(3)]
        self.store().attach(rows, "tbc")
        self.assertEqual([r["icon"] for r in rows], [None, None, None])
        self.assertEqual(len(self.requests), 1)

    def test_a_network_failure_is_not_remembered_as_not_found(self):
        icon_store = self.store()
        icon_store.attach(self.rows(), "tbc")
        icon_store.offline_until = 0
        (self.pugger / "allwow" / "inv_x.png").write_bytes(PNG)
        self.replies["search"] = json.dumps({"results": [{"type": 3, "name": "Iron Bar", "icon": "inv_x"}]}).encode()
        rows = self.rows()
        icon_store.attach(rows, "tbc")
        self.assertIsNotNone(rows[0]["icon"])

    def test_an_icon_name_cannot_reach_outside_the_cache(self):
        self.replies["tooltip"] = json.dumps({"icon": "../../evil"}).encode()
        rows = self.rows("Bad", 1)
        self.store().attach(rows, "tbc")
        self.assertIsNone(rows[0]["icon"])
        self.assertEqual(len(self.requests), 1)

    def test_a_reply_that_is_not_an_image_is_refused(self):
        self.replies["tooltip"] = json.dumps({"icon": "inv_x"}).encode()
        self.replies["large/inv_x.jpg"] = b"<html>not an image</html>"
        rows = self.rows("Bad", 1)
        self.store().attach(rows, "tbc")
        self.assertIsNone(rows[0]["icon"])

    def test_a_garbled_reply_counts_as_not_found(self):
        self.replies["tooltip"] = b"not json"
        rows = self.rows("Bad", 1)
        self.store().attach(rows, "tbc")
        self.assertIsNone(rows[0]["icon"])

    def test_offline_never_makes_a_request(self):
        rows = self.rows("Bad", 1)
        self.store(online=False).attach(rows, "tbc")
        self.assertIsNone(rows[0]["icon"])
        self.assertEqual(self.requests, [])


def mp4_boxes(data, start=0, end=None):
    """{type: [(payload start, payload end)]} for the boxes between two positions."""
    boxes, at, end = {}, start, len(data) if end is None else end
    while at < end:
        size, kind = struct.unpack(">I4s", data[at:at + 8])
        boxes.setdefault(kind.decode("ascii"), []).append((at + 8, at + size))
        at += size
    return boxes


@unittest.skipUnless(shutil.which("node"), "node is needed to run the browser's MP4 writer")
class Mp4WriterTests(unittest.TestCase):
    SAMPLES = [("frame-one", True), ("frame-two!", False), ("three", False), ("frame-four", True)]

    def write(self, extra="", samples=None):
        samples = self.SAMPLES if samples is None else samples
        items = ",".join(f"{{data:new TextEncoder().encode({json.dumps(text)}),key:{str(key).lower()}}}" for text, key in samples)
        module = (ROOT / "studio" / "static" / "mp4.js").as_uri()
        script = (f'const {{writeMp4}}=await import("{module}");'
                  f'const out=writeMp4({{width:1080,height:1920,timescale:6000,frameDuration:100,'
                  f'description:new TextEncoder().encode("SETUP"),samples:[{items}]{extra}}});'
                  'process.stdout.write(Buffer.from(out).toString("base64"));')
        done = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True)
        if done.returncode:
            raise AssertionError(done.stderr)
        self.data = base64.b64decode(done.stdout)
        return self.data

    def stbl(self):
        data = self.write()
        moov = mp4_boxes(data)["moov"][0]
        trak = mp4_boxes(data, *moov)["trak"][0]
        mdia = mp4_boxes(data, *trak)["mdia"][0]
        minf = mp4_boxes(data, *mdia)["minf"][0]
        return data, mp4_boxes(data, *mp4_boxes(data, *minf)["stbl"][0])

    def test_the_index_comes_before_the_video(self):
        boxes = mp4_boxes(self.write())
        self.assertEqual(list(boxes), ["ftyp", "moov", "mdat"])

    def test_the_offset_points_at_the_first_frame_and_sizes_cover_every_frame(self):
        data, stbl = self.stbl()
        start, _ = stbl["stco"][0]
        offset = struct.unpack(">I", data[start + 8:start + 12])[0]
        start, _ = stbl["stsz"][0]
        count = struct.unpack(">I", data[start + 8:start + 12])[0]
        sizes = struct.unpack(f">{count}I", data[start + 12:start + 12 + count * 4])
        frames, at = [], offset
        for size in sizes:
            frames.append(data[at:at + size].decode())
            at += size
        self.assertEqual(frames, [text for text, _ in self.SAMPLES])
        self.assertEqual(at, len(data))

    def test_key_frames_are_listed_counting_from_one(self):
        data, stbl = self.stbl()
        start, _ = stbl["stss"][0]
        count = struct.unpack(">I", data[start + 4:start + 8])[0]
        self.assertEqual(struct.unpack(f">{count}I", data[start + 8:start + 8 + count * 4]), (1, 4))

    def test_duration_and_frame_timing(self):
        data, stbl = self.stbl()
        moov = mp4_boxes(data)["moov"][0]
        start, _ = mp4_boxes(data, *moov)["mvhd"][0]
        self.assertEqual(struct.unpack(">II", data[start + 12:start + 20]), (6000, 400))
        start, _ = stbl["stts"][0]
        self.assertEqual(struct.unpack(">III", data[start + 4:start + 16]), (1, 4, 100))

    def test_the_encoder_setup_and_size_are_stored(self):
        data, stbl = self.stbl()
        start, end = stbl["stsd"][0]
        entry = mp4_boxes(data, start + 8, end)["avc1"][0]
        self.assertEqual(struct.unpack(">HH", data[entry[0] + 24:entry[0] + 28]), (1080, 1920))
        self.assertIn(b"avcCSETUP", data[entry[0]:entry[1]])

    def test_known_colours_are_recorded_and_unknown_ones_left_out(self):
        known = self.write(extra=',colour:{primaries:"bt709",transfer:"bt709",matrix:"bt709",fullRange:false}')
        self.assertIn(b"colrnclx\x00\x01\x00\x01\x00\x01\x00", known)
        self.assertNotIn(b"colr", self.write(extra=',colour:{primaries:"mystery"}'))

    def test_a_video_must_start_on_a_key_frame(self):
        with self.assertRaises(AssertionError):
            self.write(samples=[("frame", False)])

    def test_an_empty_video_is_refused(self):
        with self.assertRaises(AssertionError):
            self.write(samples=[])


class WindowTests(StudioTestCase):
    def test_marker_runs_until_the_next_marker_or_last_record(self):
        e = Events()
        e.add("episode_start", {"name": "Day 1"}, 1000)
        e.add("episode_start", {"name": "Day 2"}, 2000)
        e.add("logout", {}, 3000)
        db = e.database(self.folder)
        self.addCleanup(db.close)
        windows = {w["id"]: w for w in analytics.windows(db)}
        self.assertEqual((windows["marker:Day 1"]["start"], windows["marker:Day 1"]["end"]), (1000, 2000))
        self.assertEqual((windows["marker:Day 2"]["start"], windows["marker:Day 2"]["end"]), (2000, 3000))

    def test_marker_stops_at_its_end_event(self):
        e = Events()
        e.add("episode_start", {"name": "Day 1"}, 1000)
        e.add("episode_end", {}, 1500)
        e.add("logout", {}, 3000)
        db = e.database(self.folder)
        self.addCleanup(db.close)
        self.assertEqual(analytics.resolve_window(db, "marker:Day 1")["end"], 1500)

    def test_a_label_shared_by_two_accounts_covers_both(self):
        e = Events()
        e.add("episode_start", {"name": "Day 1"}, 1000)
        e.add("episode_end", {}, 1500)
        e.add("episode_start", {"name": "Day 1"}, 1200, source="Other:1:1")
        e.add("episode_end", {}, 1800, source="Other:1:1")
        db = e.database(self.folder)
        self.addCleanup(db.close)
        window = analytics.resolve_window(db, "marker:Day 1")
        self.assertEqual((window["start"], window["end"]), (1000, 1800))

    def test_a_new_marker_on_one_account_ends_the_old_one_on_both(self):
        e = Events()
        e.add("episode_start", {"name": "Day 1"}, 1000)
        e.add("episode_start", {"name": "Day 1"}, 1100, source="Other:1:1")
        e.add("episode_start", {"name": "Day 2"}, 2000, source="Other:1:1")
        e.add("logout", {}, 3000)
        e.add("logout", {}, 2900, source="Other:1:1")
        db = e.database(self.folder)
        self.addCleanup(db.close)
        windows = {w["id"]: w for w in analytics.windows(db)}
        self.assertEqual((windows["marker:Day 1"]["start"], windows["marker:Day 1"]["end"]), (1000, 2000))
        self.assertEqual((windows["marker:Day 2"]["start"], windows["marker:Day 2"]["end"]), (2000, 3000))

    def test_an_account_whose_marker_ended_stays_out_of_the_new_one(self):
        e = Events()
        e.add("episode_start", {"name": "Day 1"}, 1000)
        e.add("episode_end", {}, 1500)
        e.add("episode_start", {"name": "Day 2"}, 2000, source="Other:1:1")
        e.add("logout", {}, 3000)
        e.add("logout", {}, 2500, source="Other:1:1")
        db = e.database(self.folder)
        self.addCleanup(db.close)
        windows = {w["id"]: w for w in analytics.windows(db)}
        self.assertEqual((windows["marker:Day 1"]["start"], windows["marker:Day 1"]["end"]), (1000, 1500))
        self.assertEqual((windows["marker:Day 2"]["start"], windows["marker:Day 2"]["end"]), (2000, 2500))

    def test_the_same_label_started_on_the_other_account_keeps_running(self):
        e = Events()
        e.add("episode_start", {"name": "Day 1"}, 1000)
        e.add("episode_start", {"name": "Day 1"}, 1200, source="Other:1:1")
        e.add("logout", {}, 3000)
        e.add("logout", {}, 2500, source="Other:1:1")
        db = e.database(self.folder)
        self.addCleanup(db.close)
        window = analytics.resolve_window(db, "marker:Day 1")
        self.assertEqual((window["start"], window["end"]), (1000, 3000))

    def test_a_marker_taken_over_from_the_linked_account_counts_from_its_start_there(self):
        e = Events()
        e.add("episode_start", {"name": "Day 1"}, 1000)
        e.add("episode_start", {"name": "Day 2"}, 2000)
        e.add("logout", {}, 3000)
        # The other account was offline at 2000 and took Day 2 over when it came back.
        e.add("episode_start", {"name": "Day 1", "occurredAt": 1000}, 1000, source="Other:1:1")
        e.add("episode_start", {"name": "Day 2", "occurredAt": 2000}, 2600, source="Other:1:1")
        e.add("highlight", {}, 2700, character=(BANK_GUID, "Bank-Realm"), source="Other:1:1")
        e.add("logout", {}, 2900, source="Other:1:1")
        db = e.database(self.folder)
        self.addCleanup(db.close)
        windows = {w["id"]: w for w in analytics.windows(db)}
        self.assertEqual((windows["marker:Day 1"]["start"], windows["marker:Day 1"]["end"]), (1000, 2000))
        self.assertEqual((windows["marker:Day 2"]["start"], windows["marker:Day 2"]["end"]), (2000, 3000))
        (found,) = analytics.highlights(db, windows["marker:Day 2"])
        self.assertEqual((found["marker"], found["since"], found["number"]), ("Day 2", 700, 1))

    def test_the_same_marker_started_again_keeps_the_earlier_start_for_highlights(self):
        e = Events()
        e.add("episode_start", {"name": "Day 1"}, 1100)
        e.add("highlight", {}, 1150)
        e.add("episode_start", {"name": "Day 1", "occurredAt": 1000}, 1200)
        e.add("highlight", {}, 1300)
        db = e.database(self.folder)
        self.addCleanup(db.close)
        found = analytics.highlights(db, analytics.resolve_window(db, "all"))
        self.assertEqual([(h["number"], h["since"]) for h in found], [(1, 50), (2, 300)])

    def test_unknown_window_is_reported(self):
        e = Events()
        e.add("logout", {}, 1000)
        db = e.database(self.folder)
        self.addCleanup(db.close)
        with self.assertRaises(analytics.UnknownWindow):
            analytics.resolve_window(db, "marker:Nope")


class HighlightTests(StudioTestCase):
    def test_highlights_are_timed_into_their_own_accounts_marker_and_removals_are_left_out(self):
        e = Events()
        e.add("episode_start", {"name": "Day 1"}, 1000)
        e.add("highlight", {"note": "Big sale", "zone": "Elwynn Forest"}, 1075)
        mistake = e.add("highlight", {}, 1100)
        e.add("highlight_removed", {"highlightID": mistake}, 1102)
        e.add("highlight", {}, 1300)
        e.add("episode_start", {"name": "Day 1"}, 1200, source="Other:1:1")
        e.add("highlight", {"note": "Bank side"}, 1260, character=(BANK_GUID, "Bank-Realm"), source="Other:1:1")
        e.add("episode_end", {}, 1400)
        e.add("highlight", {}, 1450)
        db = e.database(self.folder)
        self.addCleanup(db.close)
        found = analytics.highlights(db, analytics.resolve_window(db, "marker:Day 1"))
        self.assertEqual([(h["time"], h["number"], h["since"], h["note"], h["character"]) for h in found],
                         [(1075, 1, 75, "Big sale", "Main-Realm"), (1260, 1, 60, "Bank side", "Bank-Realm"),
                          (1300, 2, 300, None, "Main-Realm")])
        everything = analytics.highlights(db, analytics.resolve_window(db, "all"))
        self.assertEqual((everything[-1]["time"], everything[-1]["marker"], everything[-1]["since"]), (1450, None, None))
        self.assertEqual([row["time"] for row in db.execute("SELECT time FROM highlights ORDER BY time")],
                         [1075, 1260, 1300, 1450])
        self.assertIn("highlights", analytics.figures(db, "all", "window"))


class StartFigureTests(StudioTestCase):
    WINDOW = {"start": 1000, "end": 2000}

    def figure(self, e):
        db = e.database(self.folder)
        self.addCleanup(db.close)
        return analytics.start_figure(db, self.WINDOW)

    def test_start_plus_change_equals_end(self):
        e = Events()
        e.add("baseline", {"balance": 500}, 900)
        e.balance(500, 800, 1100)
        e.balance(800, 700, 1200)
        e.balance(700, 9999, 2500)
        figure = self.figure(e)
        self.assertEqual((figure["start"], figure["change"], figure["end"]), (500, 200, 700))

    def test_character_first_seen_during_the_window_is_not_income(self):
        e = Events()
        e.add("baseline", {"balance": 100}, 900)
        e.add("baseline", {"balance": 5000}, 1500, character=(BANK_GUID, "Alt-Realm"))
        figure = self.figure(e)
        self.assertEqual((figure["start"], figure["end"], figure["change"]), (5100, 5100, 0))

    def test_character_first_seen_after_the_window_is_left_out(self):
        e = Events()
        e.add("baseline", {"balance": 100}, 900)
        e.add("baseline", {"balance": 5000}, 2500, character=(BANK_GUID, "Alt-Realm"))
        self.assertEqual(self.figure(e)["end"], 100)

    def test_corrected_balance_is_ignored(self):
        e = Events()
        e.add("baseline", {"balance": 100}, 900)
        wrong = e.balance(100, 0, 1100)
        e.add("balance_correction", {"balanceID": wrong, "amount": 100}, 1101)
        self.assertEqual(self.figure(e)["end"], 100)

    def test_shows_top_three_income_and_top_two_losses_and_rows_add_up(self):
        e = Events()
        e.add("baseline", {"balance": 1000}, 900)
        rows = [("auction_sale", 500), ("quest", 400), ("loot", 300), ("vendor_sale", 100),
                ("repair", -50), ("flight", -40), ("training", -30)]
        balance = 1000
        for offset, (category, amount) in enumerate(rows):
            e.balance(balance, balance + amount, 1100 + offset)
            e.activity(category, amount, 1100 + offset)
            balance += amount
        figure = self.figure(e)
        self.assertEqual([r["label"] for r in figure["income"]], ["Auction house sales", "Quest rewards", "Loot"])
        self.assertEqual([r["label"] for r in figure["losses"]], ["Repair costs", "Flights"])
        shown = sum(r["value"] for r in figure["income"] + figure["losses"])
        self.assertEqual(shown + figure["other"], figure["change"])
        self.assertEqual(figure["other"], 100 - 30)

    def test_gold_no_record_explains_is_its_own_row(self):
        e = Events()
        e.add("baseline", {"balance": 0}, 900)
        e.balance(0, 700, 1100)
        e.activity("quest", 200, 1100)
        figure = self.figure(e)
        self.assertIn({"label": "Not identified", "value": 500}, figure["income"])

    def test_transfers_between_own_characters_are_not_income_or_loss(self):
        e = Events()
        e.add("baseline", {"balance": 1000}, 900)
        e.add("baseline", {"balance": 0}, 900, character=(BANK_GUID, "Alt-Realm"))
        e.balance(1000, 400, 1100)
        e.activity("mail_sent", -600, 1100, recipient="Alt")
        e.balance(0, 600, 1200, character=(BANK_GUID, "Alt-Realm"))
        e.activity("mail_received", 600, 1200, sender="Main-Realm", character=(BANK_GUID, "Alt-Realm"))
        figure = self.figure(e)
        self.assertEqual(figure["change"], 0)
        self.assertEqual((figure["income"], figure["losses"], figure["other"]), ([], [], 0))

    def test_forever_surname_and_hidden_realm_still_mark_a_transfer(self):
        e = Events()
        e.add("baseline", {"balance": 1000}, 900)
        e.add("baseline", {"balance": 0}, 900, character=(BANK_GUID, "Alt-Realm2"))
        e.balance(1000, 400, 1100)
        e.activity("mail_sent", -600, 1100, recipient="Alt Bank-Realm")
        e.balance(0, 600, 1200, character=(BANK_GUID, "Alt-Realm2"))
        e.activity("mail_received", 600, 1200, sender="Main Setharius-Realm2", character=(BANK_GUID, "Alt-Realm2"))
        figure = self.figure(e)
        self.assertEqual((figure["income"], figure["losses"], figure["other"]), ([], [], 0))

    def test_cancelled_activity_and_its_correction_are_both_left_out(self):
        e = Events()
        e.add("baseline", {"balance": 0}, 900)
        e.balance(0, 100, 1100)
        wrong = e.activity("quest", 999, 1100)
        e.activity("quest", -999, 1500, correctsActivityID=wrong)
        e.activity("loot", 100, 1100)
        figure = self.figure(e)
        self.assertEqual(figure["income"], [{"label": "Loot", "value": 100}])

    def test_backfilled_activity_counts_when_it_happened(self):
        e = Events()
        e.add("baseline", {"balance": 0}, 900)
        e.activity("quest", 50, 5000, occurredAt=1500)
        e.activity("loot", 70, 1500, occurredAt=5000)
        labels = [r["label"] for r in self.figure(e)["all_rows"]]
        self.assertIn("Quest rewards", labels)
        self.assertNotIn("Loot", labels)


class AuctionFigureTests(StudioTestCase):
    WINDOW = {"start": 1000, "end": 2000}

    def figure(self, e, chart_range="window"):
        db = e.database(self.folder)
        self.addCleanup(db.close)
        return analytics.auction_figure(db, self.WINDOW, chart_range)

    def test_same_item_groups_by_name_even_when_invoices_lack_an_id(self):
        e = Events()
        e.activity("auction_sale", 1000, 1100, item={"id": False, "name": "Iron Bar"}, quantity=5)
        e.activity("auction_purchase_or_bid", -300, 1200, item={"id": 3575, "name": "Iron Bar"})
        e.activity("auction_deposit", -20, 1300, item={"id": 3575, "name": "Iron Bar"})
        top = self.figure(e)["top"]
        self.assertEqual(len(top), 1)
        self.assertEqual((top[0]["name"], top[0]["net"], top[0]["quantity"]), ("Iron Bar", 680, 5))

    def test_top_five_by_net_gain_excludes_unknown_items_but_counts_them_in_totals(self):
        e = Events()
        for i in range(7):
            e.activity("auction_sale", 100 * (i + 1), 1100 + i, item={"name": f"Item {i}"})
        e.activity("auction_purchase_or_bid", -50, 1200, auctionID=9)
        figure = self.figure(e)
        self.assertEqual([r["name"] for r in figure["top"]], ["Item 6", "Item 5", "Item 4", "Item 3", "Item 2"])
        self.assertEqual((figure["sold"], figure["spent"]), (2800, 50))
        self.assertEqual(figure["net"], 2750)

    def test_lines_are_cumulative_and_end_at_the_totals(self):
        e = Events()
        e.activity("auction_sale", 100, 1100, item={"name": "A"})
        e.activity("auction_purchase", -30, 1200, item={"name": "A"})
        e.activity("auction_sale", 50, 1300, item={"name": "A"})
        points = self.figure(e)["points"]
        self.assertEqual((points[0]["sold"], points[0]["spent"]), (0, 0))
        self.assertEqual((points[-1]["sold"], points[-1]["spent"], points[-1]["time"]), (150, 30, 2000))
        sold = [p["sold"] for p in points]
        self.assertEqual(sold, sorted(sold))

    def test_range_to_date_includes_earlier_sales_but_never_later_ones(self):
        e = Events()
        e.activity("auction_sale", 7, 500, item={"name": "Early"})
        e.activity("auction_sale", 11, 1500, item={"name": "During"})
        e.activity("auction_sale", 13, 2500, item={"name": "Later"})
        self.assertEqual(self.figure(e)["sold"], 11)
        self.tmp2 = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp2.cleanup)
        db = e.database(self.tmp2.name)
        self.addCleanup(db.close)
        self.assertEqual(analytics.auction_figure(db, self.WINDOW, "to_date")["sold"], 18)

    def test_top_items_carry_an_id_when_any_record_has_one(self):
        e = Events()
        e.activity("auction_sale", 1000, 1100, item={"id": False, "name": "Iron Bar"})
        e.activity("auction_deposit", -20, 1300, item={"id": 3575, "name": "Iron Bar"})
        e.activity("auction_sale", 500, 1400, item={"id": False, "name": "Name Only"})
        top = {row["name"]: row["item_id"] for row in self.figure(e)["top"]}
        self.assertEqual(top, {"Iron Bar": 3575, "Name Only": None})

    def test_no_auction_activity_is_flagged(self):
        e = Events()
        e.add("logout", {}, 1500)
        self.assertFalse(self.figure(e)["has_activity"])


class CostFigureTests(StudioTestCase):
    WINDOW = {"start": 1000, "end": 2000}

    def figure(self, e):
        db = e.database(self.folder)
        self.addCleanup(db.close)
        return analytics.cost_figure(db, self.WINDOW)

    @staticmethod
    def values(figure):
        return {row["key"]: row["value"] for row in figure["rows"]}

    def test_each_cost_lands_in_its_row_and_rows_add_up_to_the_total(self):
        e = Events()
        e.activity("training", -100, 1100, service="Shadow Bolt", trainer="class")
        e.activity("training", -40, 1200, service="Linen Belt", trainer="profession")
        e.activity("repair", -300, 1300)
        e.activity("flight", -20, 1400)
        e.activity("auction_purchase", -500, 1500, item={"name": "Iron Bar"})
        e.activity("auction_purchase_or_bid", -250, 1510, item={"name": "Iron Bar"})
        e.activity("auction_sale", 950, 1600, item={"name": "Silk Cloth"}, quantity=1, commission=50, depositRefund=0)
        e.activity("vendor_purchase", -999, 1700)
        figure = self.figure(e)
        self.assertEqual(self.values(figure), {"class_training": 100, "profession_training": 40, "repair": 300,
                                               "flight": 20, "ah_fees": 50, "ah_purchases": 750})
        self.assertEqual(figure["total"], sum(self.values(figure).values()))
        self.assertEqual([row["key"] for row in figure["rows"]][:2], ["ah_purchases", "repair"])

    def test_costs_outside_the_window_are_left_out(self):
        e = Events()
        e.activity("repair", -300, 900)
        e.activity("repair", -30, 1500)
        e.activity("repair", -3, 2100)
        self.assertEqual(self.values(self.figure(e))["repair"], 30)

    def test_older_training_is_split_by_name_and_trainer_visit(self):
        e = Events()
        e.add("snapshot", {"location": "bags", "rows": [{"item": {"id": 2580, "name": "Linen Belt"}}]}, 900)
        e.activity("training", -10, 1100, service="Apprentice Tailoring")
        e.activity("training", -20, 1104, service="Simple Dress")  # Same visit as the rank.
        e.activity("training", -40, 1200, service="Linen Belt")  # Named after a known item.
        e.activity("training", -80, 1300, service="Enchant Chest - Minor Health")
        e.activity("training", -100, 1400, service="Corruption")
        e.activity("training", -200, 1500, service="Immolate")
        values = self.values(self.figure(e))
        self.assertEqual((values["profession_training"], values["class_training"]), (150, 300))

    def test_a_visit_is_one_characters_and_a_recorded_trainer_wins(self):
        e = Events()
        e.activity("training", -10, 1100, service="Apprentice Cook")
        e.activity("training", -100, 1102, service="Fear", character=(BANK_GUID, "Alt-Realm"))
        e.activity("training", -7, 1103, service="Apprentice Pyromancy", trainer="class")
        values = self.values(self.figure(e))
        self.assertEqual((values["profession_training"], values["class_training"]), (10, 107))

    def test_auction_costs_are_lost_deposits_and_the_house_cut(self):
        e = Events()
        scroll = {"id": 10306, "name": "Scroll of Spirit IV"}
        for at in (1100, 1101, 1102):
            e.activity("auction_deposit", -300, at, item=scroll, quantity=5)
        e.activity("auction_deposit", -999, 1103, item=scroll, quantity=20)
        # One sells, so its deposit comes back with the money; one returns unsold.
        e.activity("auction_sale", 2300, 1200, item={"id": False, "name": "Scroll of Spirit IV"}, quantity=5,
                   gross=2100, commission=100, depositRefund=300)
        e.add("auction_return", {"item": scroll, "quantity": 5, "failure": "expired"}, 1300)
        figure = self.figure(e)
        self.assertEqual((figure["parts"]["listing_fees"], figure["parts"]["ah_cut"]), (300, 100))
        self.assertEqual(self.values(figure)["ah_fees"], 400)
        self.assertEqual(figure["unpriced_returns"], 0)

    def test_a_return_takes_only_a_deposit_posted_before_it(self):
        e = Events()
        item = {"name": "Flame Cap"}
        e.add("auction_return", {"item": item, "quantity": 5, "failure": "cancelled"}, 1100)
        e.activity("auction_deposit", -1122, 1200, item=item, quantity=5)
        figure = self.figure(e)
        self.assertEqual((figure["parts"]["listing_fees"], figure["unpriced_returns"]), (0, 1))

    def test_server_outcomes_carry_their_own_deposit_and_are_not_counted_twice(self):
        e = Events()
        item = {"id": 4238, "name": "Linen Bag"}
        e.activity("auction_deposit", -100, 1100, item=item, auctionKey="P:1")
        e.add("auction_outcome", {"auctionKey": "P:1", "item": item, "quantity": 2, "outcome": "expired",
                                  "depositLost": 100}, 1500)
        e.add("auction_return", {"item": item, "quantity": 2, "failure": "expired", "auctionKey": "P:1"}, 1600)
        e.activity("auction_cancel_fee", -25, 1700, auctionID=2)
        self.assertEqual(self.figure(e)["parts"]["listing_fees"], 125)

    # Earlier addon versions marked Forever auctions cancelled when they sold or expired.
    LEGS = {"id": 9789, "name": "Raider's Legguards of Magic"}

    def listing(self, e, key, at, quantity=1, total=7500, deposit=148, item=LEGS):
        e.add("auction_posted", {"key": key, "character": GUID, "item": item, "quantity": quantity,
                                 "totalPrice": total, "deposit": deposit}, at)

    def falsely_cancelled(self, e, key, at, quantity=1, deposit=148, item=LEGS):
        e.add("auction_outcome", {"auctionKey": key, "item": item, "quantity": quantity, "outcome": "cancelled",
                                  "confidence": "server_id", "depositLost": deposit}, at)

    def sale_mail(self, e, at, quantity=1, gross=7500, refund=148, key=None, item=LEGS):
        sale = {"item": item, "quantity": quantity, "gross": gross, "depositRefund": refund,
                "commission": gross // 20, "matchConfidence": "unmatched" if key is None else "inferred_unique"}
        if key:
            sale["auctionKey"] = key
        sale_id = e.add("auction_sale", sale, at)
        e.activity("auction_sale", gross - gross // 20 + refund, at, saleID=sale_id, item=item, quantity=quantity,
                   gross=gross, commission=gross // 20, depositRefund=refund)

    def test_a_cancelled_auction_whose_sale_mail_came_later_lost_nothing(self):
        e = Events()
        self.listing(e, "P:1073672", 1100)
        self.falsely_cancelled(e, "P:1073672", 1400)
        self.sale_mail(e, 1700)
        self.assertEqual(self.figure(e)["parts"]["listing_fees"], 0)

    def test_a_later_sold_outcome_replaces_a_cancel(self):
        e = Events()
        self.listing(e, "P:1", 1100)
        self.falsely_cancelled(e, "P:1", 1400)
        e.add("auction_outcome", {"auctionKey": "P:1", "item": self.LEGS, "quantity": 1, "outcome": "sold",
                                  "replaces": "cancelled"}, 1700)
        self.assertEqual(self.figure(e)["parts"]["listing_fees"], 0)

    def test_a_sale_of_another_price_does_not_refund_a_cancel(self):
        e = Events()
        self.listing(e, "P:1", 1100)
        self.falsely_cancelled(e, "P:1", 1400)
        self.sale_mail(e, 1700, gross=7000)
        self.sale_mail(e, 1300)  # Before the auction left the house.
        self.assertEqual(self.figure(e)["parts"]["listing_fees"], 148)

    def test_a_partly_sold_commodity_loses_only_the_rest_of_its_deposit(self):
        e = Events()
        eye = {"id": 730, "name": "Murloc Eye"}
        self.listing(e, "P:1", 1100, quantity=2, total=2498, deposit=100, item=eye)
        self.falsely_cancelled(e, "P:1", 1150, quantity=2, deposit=100, item=eye)
        self.sale_mail(e, 1600, quantity=1, gross=1249, refund=50, item=eye)
        self.assertEqual(self.figure(e)["parts"]["listing_fees"], 50)

    def test_a_relisted_items_sale_refunds_the_relisting_not_the_expired_one(self):
        e = Events()
        self.listing(e, "P:1", 1100)
        self.falsely_cancelled(e, "P:1", 1300)  # Expired.
        self.listing(e, "P:2", 1400)
        self.falsely_cancelled(e, "P:2", 1500)  # Sold.
        self.sale_mail(e, 1600)
        # The same mail read again without its money taken is not a second refund.
        e.activity("auction_sale", 0, 1650, item=self.LEGS, quantity=1, gross=7500, depositRefund=148)
        db = e.database(self.folder)
        self.addCleanup(db.close)
        losses = analytics._lost_listing_fees(db, analytics._activities(db))
        self.assertEqual(losses, [(1300, 148, GUID, self.LEGS, 1)])

    def test_a_sale_linked_to_its_auction_refunds_only_that_auction(self):
        e = Events()
        self.listing(e, "P:1", 1100)
        self.falsely_cancelled(e, "P:1", 1300)
        self.listing(e, "P:2", 1400)
        self.falsely_cancelled(e, "P:2", 1500)
        self.sale_mail(e, 1600, key="P:1")
        self.assertEqual(self.figure(e)["parts"]["listing_fees"], 148)

    def test_the_cut_of_a_sale_mail_read_again_without_its_money_is_not_counted_twice(self):
        e = Events()
        e.activity("auction_sale", 0, 1100, item={"name": "Scroll"}, gross=2100, commission=100)
        e.activity("auction_sale", 2000, 1101, item={"name": "Scroll"}, gross=2100, commission=100)
        self.assertEqual(self.figure(e)["parts"]["ah_cut"], 100)

    def test_a_listing_still_up_costs_nothing_yet(self):
        e = Events()
        e.activity("auction_deposit", -300, 1100, item={"name": "Iron Bar"}, quantity=5)
        self.assertEqual(self.values(self.figure(e))["ah_fees"], 0)

    def test_bids_the_auction_house_sends_back_are_not_a_cost(self):
        e = Events()
        e.activity("auction_purchase_or_bid", -500, 1100, item={"name": "Iron Bar"})
        e.activity("mail_received", 500, 1500, sender="Alliance Auction House-Realm", subject="Outbid on Iron Bar")
        e.activity("mail_received", 900, 1600, sender="Friend-Realm")
        figure = self.figure(e)
        self.assertEqual((figure["parts"]["bought"], figure["parts"]["bid_refunds"]), (500, 500))
        self.assertEqual(self.values(figure)["ah_purchases"], 0)

    def test_no_costs_is_flagged(self):
        e = Events()
        e.activity("loot", 100, 1500)
        figure = self.figure(e)
        self.assertFalse(figure["has_activity"])
        self.assertEqual(len(figure["rows"]), 6)

    def test_each_character_has_its_own_share_of_every_row(self):
        e = Events()
        alt = (BANK_GUID, "Alt-Realm")
        e.activity("repair", -300, 1100)
        e.activity("repair", -50, 1200, character=alt)
        e.activity("flight", -20, 1300, character=alt)
        e.activity("auction_sale", 950, 1400, item={"name": "Silk"}, quantity=1, commission=40, character=alt)
        figure = self.figure(e)
        rows = {row["key"]: row["by_character"] for row in figure["rows"]}
        self.assertEqual(rows["repair"], {GUID: 300, BANK_GUID: 50})
        self.assertEqual((rows["flight"], rows["ah_fees"]), ({BANK_GUID: 20}, {BANK_GUID: 40}))
        self.assertEqual(figure["parts_by_character"][BANK_GUID]["ah_cut"], 40)
        self.assertEqual([(c["name"], c["total"]) for c in figure["characters"]], [("Main", 300), ("Alt", 110)])

    def test_a_character_keeps_its_place_in_line_whatever_the_window(self):
        e = Events()
        alt = (BANK_GUID, "Alt-Realm")
        e.activity("loot", 5, 500)  # Main is seen first, long before the window.
        e.activity("repair", -50, 1200, character=alt)
        e.activity("repair", -10, 1300)
        self.assertEqual([(c["name"], c["slot"]) for c in self.figure(e)["characters"]], [("Main", 0), ("Alt", 1)])

    def test_a_returned_listing_takes_its_own_characters_deposit(self):
        e = Events()
        alt = (BANK_GUID, "Alt-Realm")
        item = {"name": "Flame Cap"}
        e.activity("auction_deposit", -100, 1100, item=item, quantity=5)
        e.activity("auction_deposit", -700, 1200, item=item, quantity=5, character=alt)
        e.add("auction_return", {"item": item, "quantity": 5, "failure": "expired"}, 1300, character=alt)
        rows = {row["key"]: row["by_character"] for row in self.figure(e)["rows"]}
        self.assertEqual(rows["ah_fees"], {BANK_GUID: 700})

    def test_two_characters_with_one_name_keep_their_realms(self):
        e = Events()
        e.activity("repair", -1, 1100, character=("Player-A", "Same-One"))
        e.activity("repair", -2, 1200, character=("Player-B", "Same-Two"))
        self.assertEqual(sorted(c["name"] for c in self.figure(e)["characters"]), ["Same-One", "Same-Two"])


class RevenueFigureTests(StudioTestCase):
    WINDOW = {"start": 1000, "end": 2000}

    def figure(self, e):
        db = e.database(self.folder)
        self.addCleanup(db.close)
        return analytics.revenue_figure(db, self.WINDOW)

    @staticmethod
    def values(figure):
        return {row["key"]: row["value"] for row in figure["rows"]}

    def test_each_source_lands_in_its_row_and_rows_add_up_to_the_total(self):
        e = Events()
        e.activity("loot", 30, 1100)
        e.activity("quest", 200, 1200)
        e.activity("vendor_sale", 45, 1300)
        e.activity("trade", 500, 1400, counterparty="Stranger")
        e.activity("mail_cod", 80, 1450, sender="Buyer-Realm")
        e.activity("repair", -300, 1500)
        figure = self.figure(e)
        self.assertEqual(self.values(figure), {"ah_sales": 0, "loot": 30, "quest": 200, "vendor_sale": 45, "players": 580})
        self.assertEqual(figure["total"], 855)
        self.assertEqual(figure["rows"][0]["key"], "players")

    def test_a_sale_counts_at_the_buyers_price_and_explains_what_was_collected(self):
        e = Events()
        e.activity("auction_sale", 2300, 1100, item={"name": "Scroll"}, gross=2100, commission=100, depositRefund=300)
        e.activity("auction_sale", 950, 1200, item={"name": "Silk"}, commission=50)  # No price on record.
        figure = self.figure(e)
        self.assertEqual(self.values(figure)["ah_sales"], 3100)
        self.assertEqual(figure["parts"], {"sold_for": 3100, "ah_cut": 150, "deposits_back": 300, "collected": 3250})
        self.assertEqual(figure["rows"][0]["count"], 2)

    def test_a_sale_mail_read_again_without_its_money_is_not_another_sale(self):
        e = Events()
        e.activity("auction_sale", 0, 1100, item={"name": "Scroll"}, gross=2100, commission=100)
        e.activity("auction_sale", 2000, 1101, item={"name": "Scroll"}, gross=2100, commission=100)
        self.assertEqual(self.values(self.figure(e))["ah_sales"], 2100)

    def test_gold_from_own_characters_and_returned_bids_is_not_revenue(self):
        e = Events()
        e.add("baseline", {"balance": 0}, 900, character=(BANK_GUID, "Alt-Realm"))
        e.activity("mail_received", 600, 1100, sender="Alt-Realm")
        e.activity("trade", 300, 1200, counterparty="Alt Bank-Realm2")
        e.activity("mail_received", 500, 1300, sender="Alliance Auction House-Realm")
        e.activity("trade", -50, 1400, counterparty="Stranger")
        figure = self.figure(e)
        self.assertEqual(figure["total"], 0)
        self.assertFalse(figure["has_activity"])

    def test_revenue_outside_the_window_is_left_out_and_split_per_character(self):
        e = Events()
        alt = (BANK_GUID, "Alt-Realm")
        e.activity("quest", 999, 900)
        e.activity("quest", 100, 1100)
        e.activity("quest", 40, 1200, character=alt)
        figure = self.figure(e)
        quests = next(row for row in figure["rows"] if row["key"] == "quest")
        self.assertEqual((quests["value"], quests["by_character"]), (140, {GUID: 100, BANK_GUID: 40}))
        self.assertEqual([c["name"] for c in figure["characters"]], ["Main", "Alt"])


class ValueFigureTests(StudioTestCase):
    WINDOW = {"start": 1000, "end": 2000}

    @staticmethod
    def valuation(e, at, total, source=SOURCE, unpriced=0):
        e.add("valuation", {"scope": "s", "gold": total, "assets": 0, "equipped": 0, "total": total,
                            "unpricedRows": unpriced}, at, source=source)

    def figure(self, e, chart_range="window"):
        db = e.database(self.folder)
        self.addCleanup(db.close)
        return analytics.value_figure(db, self.WINDOW, chart_range)

    def test_accounts_add_up_without_summing_history(self):
        e = Events()
        self.valuation(e, 1100, 100)
        self.valuation(e, 1200, 300, source="Other:1:1")
        self.valuation(e, 1300, 150)
        self.assertEqual([p["total"] for p in self.figure(e)["points"]], [100, 400, 450, 450])

    def test_value_before_the_window_carries_in_as_the_start(self):
        e = Events()
        self.valuation(e, 500, 1000)
        self.valuation(e, 1500, 1250)
        figure = self.figure(e)
        self.assertEqual((figure["points"][0]["time"], figure["first"]), (1000, 1000))
        self.assertEqual((figure["last"], figure["change"]), (1250, 250))

    def test_later_valuations_are_ignored(self):
        e = Events()
        self.valuation(e, 1500, 10, unpriced=3)
        self.valuation(e, 2500, 99, unpriced=9)
        figure = self.figure(e)
        self.assertEqual((figure["last"], figure["unpriced"]), (10, 3))

    def test_no_valuations(self):
        e = Events()
        e.add("logout", {}, 1500)
        figure = self.figure(e)
        self.assertEqual((figure["points"], figure["last"]), ([], None))


def link(item_id, name, quantity=1):
    return f"|cffffffff|Hitem:{item_id}::::::::70::::::::::|h[{name}]|h|r" + (f"x{quantity}" if quantity > 1 else "") + "."


ORE, BAR, THREAD, CHAIN = (1, "Ore"), (2, "Bar"), (3, "Thread"), (9, "Chain")


class ItemAnalysisTests(StudioTestCase):
    WINDOW = {"start": 1000, "end": 2000}

    def analyse(self, e, name):
        db = e.database(self.folder)
        self.addCleanup(db.close)
        return analytics.ItemLedger(db).analyse(name, self.WINDOW["start"], self.WINDOW["end"])

    @staticmethod
    def loot(e, item, at, quantity=1, text="You receive loot: ", **kw):
        e.add("loot_message", {"text": text + link(*item, quantity)}, at, **kw)

    @staticmethod
    def bags(e, at, contents, **kw):
        e.add("snapshot", {"location": "bags", "rows": [{"item": {"id": item_id}, "quantity": count}
                                                        for item_id, count in contents.items()]}, at, **kw)

    def craft(self, e, at, made, before, after, item=CHAIN, **kw):
        """Crafts between two bag snapshots, one chat line per craft."""
        self.bags(e, at, before, **kw)
        for i in range(made):
            self.loot(e, item, at + 1 + i, text="You create: ", **kw)
        self.bags(e, at + 1 + made, after, **kw)

    def test_sales_give_a_count_and_the_highest_and_lowest_price_each(self):
        e = Events()
        e.activity("auction_sale", 950, 1100, item={"id": False, "name": "Chain"}, quantity=2, gross=1000, commission=50)
        e.activity("auction_sale", 2850, 1200, item={"id": 9, "name": "Chain"}, quantity=10, gross=3000, commission=150)
        e.activity("vendor_sale", 40, 1300, item={"id": 9, "name": "Chain"}, quantity=4)
        e.activity("auction_sale", 99999, 2500, item={"id": 9, "name": "Chain"}, quantity=1, gross=99999)
        sold = self.analyse(e, "Chain")["sold"]
        self.assertEqual((sold["quantity"], sold["auction"], sold["vendor"]), (16, 12, 4))
        self.assertEqual((sold["highest"], sold["lowest"], sold["price_from"]), (500, 300, "auction"))
        self.assertEqual(sold["revenue"], 950 + 2850 + 40)

    def test_vendor_prices_are_used_when_nothing_sold_at_auction(self):
        e = Events()
        e.activity("vendor_sale", 40, 1300, item={"id": 9, "name": "Chain"}, quantity=4)
        sold = self.analyse(e, "Chain")["sold"]
        self.assertEqual((sold["highest"], sold["lowest"], sold["price_from"]), (10, 10, "vendor"))

    def test_a_sale_with_no_gross_is_priced_from_what_was_collected(self):
        e = Events()
        e.activity("auction_sale", 1000, 1100, item={"id": 9, "name": "Chain"}, quantity=2, commission=50, depositRefund=100)
        sold = self.analyse(e, "Chain")["sold"]
        self.assertEqual((sold["revenue"], sold["highest"]), (900, 475))

    def test_a_cancelled_sale_is_not_counted(self):
        e = Events()
        sale = e.activity("auction_sale", 950, 1100, item={"id": 9, "name": "Chain"}, quantity=2, gross=1000)
        e.activity("auction_sale", -950, 1150, item={"id": 9, "name": "Chain"}, correctsActivityID=sale)
        self.assertEqual(self.analyse(e, "Chain")["sold"]["quantity"], 0)

    def test_only_your_own_loot_is_farmed(self):
        e = Events()
        self.loot(e, ORE, 1100, 3)
        self.loot(e, ORE, 1200, 2, text="Partymember receives loot: ")
        self.loot(e, ORE, 1300, 4, character=(BANK_GUID, "Alt-Realm"))
        self.loot(e, ORE, 1400, 5, text="You receive item: ")
        self.loot(e, ORE, 2500, 6)
        self.assertEqual(self.analyse(e, "Ore")["gained"]["farmed"], 7)

    @staticmethod
    def merchant_spend(e, before, after, at, merchant=True):
        return e.add("balance", {"before": before, "after": after, "delta": after - before,
                                 "context": {"merchant": True} if merchant else {}}, at)

    @staticmethod
    def unresolved(e, balances, residual, at, status="unresolved"):
        e.add("reconciliation", {"balanceIDs": balances, "activityIDs": {}, "observed": residual,
                                 "explained": 0 if status == "unresolved" else residual,
                                 "residual": residual if status == "unresolved" else 0, "status": status}, at)

    def test_vendor_buys_with_no_record_are_read_from_gold_spent_at_a_merchant(self):
        e = Events()
        thread = (2321, "Fine Thread")
        first = self.merchant_spend(e, 1000, 800, 1100)
        self.loot(e, thread, 1100, text="You receive item: ")
        self.loot(e, thread, 1101, text="You receive item: ")
        second = self.merchant_spend(e, 800, 500, 1102)
        self.loot(e, thread, 1102, 3, text="You receive item: ")
        self.unresolved(e, [first], -200, 1104)
        self.unresolved(e, [second], -300, 1105)
        found = self.analyse(e, "Fine Thread")
        self.assertEqual((found["gained"]["bought"], found["spent"]["bought"]), (5, 500))
        self.assertEqual((found["spent"]["purchases"], found["gained"]["inferred_purchases"]), (2, 2))

    def test_gold_spent_away_from_a_merchant_or_on_mixed_items_is_not_a_buy(self):
        e = Events()
        thread, vial = (2321, "Fine Thread"), (3371, "Empty Vial")
        postage = self.merchant_spend(e, 1000, 970, 1100, merchant=False)
        self.loot(e, thread, 1100, text="You receive item: ")
        self.unresolved(e, [postage], -30, 1102)
        mixed = self.merchant_spend(e, 970, 800, 1200)
        self.loot(e, thread, 1200, text="You receive item: ")
        self.loot(e, vial, 1200, text="You receive item: ")
        self.unresolved(e, [mixed], -170, 1202)
        explained = self.merchant_spend(e, 800, 700, 1300)
        self.loot(e, thread, 1300, text="You receive item: ")
        self.unresolved(e, [explained], -100, 1302, status="balanced")
        self.assertEqual(self.analyse(e, "Fine Thread")["spent"]["purchases"], 0)

    def test_purchases_count_their_cost_and_an_outbid_refund_cancels_one(self):
        e = Events()
        e.activity("auction_purchase", -500, 1100, item={"id": 1, "name": "Ore"}, quantity=5)
        e.activity("vendor_purchase", -30, 1150, item={"id": 1, "name": "Ore"}, quantity=3)
        e.activity("auction_purchase_or_bid", -700, 1200, item={"id": 1, "name": "Ore"})
        e.activity("auction_purchase_or_bid", -800, 1250, item={"id": 1, "name": "Ore"})
        e.activity("mail_received", 800, 1300, sender="Alliance Auction House", subject="Outbid on Ore")
        found = self.analyse(e, "Ore")
        self.assertEqual((found["gained"]["bought"], found["gained"]["unknown_purchases"]), (8, 1))
        self.assertEqual((found["spent"]["bought"], found["spent"]["purchases"]), (1230, 3))

    def test_the_recipe_is_read_from_the_bags_around_a_craft(self):
        e = Events()
        self.loot(e, BAR, 900, text="You receive item: ")
        self.loot(e, THREAD, 900, text="You receive item: ")
        self.craft(e, 1100, 2, {BAR[0]: 10, THREAD[0]: 4}, {BAR[0]: 4, THREAD[0]: 2, CHAIN[0]: 2})
        found = self.analyse(e, "Chain")
        self.assertEqual((found["gained"]["crafted"], found["recipe"]["makes"], found["recipe"]["seen"]), (2, 1, 1))
        self.assertEqual({r["name"]: (r["per_craft"], r["used"]) for r in found["recipe"]["reagents"]},
                         {"Bar": (3, 6), "Thread": (1, 2)})

    def test_a_craft_with_something_else_arriving_is_not_a_recipe(self):
        e = Events()
        self.loot(e, BAR, 900, text="You receive item: ")
        self.craft(e, 1100, 1, {BAR[0]: 10}, {BAR[0]: 7, CHAIN[0]: 1, ORE[0]: 1})
        self.craft(e, 1200, 1, {BAR[0]: 10}, {BAR[0]: 5, CHAIN[0]: 1}, character=(BANK_GUID, "Alt-Realm"))
        self.craft(e, 1300, 1, {BAR[0]: 10}, {BAR[0]: 7, CHAIN[0]: 1})
        self.craft(e, 1400, 1, {BAR[0]: 10}, {BAR[0]: 7, CHAIN[0]: 1})
        recipe = self.analyse(e, "Chain")["recipe"]
        self.assertEqual(({r["name"]: r["per_craft"] for r in recipe["reagents"]}, recipe["seen"]), ({"Bar": 3}, 2))

    def test_a_snapshot_long_after_the_craft_is_not_used(self):
        e = Events()
        self.bags(e, 1100, {BAR[0]: 10})
        self.loot(e, CHAIN, 1101, text="You create: ")
        self.bags(e, 1101 + analytics.CRAFT_SNAPSHOT_SECONDS + 1, {BAR[0]: 7, CHAIN[0]: 1})
        found = self.analyse(e, "Chain")
        self.assertIsNone(found["recipe"])
        self.assertTrue(found["materials_unknown"])

    def test_materials_cost_what_was_paid_on_average_with_farmed_ones_free(self):
        e = Events()
        e.activity("auction_purchase", -600, 900, item={"id": 2, "name": "Bar"}, quantity=6)
        self.loot(e, BAR, 950, 4)
        e.activity("auction_purchase", -9999, 2500, item={"id": 2, "name": "Bar"}, quantity=1)
        self.craft(e, 1100, 2, {BAR[0]: 10}, {BAR[0]: 4, CHAIN[0]: 2})
        found = self.analyse(e, "Chain")
        bar = found["recipe"]["reagents"][0]
        self.assertEqual((bar["unit_cost"], bar["cost"], bar["bought"], bar["farmed"]), (60, 360, 6, 4))
        self.assertEqual((found["spent"]["materials"], found["spent"]["total"]), (360, 360))
        self.assertFalse(found["materials_unknown"])

    def test_a_crafted_material_costs_what_its_own_materials_did(self):
        e = Events()
        e.activity("vendor_purchase", -100, 900, item={"id": 1, "name": "Ore"}, quantity=4)
        self.craft(e, 910, 2, {ORE[0]: 4}, {BAR[0]: 2}, item=BAR)
        self.craft(e, 1100, 1, {BAR[0]: 2}, {CHAIN[0]: 1})
        found = self.analyse(e, "Chain")
        self.assertEqual(found["recipe"]["reagents"][0]["unit_cost"], 50)
        self.assertEqual(found["spent"]["materials"], 100)

    def test_units_used_to_craft_other_items_come_off_what_was_spent(self):
        e = Events()
        e.activity("auction_purchase", -1000, 1050, item={"id": 2, "name": "Bar"}, quantity=10)
        self.craft(e, 1100, 2, {BAR[0]: 10}, {BAR[0]: 4, CHAIN[0]: 2})  # Six bars into two chains.
        e.activity("vendor_sale", 50, 1300, item={"id": 2, "name": "Bar"}, quantity=1)
        found = self.analyse(e, "Bar")
        self.assertEqual(found["used"], {"units": 6, "value": 600, "credited": 600, "unpriced": False,
                                         "into": [{"name": "Chain", "units": 6}]})
        self.assertEqual((found["spent"]["used_in_crafts"], found["spent"]["total"], found["net"]), (600, 400, 50 - 400))
        # The chains count those bars as their materials.
        self.assertEqual(self.analyse(e, "Chain")["spent"]["materials"], 600)

    def test_units_used_never_take_off_more_than_was_spent_in_the_span(self):
        e = Events()
        e.activity("auction_purchase", -1000, 900, item={"id": 2, "name": "Bar"}, quantity=10)  # Before the span.
        self.craft(e, 1100, 2, {BAR[0]: 10}, {BAR[0]: 4, CHAIN[0]: 2})
        found = self.analyse(e, "Bar")
        self.assertEqual((found["used"]["value"], found["used"]["credited"], found["net"]), (600, 0, 0))

    def test_a_material_with_no_cost_on_record_is_flagged(self):
        e = Events()
        self.craft(e, 1100, 1, {BAR[0]: 10}, {BAR[0]: 7, CHAIN[0]: 1})
        found = self.analyse(e, "Chain")
        self.assertEqual(found["recipe"]["reagents"][0]["name"], "Item 2")  # Nothing on record names it.
        self.assertIsNone(found["recipe"]["reagents"][0]["unit_cost"])
        self.assertTrue(found["materials_unknown"])

    def test_net_is_sales_less_purchases_and_materials(self):
        e = Events()
        e.activity("vendor_purchase", -100, 900, item={"id": 2, "name": "Bar"}, quantity=10)
        e.activity("auction_purchase", -400, 1050, item={"id": 9, "name": "Chain"}, quantity=1)
        self.craft(e, 1100, 1, {BAR[0]: 10}, {BAR[0]: 7, CHAIN[0]: 1})
        e.activity("auction_sale", 950, 1200, item={"id": False, "name": "Chain"}, quantity=2, gross=1000, commission=50)
        found = self.analyse(e, "Chain")
        self.assertEqual((found["spent"]["bought"], found["spent"]["materials"], found["net"]), (400, 30, 950 - 430))

    def test_choices_list_items_that_moved_best_selling_first(self):
        e = Events()
        e.activity("auction_sale", 100, 1100, item={"id": 2, "name": "Bar"}, quantity=1, gross=100)
        e.activity("auction_sale", 900, 1100, item={"id": 9, "name": "Chain"}, quantity=1, gross=900)
        self.loot(e, ORE, 1200, 30)
        self.loot(e, THREAD, 2500)
        db = e.database(self.folder)
        self.addCleanup(db.close)
        result = analytics.item_figure(db, self.WINDOW)
        self.assertEqual([c["name"] for c in result["choices"]], ["Chain", "Bar", "Ore"])
        self.assertEqual(result["item"]["name"], "Chain")
        self.assertFalse(analytics.item_figure(db, self.WINDOW, "Thread")["item"]["has_activity"])


class ItemComparisonTests(StudioTestCase):
    WINDOW = {"start": 1000, "end": 2000}
    CHAIN = {"id": 9, "name": "Chain"}

    def ledger(self, e):
        db = e.database(self.folder)
        self.addCleanup(db.close)
        return db

    def compare(self, e, name="Chain"):
        return analytics.ItemLedger(self.ledger(e)).compare(name, self.WINDOW["start"], self.WINDOW["end"])

    def post(self, e, key, at, quantity, deposit, total):
        e.add("auction_posted", {"key": key, "character": GUID, "item": self.CHAIN, "quantity": quantity,
                                 "totalPrice": total, "deposit": deposit}, at)
        e.activity("auction_deposit", -deposit, at, item=self.CHAIN, auctionKey=key)

    def sell(self, e, at, quantity, gross, refund):
        e.activity("auction_sale", gross - gross // 20 + refund, at, item=self.CHAIN, quantity=quantity,
                   gross=gross, commission=gross // 20, depositRefund=refund)

    def test_a_partly_sold_listing_counts_the_units_that_came_back_and_their_deposit(self):
        e = Events()
        e.activity("auction_purchase", -1000, 1050, item=self.CHAIN, quantity=10)
        self.post(e, "P:1", 1100, quantity=4, deposit=40, total=1200)
        # Forever reports a commodity that partly sold as cancelled, losing its whole deposit.
        e.add("auction_outcome", {"auctionKey": "P:1", "outcome": "cancelled", "confidence": "server_id",
                                  "depositLost": 40}, 1300)
        self.sell(e, 1600, quantity=1, gross=300, refund=10)
        row = self.compare(e)
        self.assertEqual((row["sold"], row["each"], row["unit_cost"], row["margin"]), (1, 285, 100, 185))
        self.assertAlmostEqual(row["margin_share"], 1.85)
        self.assertEqual((row["listed"], row["auctions"], row["returned"], row["listing_fees"]), (4, 1, 3, 30))
        self.assertAlmostEqual(row["sales_rate"], 0.25)
        self.assertEqual(row["net"], 285 - 1000 - 30)
        # The nine still held cost 900 of that, so selling one made a profit.
        self.assertEqual(row["profit_sold"], 285 - 100 - 30)
        self.assertEqual((row["stock"], row["stock_value"]), (None, None))

    def test_stock_is_each_characters_latest_bags_bank_mail_and_auctions_up(self):
        e = Events()
        alt = (BANK_GUID, "Alt-Realm")
        e.activity("auction_purchase", -2000, 1050, item=self.CHAIN, quantity=20)
        chain = {"id": 9}  # As a TBC snapshot has it: no name.
        e.add("snapshot", {"location": "bags", "rows": [{"item": chain, "quantity": 5}]}, 1100)
        e.add("snapshot", {"location": "bags", "rows": [{"item": chain, "quantity": 3}]}, 1200)
        e.add("snapshot", {"location": "equipment", "rows": [{"item": chain, "quantity": 1}]}, 1200)
        e.add("snapshot", {"location": "mail", "rows": [{"items": [{"item": chain, "quantity": 2}]}]}, 1300)
        e.add("snapshot", {"location": "auctions", "rows": [{"item": chain, "quantity": 4, "status": 0},
                                                            {"item": chain, "quantity": 9, "status": 1}]}, 1400)
        e.add("snapshot", {"location": "bank", "rows": [{"item": chain, "quantity": 10}]}, 1500, character=alt)
        e.add("snapshot", {"location": "bank", "rows": [{"item": chain, "quantity": 50}]}, 2500, character=alt)
        row = self.compare(e)
        self.assertEqual(row["stock_places"], {"bags": 3, "bank": 10, "mail": 2, "auctions": 4})
        self.assertEqual((row["stock"], row["stock_value"]), (19, 1900))
        self.assertEqual(self.compare(e, "Ore")["stock_places"], {})

    def test_the_item_analysis_counts_deposits_kept_on_unsold_listings_as_spent(self):
        e = Events()
        e.activity("auction_deposit", -60, 1100, item=self.CHAIN, quantity=5)
        e.add("auction_return", {"item": self.CHAIN, "quantity": 5, "failure": "expired"}, 1500)
        e.activity("auction_deposit", -60, 1600, item=self.CHAIN, quantity=5)  # Still up.
        found = analytics.ItemLedger(self.ledger(e)).analyse("Chain", 1000, 2000)
        self.assertEqual((found["spent"]["listing_fees"], found["spent"]["total"], found["net"]), (60, 60, -60))
        self.assertEqual(found["listings"], {"listed": 2, "unsold": 1, "unpriced": 0, "listed_units": 10, "listed_unknown": 0,
                                             "returned": 1, "returned_units": 5, "returned_unknown": 0})

    def test_listings_and_the_sales_rate_count_units_not_auctions(self):
        e = Events()
        e.activity("auction_purchase", -5100, 1050, item=self.CHAIN, quantity=51)
        self.post(e, "P:1", 1100, quantity=1, deposit=10, total=250)
        self.post(e, "P:2", 1100, quantity=50, deposit=100, total=10000)
        e.add("auction_outcome", {"auctionKey": "P:1", "item": self.CHAIN, "quantity": 1, "outcome": "expired",
                                  "depositLost": 10}, 1500)
        e.add("auction_outcome", {"auctionKey": "P:2", "item": self.CHAIN, "quantity": 50, "outcome": "sold"}, 1500)
        self.sell(e, 1600, quantity=50, gross=10000, refund=100)
        row = self.compare(e)
        # One auction in two came back, but only one unit in 51.
        self.assertEqual((row["listed"], row["auctions"], row["returned"]), (51, 2, 1))
        self.assertAlmostEqual(row["sales_rate"], 50 / 51)

    def test_a_listing_bigger_than_a_stack_comes_back_once_however_many_mails_it_takes(self):
        e = Events()
        self.post(e, "P:1", 1100, quantity=79, deposit=100, total=7900)
        e.add("auction_outcome", {"auctionKey": "P:1", "item": self.CHAIN, "quantity": 79, "outcome": "expired",
                                  "depositLost": 100}, 1500)
        for at, units in ((1600, 20), (1600, 20), (1601, 20), (1601, 19)):
            e.add("auction_return", {"item": self.CHAIN, "quantity": units, "failure": "expired",
                                     "subject": "Auction expired: Chain (79)",
                                     "items": [{"item": self.CHAIN, "quantity": units}]}, at)
        row = self.compare(e)
        self.assertEqual((row["listed"], row["returned"]), (79, 79))

    def test_the_mail_shows_how_much_of_a_partly_sold_listing_came_back(self):
        e = Events()
        self.post(e, "P:1", 1100, quantity=10, deposit=100, total=5000)
        self.sell(e, 1200, quantity=1, gross=500, refund=0)
        e.add("auction_outcome", {"auctionKey": "P:1", "item": self.CHAIN, "quantity": 10, "outcome": "cancelled",
                                  "depositLost": 100}, 1500)
        e.add("auction_return", {"item": self.CHAIN, "quantity": 9, "failure": "expired",
                                 "subject": "Auction expired: Chain (9)"}, 1600)
        # A return of another listing no outcome was recorded for still counts.
        e.add("auction_return", {"item": self.CHAIN, "quantity": 5, "failure": "expired",
                                 "subject": "Auction expired: Chain (5)"}, 1050)
        row = self.compare(e)
        self.assertEqual((row["listed"], row["returned"], row["sold"]), (10, 14, 1))

    def test_a_listing_marked_cancelled_whose_deposit_a_sale_gave_back_did_not_come_back(self):
        e = Events()
        self.post(e, "P:1", 1100, quantity=2, deposit=40, total=400)
        e.add("auction_outcome", {"auctionKey": "P:1", "item": self.CHAIN, "quantity": 2, "outcome": "cancelled",
                                  "depositLost": 40}, 1300)
        self.sell(e, 1400, quantity=2, gross=400, refund=40)
        row = self.compare(e)
        self.assertEqual((row["listed"], row["returned"], row["sales_rate"]), (2, 0, 1.0))

    def test_figures_that_cannot_be_worked_out_are_none(self):
        e = Events()
        e.activity("vendor_sale", 40, 1300, item=self.CHAIN, quantity=4)  # Never gained, never listed.
        row = self.compare(e)
        self.assertEqual((row["each"], row["unit_cost"], row["margin"], row["margin_share"], row["sales_rate"]),
                         (10, None, None, None, None))

    def test_an_item_that_cost_nothing_has_a_margin_but_no_share_of_its_cost(self):
        farmed = Events()
        farmed.add("loot_message", {"text": "You receive loot: " + link(9, "Chain", 3)}, 1100)
        self.sell(farmed, 1200, quantity=1, gross=100, refund=0)
        row = self.compare(farmed)
        self.assertEqual((row["unit_cost"], row["margin"], row["margin_share"], row["sales_rate"]), (0, 95, None, 1.0))

    def test_the_best_sellers_are_compared_until_items_are_chosen(self):
        e = Events()
        for at, (item_id, name), gross in ((1100, (1, "Ore"), 50), (1200, (2, "Bar"), 500), (1300, (9, "Chain"), 900),
                                           (1400, (3, "Thread"), 10)):
            e.activity("auction_sale", gross, at, item={"id": item_id, "name": name}, quantity=1, gross=gross)
        db = self.ledger(e)
        names = lambda result: [row["name"] for row in result["items"]]  # noqa: E731
        self.assertEqual(names(analytics.compare_figure(db, self.WINDOW)), ["Chain", "Bar", "Ore"])
        self.assertEqual(names(analytics.compare_figure(db, self.WINDOW, ["Thread", "", "Ore", "Thread"])), ["Thread", "Ore"])
        self.assertEqual(names(analytics.compare_figure(db, self.WINDOW, [])), [])
        many = analytics.compare_figure(db, self.WINDOW, [f"Item {i}" for i in range(10)])
        self.assertEqual(len(many["items"]), analytics.MAX_COMPARED_ITEMS)

    def test_top_items_rank_sales_profit_and_loss(self):
        e = Events()
        ore, bar, thread = {"id": 1, "name": "Ore"}, {"id": 2, "name": "Bar"}, {"id": 3, "name": "Thread"}
        e.activity("auction_purchase", -800, 1050, item=bar, quantity=1)
        e.activity("auction_purchase", -100, 1060, item=thread, quantity=5)
        for at, item, units, gross in ((1100, ore, 5, 50), (1200, bar, 1, 500), (1300, self.CHAIN, 2, 900),
                                       (1400, {"id": 4, "name": "Gem"}, 2, 400)):
            e.activity("auction_sale", gross, at, item=item, quantity=units, gross=gross)
        e.activity("auction_sale", 5000, 2500, item=bar, quantity=50, gross=5000)  # After the window.
        db = self.ledger(e)
        top = analytics.top_items(db, self.WINDOW)
        pairs = lambda rows, key: [(row["name"], row[key]) for row in rows]  # noqa: E731
        # Most units first; the same number of units goes by what they brought in.
        self.assertEqual(pairs(top["sales"], "sold"), [("Ore", 5), ("Chain", 2), ("Gem", 2), ("Bar", 1)])
        self.assertEqual(top["sales"][1]["revenue"], 900)
        self.assertEqual(pairs(top["profit"], "net"), [("Chain", 900), ("Gem", 400), ("Ore", 50)])
        self.assertEqual(pairs(top["loss"], "net"), [("Bar", -300), ("Thread", -100)])
        self.assertEqual(top["loss"][0]["item_id"], 2)
        self.assertEqual([len(top[k]) for k in ("sales", "profit", "loss")], [4, 3, 2])
        self.assertEqual(len(analytics.top_items(db, self.WINDOW, limit=1)["sales"]), 1)

    def test_the_chosen_items_are_kept_with_the_episode(self):
        db = store.connect(self.folder / "plan.sqlite")
        self.addCleanup(db.close)
        episode = store.add_episode(db, store.add_series(db, "Series", "short"))
        settings = {"item": {"view": "compare"}, "compare": {"names": ["Chain", "Ore", "Chain"], "seconds": 4}}
        store.update_episode(db, episode, {"chart_settings": settings})
        saved = store.get_episode(db, episode)["chart_settings"]
        self.assertEqual((saved["item"]["view"], saved["compare"]["names"]), ("compare", ["Chain", "Ore"]))
        periods = {"item": {"view": "periods"}, "periods": {"name": "Chain", "windows": ["day:2026-11-01", "all"]}}
        store.update_episode(db, episode, {"chart_settings": periods})
        saved = store.get_episode(db, episode)["chart_settings"]
        self.assertEqual((saved["periods"]["name"], saved["periods"]["windows"]), ("Chain", ["day:2026-11-01", "all"]))
        for bad in ({"compare": {"names": "Chain"}}, {"compare": {"names": [""]}}, {"item": {"view": "both"}},
                    {"compare": {"names": [f"Item {i}" for i in range(7)]}}, {"periods": {"windows": ["all"]}},
                    {"periods": {"windows": ["all", "all"]}}, {"periods": {"name": 3}}):
            with self.assertRaises(store.Invalid, msg=bad):
                store.update_episode(db, episode, {"chart_settings": bad})


class PeriodComparisonTests(StudioTestCase):
    WINDOW, CHAIN = ItemComparisonTests.WINDOW, ItemComparisonTests.CHAIN
    ledger, post, sell = ItemComparisonTests.ledger, ItemComparisonTests.post, ItemComparisonTests.sell

    def marked(self):
        e = Events()
        e.add("episode_start", {"name": "Week 1"}, 1000)
        e.activity("auction_purchase", -1000, 1050, item=self.CHAIN, quantity=10)
        self.post(e, "P:1", 1100, quantity=4, deposit=40, total=1200)
        e.add("auction_outcome", {"auctionKey": "P:1", "item": self.CHAIN, "quantity": 4, "outcome": "sold"}, 1200)
        self.sell(e, 1200, quantity=4, gross=1200, refund=40)
        e.add("episode_start", {"name": "Week 2"}, 2000)
        self.post(e, "P:2", 2100, quantity=6, deposit=60, total=1200)
        e.add("auction_outcome", {"auctionKey": "P:2", "item": self.CHAIN, "quantity": 6, "outcome": "expired",
                                  "depositLost": 60}, 2500)
        e.add("episode_start", {"name": "Week 3"}, 3000)
        e.activity("vendor_sale", 10, 3500, item={"id": 1, "name": "Ore"}, quantity=1)
        return self.ledger(e)

    def test_one_item_is_compared_across_two_windows_earliest_first(self):
        db = self.marked()
        later, earlier = (analytics.resolve_window(db, f"marker:Week {n}") for n in (2, 1))
        result = analytics.periods_figure(db, [later, earlier], "Chain")
        self.assertEqual([row["window"]["id"] for row in result["items"]], ["marker:Week 1", "marker:Week 2"])
        first, second = result["items"]
        self.assertEqual((first["sold"], first["listed"], first["returned"], first["sales_rate"]), (4, 4, 0, 1.0))
        self.assertEqual((second["sold"], second["listed"], second["returned"], second["sales_rate"]), (0, 6, 6, 0.0))
        # Items are offered from both windows together, and the first is shown when none is chosen.
        self.assertEqual(analytics.periods_figure(db, [earlier, later])["name"], "Chain")

    def test_the_episode_window_is_compared_with_the_one_before_it(self):
        db = self.marked()
        ids = lambda found: [w["id"] for w in found]  # noqa: E731
        self.assertEqual(ids(analytics.default_periods(db, "marker:Week 2")), ["marker:Week 1", "marker:Week 2"])
        self.assertEqual(ids(analytics.default_periods(db, "marker:Week 1")), ["marker:Week 1"])
        self.assertEqual(ids(analytics.default_periods(db, "all")), ["marker:Week 2", "marker:Week 3"])
        self.assertEqual(ids(analytics.default_periods(db, "marker:Gone")), ["marker:Week 2", "marker:Week 3"])


class MockDataTests(StudioTestCase):
    def setUp(self):
        super().setUp()
        path = self.folder / "mock.json"
        path.write_text(json.dumps(mockdata.build_export()), encoding="utf-8")
        self.db = ledger.connect(self.folder / "mock.sqlite")
        self.addCleanup(self.db.close)
        ledger.import_file(self.db, path)

    def test_is_identical_every_time(self):
        self.assertEqual(mockdata.build_export(), mockdata.build_export())

    def test_linen_bags_are_crafted_from_bolts_made_of_farmed_and_bought_linen(self):
        found = analytics.item_figure(self.db, analytics.resolve_window(self.db, "all"), "Linen Bag")["item"]
        self.assertEqual({r["name"]: r["per_craft"] for r in found["recipe"]["reagents"]},
                         {"Bolt of Linen Cloth": 3, "Coarse Thread": 3})
        self.assertGreater(found["spent"]["materials"], 0)
        self.assertEqual(found["sold"]["quantity"], found["gained"]["crafted"])
        self.assertLess(found["sold"]["lowest"], found["sold"]["highest"])

    def test_every_day_has_a_marker_and_adds_up(self):
        windows = [w for w in analytics.windows(self.db) if w["kind"] == "marker"]
        self.assertEqual([w["label"] for w in windows], [f"Day {i}" for i in range(1, 8)])
        changes = []
        for window in windows:
            figure = analytics.start_figure(self.db, window)
            self.assertEqual(figure["start"] + figure["change"], figure["end"])
            shown = sum(r["value"] for r in figure["income"] + figure["losses"])
            self.assertEqual(shown + figure["other"], figure["change"])
            changes.append(figure["change"])
        self.assertTrue(any(c < 0 for c in changes), "one day should show a loss")
        self.assertTrue(any(c > 0 for c in changes))


class ServerTests(StudioTestCase):
    def setUp(self):
        super().setUp()
        self.app = studio.Studio(self.folder / "data", wow_roots=[], pugger_icons=None, online=False)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), studio.make_handler(self.app, 0))
        self.port = self.server.server_address[1]
        self.server.RequestHandlerClass = studio.make_handler(self.app, self.port)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port)
        sent = {"Content-Type": "application/json", **(headers or {})}
        connection.request(method, path, json.dumps(body) if body is not None else None, sent)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, data

    def api(self, method, path, body=None):
        status, data = self.request(method, path, body)
        self.assertEqual(status, 200, data)
        return json.loads(data)

    def test_serves_the_page_and_the_seeded_plan(self):
        status, page = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"<title>", page)
        self.assertTrue(self.api("GET", "/api/tree")["series"])

    def test_another_website_cannot_write(self):
        status, _ = self.request("POST", "/api/series", {"name": "x", "format": "short"},
                                 {"Origin": "https://evil.example"})
        self.assertEqual(status, 403)

    def test_a_rebound_host_is_refused(self):
        status, _ = self.request("GET", "/api/tree", headers={"Host": "evil.example"})
        self.assertEqual(status, 403)

    def test_form_posts_are_refused(self):
        status, _ = self.request("POST", "/api/series", {"name": "x", "format": "short"},
                                 {"Content-Type": "text/plain"})
        self.assertEqual(status, 403)

    def test_paths_outside_the_app_are_not_served(self):
        self.assertEqual(self.request("GET", "/../studio.py")[0], 404)

    def test_bad_input_gets_a_readable_error(self):
        status, data = self.request("POST", "/api/series", {"name": "x", "format": "nope"})
        self.assertEqual(status, 400)
        self.assertIn("Format", json.loads(data)["error"])

    def test_figures_include_an_icon_slot_for_each_top_item(self):
        top = self.api("GET", "/api/data/mock/figures?window=all&range=to_date")["auction"]["top"]
        self.assertEqual(len(top), 5)
        self.assertTrue(all("icon" in row for row in top))

    def test_item_analysis_picks_the_best_seller_and_attaches_icons(self):
        result = self.api("GET", "/api/data/mock/item?window=all")
        self.assertEqual(result["item"]["name"], result["choices"][0]["name"])
        self.assertIn("icon", result["item"])
        bag = self.api("GET", "/api/data/mock/item?window=marker:Gone&name=Linen%20Bag")
        self.assertEqual((bag["window"]["id"], bag["item"]["name"]), ("all", "Linen Bag"))
        self.assertTrue(all("icon" in r for r in bag["item"]["recipe"]["reagents"]))
        self.assertEqual(self.api("GET", "/api/data/tbc/item"), {"empty": True})

    def test_comparison_shows_the_best_sellers_or_the_chosen_items_with_icons(self):
        result = self.api("GET", "/api/data/mock/compare?window=all")
        self.assertEqual([r["name"] for r in result["items"]], [c["name"] for c in result["choices"][:3]])
        self.assertTrue(all("icon" in r for r in result["items"]))
        chosen = self.api("GET", "/api/data/mock/compare?window=all&chosen=1&name=Linen%20Bag")
        self.assertEqual([r["name"] for r in chosen["items"]], ["Linen Bag"])
        self.assertEqual(self.api("GET", "/api/data/mock/compare?window=all&chosen=1")["items"], [])
        self.assertEqual(self.api("GET", "/api/data/tbc/compare"), {"empty": True})

    def test_period_comparison_uses_the_chosen_windows_or_the_episode_window_and_the_one_before(self):
        windows = [w for w in self.api("GET", "/api/data/mock/windows")["windows"] if w["kind"] == "marker"]
        first, second = windows[0]["id"], windows[1]["id"]
        query = lambda pairs: urllib.parse.urlencode(pairs)  # noqa: E731
        chosen = self.api("GET", "/api/data/mock/periods?" + query([("period", second), ("period", first), ("name", "Linen Bag")]))
        self.assertEqual([r["window"]["id"] for r in chosen["items"]], [first, second])
        self.assertEqual(chosen["name"], "Linen Bag")
        self.assertTrue(all("icon" in r for r in chosen["items"]))
        default = self.api("GET", "/api/data/mock/periods?" + query([("window", second), ("period", "marker:Gone"), ("period", first)]))
        self.assertEqual([w["id"] for w in default["windows"]], [first, second])
        self.assertEqual(default["name"], default["choices"][0]["name"])
        self.assertEqual(self.api("GET", "/api/data/tbc/periods"), {"empty": True})

    def test_sources_stay_separate(self):
        mock = self.api("GET", "/api/data/mock/figures?window=all&range=to_date")
        self.assertGreater(mock["value"]["last"], 0)
        self.assertEqual(self.api("GET", "/api/data/tbc/figures"), {"empty": True})
        self.assertEqual(self.api("GET", "/api/data/forever/windows"), {"windows": []})

    def test_an_account_cannot_be_imported_into_two_sources(self):
        e = Events()
        e.add("baseline", {"balance": 5}, 100)
        path = self.folder / "account.json"
        path.write_text(json.dumps({"schema": 1, "sourceID": SOURCE, "events": e.events}), encoding="utf-8")
        self.assertTrue(self.app.import_path("tbc", str(path))["ok"])
        result = self.app.import_path("forever", str(path))
        self.assertFalse(result["ok"])
        self.assertIn("TBC Anniversary", result["error"])
        self.assertFalse(self.app.ledger_path("forever").exists())

    def test_detects_each_client_and_never_writes_to_it(self):
        root = self.folder / "wow"
        for client in ("_anniversary_", "_forever_"):
            saved = root / client / "WTF" / "Account" / "ME" / "SavedVariables"
            saved.mkdir(parents=True)
            source = client.strip("_")
            e = Events()
            e.add("baseline", {"balance": 5}, 100, source=f"{source}:1:1")
            (saved / "ForeverLedger.lua").write_text(
                json.dumps({"schema": 1, "sourceID": f"{source}:1:1", "events": e.events}), encoding="utf-8")
        before = {p: p.stat().st_mtime_ns for p in root.rglob("*.lua")}
        self.app.wow_roots = [root]
        self.app.import_changed()
        self.assertEqual(self.api("GET", "/api/data/tbc/figures?window=all")["start"]["end"], 5)
        self.assertEqual(self.api("GET", "/api/data/forever/figures?window=all")["start"]["end"], 5)
        self.assertEqual(before, {p: p.stat().st_mtime_ns for p in root.rglob("*.lua")})

    def test_a_removed_file_stays_removed(self):
        root = self.folder / "wow"
        saved = root / "_forever_" / "WTF" / "Account" / "ME" / "SavedVariables"
        saved.mkdir(parents=True)
        path = saved / "ForeverLedger.lua"
        path.write_text(json.dumps({"schema": 1, "sourceID": "F:1:1", "events": []}), encoding="utf-8")
        self.app.wow_roots = [root]
        self.app.import_changed()
        self.app.remove_file("forever", str(path))
        self.app.import_changed()
        self.assertEqual(self.app.files("forever"), [])

    def test_a_restart_does_not_import_an_unchanged_file_again(self):
        root = self.folder / "wow"
        saved = root / "_forever_" / "WTF" / "Account" / "ME" / "SavedVariables"
        saved.mkdir(parents=True)
        (saved / "ForeverLedger.lua").write_text(json.dumps({"schema": 1, "sourceID": "F:1:1", "events": []}), encoding="utf-8")
        self.app.wow_roots = [root]
        self.app.import_changed()
        restarted = studio.Studio(self.folder / "data", wow_roots=[root], pugger_icons=None, online=False)
        restarted.import_path = lambda *_: self.fail("the unchanged file was imported again")
        restarted.import_changed()

    def test_a_half_written_file_reports_an_error_and_keeps_working(self):
        path = self.folder / "broken.json"
        path.write_text("{ not json", encoding="utf-8")
        self.assertFalse(self.app.import_path("forever", str(path))["ok"])
        self.assertEqual(self.api("GET", "/api/data/forever/windows"), {"windows": []})

    def test_a_missing_window_falls_back_and_says_so(self):
        figures = self.api("GET", "/api/data/mock/figures?window=marker:Gone&range=window")
        self.assertEqual(figures["window_missing"], "marker:Gone")
        self.assertEqual(figures["window"]["id"], "all")

    def test_visual_search_lists_ledger_items_and_the_item_falls_back_to_its_name_offline(self):
        e = Events()
        e.add("auction_sale", {"item": {"id": 4238, "name": "Linen Bag"}}, 110)
        path = self.folder / "account.json"
        path.write_text(json.dumps({"schema": 1, "sourceID": SOURCE, "events": e.events}), encoding="utf-8")
        self.assertTrue(self.app.import_path("tbc", str(path))["ok"])
        found = self.api("GET", "/api/visual/tbc/search?q=linen")
        self.assertEqual(found["items"], [{"item_id": 4238, "name": "Linen Bag", "in_ledger": True}])
        self.assertEqual(self.api("GET", "/api/visual/forever/search?q=linen")["items"], [])
        item = self.api("GET", "/api/visual/tbc/item?id=4238&name=Linen%20Bag")
        self.assertEqual((item["name"], item["found"], item["lines"]), ("Linen Bag", False, []))
        self.assertIn("icon", item)
        self.assertNotIn("icon_name", item)
        for bad in ("id=x", "id=0", ""):
            self.assertEqual(self.request("GET", f"/api/visual/tbc/item?{bad}")[0], 400)
        self.assertEqual(self.request("GET", "/api/visual/nope/item?id=1")[0], 404)

    def test_visual_top_items_come_with_icons_and_fall_back_to_all_history(self):
        self.assertEqual(self.api("GET", "/api/visual/tbc/top"), {"empty": True})
        e = Events()
        e.activity("auction_sale", 900, 110, item={"id": 4238, "name": "Linen Bag"}, quantity=1, gross=900)
        path = self.folder / "account.json"
        path.write_text(json.dumps({"schema": 1, "sourceID": SOURCE, "events": e.events}), encoding="utf-8")
        self.assertTrue(self.app.import_path("tbc", str(path))["ok"])
        top =self.api("GET", "/api/visual/tbc/top?window=marker:Gone")
        self.assertEqual(top["window"]["id"], "all")
        self.assertEqual([row["name"] for row in top["sales"]], ["Linen Bag"])
        self.assertIn("icon", top["sales"][0])
        self.assertEqual(top["loss"], [])

    def test_episode_round_trip(self):
        series = self.api("POST", "/api/series", {"name": "New", "format": "long"})["id"]
        episode = self.api("POST", f"/api/series/{series}/episodes", {})["id"]
        self.api("PATCH", f"/api/episodes/{episode}", {"title": "Custom", "script": "One. Two."})
        self.assertEqual(self.api("POST", f"/api/episodes/{episode}/shots/rebuild", {})["lines"], 2)
        loaded = self.api("GET", f"/api/episodes/{episode}")
        self.assertEqual((loaded["title"], loaded["format"], len(loaded["shots"])), ("Custom", "long", 2))
        self.api("DELETE", f"/api/episodes/{episode}")
        self.assertEqual(self.request("GET", f"/api/episodes/{episode}")[0], 404)


if __name__ == "__main__":
    unittest.main()
