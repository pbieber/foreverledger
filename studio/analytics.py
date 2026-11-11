"""Chart figures from one ledger database. All money is integer copper.

Facts come from immutable events, following SCHEMA.md: a corrected balance is left
out, a cancelled activity and its correction are both left out, and `occurredAt`
wins over `time` for anything per period.
"""
from __future__ import annotations

import bisect
import datetime
import functools
import json
import re
import sqlite3
from collections import Counter, defaultdict, deque

import ledger

LABELS = {
    "repair": "Repair costs", "loot": "Loot", "quest": "Quest rewards",
    "auction_sale": "Auction house sales", "auction_purchase": "Auction house purchases",
    "auction_purchase_or_bid": "Auction house purchases", "auction_deposit": "Auction house fees",
    "auction_cancel_fee": "Auction house fees", "vendor_sale": "Vendor sales",
    "vendor_purchase": "Vendor purchases", "vendor_buyback": "Vendor purchases", "flight": "Flights",
    "training": "Training", "mail_received": "Mail received", "mail_sent": "Mail sent",
    "mail_cod": "Cash on delivery", "postage": "Postage", "trade": "Trades",
}
AH_SOLD = {"auction_sale"}
AH_SPENT = {"auction_purchase", "auction_purchase_or_bid", "auction_deposit", "auction_cancel_fee"}
TRANSFER_CATEGORIES = {"trade", "mail_received", "mail_sent", "mail_cod"}
STORAGE_CATEGORIES = {"bank_deposit", "bank_withdrawal"}
UNKNOWN_ITEM = "Unknown item"
MAX_POINTS = 240
COST_ROWS = (("class_training", "Class training"), ("profession_training", "Profession training"),
             ("repair", "Repairs"), ("flight", "Flights"), ("ah_fees", "Auction house costs"),
             ("ah_purchases", "Auction house purchases"))
AH_BOUGHT = {"auction_purchase", "auction_purchase_or_bid"}
COST_PARTS = ("listing_fees", "ah_cut", "bought", "bid_refunds")
REVENUE_ROWS = (("ah_sales", "Auction house sales"), ("loot", "Looted gold"), ("quest", "Quest rewards"),
                ("vendor_sale", "Vendor sales"), ("players", "From other players"))
REVENUE_PARTS = ("sold_for", "ah_cut", "deposits_back", "collected")
PLAYER_CATEGORIES = {"trade", "mail_received", "mail_cod"}
# Ranks and recipe families that no class spell is named like.
PROFESSION_PREFIXES = ("Apprentice ", "Journeyman ", "Expert ", "Artisan ", "Master ", "Grand Master ", "Enchant ",
                       "Elixir of ", "Flask of ", "Transmute", "Smelt ")
# Lessons bought this close together, by one character, came from one trainer.
TRAINER_VISIT_SECONDS = 10
ITEM_LINK = re.compile(r"\|Hitem:(\d+)[^|]*\|h\[([^\]]*)\]\|h\|r(?:x(\d+))?")
# What the English client says when the recording character itself gains an item.
FARMED_PREFIX, CRAFTED_PREFIX, RECEIVED_PREFIX = "You receive loot: ", "You create: ", "You receive item: "
# How far a "You receive item" line may be from the gold it cost at a merchant.
MERCHANT_LINE_SECONDS = 2
ITEM_SOLD = {"auction_sale": "auction", "vendor_sale": "vendor"}
ITEM_BOUGHT = {"auction_purchase": "auction", "auction_purchase_or_bid": "auction", "vendor_purchase": "vendor"}
OUTBID_PREFIX = "Outbid on "
# A bag snapshot this long after a craft may hold other changes, so it can't show the recipe.
CRAFT_SNAPSHOT_SECONDS = 30
MAX_ITEM_CHOICES = 300
MAX_COMPARED_ITEMS = 6
# What an item's record holds: sales, purchases, own loot and crafts, auctions posted,
# deposits kept on auctions that came back unsold, and the auctions that came back.
RECORD_KEYS = ("sold", "bought", "farmed", "crafted", "listed", "unsold", "returned")
# Snapshot places whose items count as stock, in the order a breakdown lists them.
STOCK_PLACES = ("bags", "bank", "mail", "auctions")


class UnknownWindow(Exception):
    pass


class Reader(sqlite3.Connection):
    """A connection that can carry `memo`: a dict of what was already worked out from
    its database. Reading a whole ledger takes seconds, so whoever opens the connection
    hands every one the same dict until the database changes, then a new one, and lets
    one thread at a time use it."""
    memo = None


def _once(function):
    """Work a whole-ledger answer out once per `Reader.memo`. The answer is shared, so
    callers must not change it. A plain connection works it out every time."""
    @functools.wraps(function)
    def remembered(db):
        memo = getattr(db, "memo", None)
        if memo is None:
            return function(db)
        if function.__name__ not in memo:
            memo[function.__name__] = function(db)
        return memo[function.__name__]
    return remembered


def _midnight_before(timestamp):
    local = datetime.datetime.fromtimestamp(timestamp)
    return timestamp - (local.hour * 3600 + local.minute * 60 + local.second)


def _day_bounds(timestamp):
    """The local day holding a moment. Stepping past 24 hours copes with clock changes."""
    start = _midnight_before(timestamp)
    return start, _midnight_before(start + 26 * 3600) - 1


def marker_intervals(db):
    """Each marker's stretches of time, per account, in order.

    A marker runs until its end, the next marker started on any account, or the
    account's last record. Both accounts can use one label, so a name can hold several
    intervals, and starting that same label on the other account leaves it running.
    A new label on one account also moves every account still in an older marker onto
    it, so a marker forgotten on one account doesn't stretch the old window over the
    new one. An account whose marker has ended stays outside the new one. A marker the
    addon took over from a linked account counts from when it began there.
    """
    latest = dict(db.execute("SELECT source_id,MAX(time) FROM events GROUP BY source_id").fetchall())
    intervals, open_marker = {}, {}

    def close(source, at):
        name, started = open_marker.pop(source)
        intervals.setdefault(name, []).append((started, at))

    for source, moment, kind, data in db.execute(
            "SELECT source_id,COALESCE(json_extract(data,'$.occurredAt'),time) AS moment,kind,data FROM events "
            "WHERE kind IN ('episode_start','episode_end') ORDER BY moment,source_id,sequence"):
        if source in open_marker:
            close(source, moment)
        if kind == "episode_start":
            name = json.loads(data).get("name") or "Unnamed marker"
            for other in [s for s, (open_name, _) in open_marker.items() if open_name != name]:
                close(other, moment)
                open_marker[other] = (name, moment)
            open_marker[source] = (name, moment)
    for source in list(open_marker):
        close(source, latest[source])
    return intervals


@_once
def windows(db):
    """Time spans an episode can use: markers first, then calendar days, then everything."""
    span = db.execute("SELECT MIN(time),MAX(time) FROM events").fetchone()
    if span[0] is None:
        return []
    result = []
    markers = sorted(marker_intervals(db).items(), key=lambda item: min(i[0] for i in item[1]))
    for name, intervals in markers:
        result.append({"id": f"marker:{name}", "kind": "marker", "label": name,
                       "start": min(i[0] for i in intervals), "end": max(i[1] for i in intervals)})
    days = {}
    for (moment,) in db.execute("SELECT DISTINCT time FROM events ORDER BY time DESC"):
        days.setdefault(datetime.datetime.fromtimestamp(moment).date(), moment)
    for day, moment in days.items():
        start, end = _day_bounds(moment)
        result.append({"id": f"day:{day.isoformat()}", "kind": "day", "label": day.strftime("%a %d %b %Y"),
                       "start": start, "end": min(end, span[1])})
    result.append({"id": "all", "kind": "all", "label": "All recorded history", "start": span[0], "end": span[1]})
    return result


def resolve_window(db, window_id):
    for window in windows(db):
        if window["id"] == window_id:
            return window
    raise UnknownWindow(window_id)


@_once
def _balances(db):
    """Per character, time-ordered (time, balance), with the opening balance kept separately."""
    corrected = {json.loads(row[0]).get("balanceID") for row in db.execute(
        "SELECT data FROM events WHERE kind='balance_correction'")}
    series, opening = {}, {}
    for event_id, source, character, moment, kind, data in db.execute(
            "SELECT id,source_id,character,time,kind,data FROM events WHERE kind IN ('baseline','balance') "
            "ORDER BY time,source_id,sequence"):
        if event_id in corrected:
            continue
        d, key = json.loads(data), (source, character)
        balance = d.get("balance") if kind == "baseline" else d.get("after")
        if balance is None:
            continue
        if key not in series:
            first = d.get("before") if kind == "balance" else None
            opening[key] = balance if first is None else first
        series.setdefault(key, []).append((moment, balance))
    return series, opening


def gold_between(db, start, end):
    """Gold at the start and end of a span.

    A character first seen inside the span counts from the balance it arrived with,
    so an old character logging in for the first time is not mistaken for income.
    """
    series, opening = _balances(db)
    total_start, total_end, characters = 0, 0, 0
    for key, points in series.items():
        if points[0][0] > end:
            continue
        before = [balance for moment, balance in points if moment <= start]
        through = [balance for moment, balance in points if moment <= end]
        total_start += before[-1] if before else opening[key]
        total_end += through[-1]
        characters += 1
    return total_start, total_end, characters


@_once
def _owners(db):
    return ledger.owned_keys(db)


@_once
def _activities(db):
    """Activities that still stand, as (time, data, character), in time order."""
    rows = [(event_id, moment, json.loads(data), character) for event_id, moment, data, character in db.execute(
        "SELECT id,time,data,character FROM events WHERE kind='activity'")]
    voided = {d[key] for _, _, d, _ in rows for key in ("correctsActivityID", "correctsSaleID") if d.get(key)}
    standing = [(d.get("occurredAt") or moment, d, character) for event_id, moment, d, character in rows
                if event_id not in voided and not d.get("correctsActivityID")]
    standing.sort(key=lambda row: row[0])
    return standing


def _is_internal(data, owners):
    if data.get("category") in STORAGE_CATEGORIES:
        return True
    peer = data.get("counterparty") or data.get("sender") or data.get("recipient")
    return bool(data.get("category") in TRANSFER_CATEGORIES and peer and ledger.character_key(peer) in owners)


def start_figure(db, window):
    """Gold at the marker start, the change over the window, and what drove it."""
    start, end = window["start"], window["end"]
    start_gold, end_gold, characters = gold_between(db, start, end)
    change = end_gold - start_gold
    owners = _owners(db)
    by_label, explained = {}, 0
    for moment, d, _ in _activities(db):
        amount = d.get("amount") or 0
        if not start <= moment <= end or not amount:
            continue
        explained += amount
        if not _is_internal(d, owners):
            label = LABELS.get(d.get("category"), d.get("category") or "Other")
            by_label[label] = by_label.get(label, 0) + amount
    unexplained = change - explained
    if unexplained:
        by_label["Not identified"] = by_label.get("Not identified", 0) + unexplained
    rows = [{"label": label, "value": value} for label, value in by_label.items() if value]
    income = sorted((r for r in rows if r["value"] > 0), key=lambda r: (-r["value"], r["label"]))[:3]
    losses = sorted((r for r in rows if r["value"] < 0), key=lambda r: (r["value"], r["label"]))[:2]
    shown = sum(r["value"] for r in income + losses)
    return {"start": start_gold, "end": end_gold, "change": change, "characters": characters,
            "income": income, "losses": losses, "other": change - shown,
            "all_rows": sorted(rows, key=lambda r: -r["value"])}


def _thin(points, start, end):
    """Keep the last point of each equal time step, plus the first and last."""
    if len(points) <= MAX_POINTS:
        return points
    step = max(1, (end - start)) / MAX_POINTS
    kept = {}
    for point in points:
        kept[int((point["time"] - start) / step)] = point
    result = [kept[key] for key in sorted(kept)]
    if result[0] is not points[0]:
        result.insert(0, points[0])
    if result[-1] is not points[-1]:
        result.append(points[-1])
    return result


def _span(db, window, chart_range):
    if chart_range == "to_date":
        first = db.execute("SELECT MIN(time) FROM events").fetchone()[0]
        return first, window["end"]
    return window["start"], window["end"]


def _vendor_stock_listed(db, activities):
    """What vendor-bought units cost when they went up for auction: [(time, copper)].

    Each item keeps its vendor-bought units first in, first out. A listing takes them at
    what they cost, as many as it holds and as are left, so units bought but never listed
    cost nothing here, and units listed beyond the vendor's, as farmed ones, cost nothing
    either. A unit that came back unsold is not charged again when it goes back up: a
    return gives credit for up to the units charged and still out, and a later listing
    uses that credit first. Purchases and listings with no quantity can't be split into
    units, so they are left out.
    """
    names, steps = {}, defaultdict(list)  # name -> [(time, order, kind, units, copper)]

    def name_of(item):
        return item.get("name") or names.get(_item_id(item.get("id")))

    posted = _postings(db)
    for moment, d, _ in activities:
        category, item = d.get("category"), d.get("item") or {}
        if item.get("name") and _item_id(item.get("id")):
            names[_item_id(item.get("id"))] = item["name"]
        if category == "vendor_purchase" and item.get("name") and (d.get("quantity") or 0) > 0:
            steps[item["name"]].append((moment, 0, "bought", d["quantity"], -(d.get("amount") or 0)))
        elif category == "auction_deposit" and item.get("name"):
            units = d.get("quantity") or posted.get(d.get("auctionKey"), {}).get("quantity") or 0
            if units > 0:
                steps[item["name"]].append((moment, 2, "listed", units, 0))
    for moment, item_id, name, quantity, cost in _unrecorded_vendor_buys(db):
        steps[name].append((moment, 0, "bought", quantity, cost))
    for moment, _, item, units in _returned_listings(db, activities):
        name = name_of(item)
        if name in steps and units:
            steps[name].append((moment, 1, "returned", units, 0))
    charges = []
    for rows in steps.values():
        if not any(kind == "bought" for _, _, kind, _, _ in rows):
            continue
        pool, out, credit = deque(), 0, 0  # Units bought and not yet listed; units charged and still out.
        for moment, _, kind, units, copper in sorted(rows, key=lambda row: row[:2]):
            if kind == "bought":
                pool.append([units, copper / units])
            elif kind == "returned":
                back = min(units, out)
                out, credit = out - back, credit + back
            else:
                again = min(credit, units)
                credit, out, units = credit - again, out + again, units - again
                cost = 0.0
                while units and pool:
                    take = min(units, pool[0][0])
                    cost += take * pool[0][1]
                    pool[0][0] -= take
                    units, out = units - take, out + take
                    if not pool[0][0]:
                        pool.popleft()
                if round(cost):
                    charges.append((moment, round(cost)))
    return charges


def auction_figure(db, window, chart_range):
    """Cumulative gold collected and spent at the auction house, and the best items.

    Sold is gold collected, net of commission, and includes returned deposits. Spent
    is purchases plus deposits and cancellation fees. Sales count when their mail is
    collected. Net gain is cash only: stock still held is not counted. Spent with
    vendor stock adds what vendor-bought units cost when they were listed (see
    `_vendor_stock_listed`), counted at the listing.
    """
    start, end = _span(db, window, chart_range)
    sold, spent, stock, items = 0, 0, 0, {}
    points = [{"time": start, "sold": 0, "spent": 0, "spent_stock": 0}]
    activities = _activities(db)
    changes = [(moment, d) for moment, d, _ in activities]
    changes += [(moment, {"category": "vendor_stock", "amount": -copper})
                for moment, copper in _vendor_stock_listed(db, activities)]
    changes.sort(key=lambda change: change[0])
    for moment, d in changes:
        category, amount = d.get("category"), d.get("amount") or 0
        if not start <= moment <= end or not amount or category not in AH_SOLD | AH_SPENT | {"vendor_stock"}:
            continue
        if category in AH_SOLD:
            sold += amount
        elif category in AH_SPENT:
            spent -= amount
        else:
            stock -= amount
        points.append({"time": moment, "sold": sold, "spent": spent, "spent_stock": spent + stock})
        if category == "vendor_stock":
            continue
        name = (d.get("item") or {}).get("name") or UNKNOWN_ITEM
        row = items.setdefault(name, {"name": name, "item_id": None, "net": 0, "sold": 0, "spent": 0, "quantity": 0})
        row["item_id"] = row["item_id"] or (d.get("item") or {}).get("id") or None
        row["net"] += amount
        if category in AH_SOLD:
            row["sold"] += amount
            row["quantity"] += d.get("quantity") or 0
        else:
            row["spent"] -= amount
    points.append({"time": end, "sold": sold, "spent": spent, "spent_stock": spent + stock})
    named = [row for name, row in items.items() if name != UNKNOWN_ITEM]
    top = sorted(named, key=lambda row: (-row["net"], row["name"]))[:5]
    return {"start": start, "end": end, "sold": sold, "spent": spent, "spent_stock": spent + stock,
            "net": sold - spent,
            "points": _thin(points, start, end), "top": top, "items": len(named),
            "has_activity": bool(items)}


def value_figure(db, window, chart_range):
    """Estimated total value over time, adding each account's latest valuation.

    One valuation only ever describes its own account, so accounts add up safely at
    any moment. Each stays at its last value until its next observation.
    """
    start, end = _span(db, window, chart_range)
    latest, points = {}, []

    def snapshot(moment):
        return {"time": moment, "total": sum(v["total"] for v in latest.values()),
                "gold": sum(v["gold"] for v in latest.values()),
                "assets": sum(v["assets"] for v in latest.values()),
                "equipped": sum(v["equipped"] for v in latest.values()),
                "unpriced": sum(v["unpriced"] for v in latest.values())}

    for moment, source, data in db.execute(
            "SELECT time,source_id,data FROM events WHERE kind='valuation' AND time<=? ORDER BY time,source_id,sequence",
            (end,)):
        d = json.loads(data)
        if moment >= start and not points and latest:
            points.append(snapshot(start))
        latest[(source, d.get("scope"))] = {
            "total": d.get("total") or 0, "gold": d.get("gold") or 0, "assets": d.get("assets") or 0,
            "equipped": d.get("equipped") or 0, "unpriced": d.get("unpricedRows") or 0}
        if moment >= start:
            points.append(snapshot(moment))
    if latest and not points:
        points.append(snapshot(start))
    if points and points[-1]["time"] < end:
        points.append(dict(points[-1], time=end))
    first, last = (points[0], points[-1]) if points else (None, None)
    return {"start": start, "end": end, "points": _thin(points, start, end),
            "first": first["total"] if first else None, "last": last["total"] if last else None,
            "change": last["total"] - first["total"] if points else None,
            "unpriced": last["unpriced"] if last else 0, "accounts": len(latest)}


@_once
def _item_names(db):
    """Every item name the ledger has seen, from item records anywhere in the events."""
    names = set()

    def walk(value):
        if isinstance(value, dict):
            if isinstance(value.get("name"), str) and ("id" in value or "link" in value):
                names.add(value["name"])
            for inner in value.values():
                walk(inner)
        elif isinstance(value, list):
            for inner in value:
                walk(inner)

    for (data,) in db.execute("SELECT data FROM events"):
        walk(json.loads(data))
    return names


def _training_kinds(trainings, item_names):
    """"class" or "profession" for each training activity, keyed by id() of its data.

    Newer records say which kind of trainer it was. Older ones are judged by name:
    a profession rank, an enchant, or a recipe named after an item the ledger has
    seen. A trainer visit follows its clearest member, which catches recipes for
    items never seen. Anything else counts as a class lesson. `item_names` is called
    only if a name has to be looked up.
    """
    visits, last = [], {}
    for moment, d, character in trainings:
        previous = last.get(character)
        if previous and moment - previous[0] <= TRAINER_VISIT_SECONDS:
            visit = previous[1]
            visit.append(d)
        else:
            visit = [d]
            visits.append(visit)
        last[character] = (moment, visit)

    names = None

    def looks_like_profession(d):
        nonlocal names
        if d.get("trainer") in ("class", "profession"):
            return d["trainer"] == "profession"
        service = d.get("service") or ""
        if service.startswith(PROFESSION_PREFIXES):
            return True
        if names is None:
            names = item_names()
        return service in names

    kinds = {}
    for visit in visits:
        profession = any(looks_like_profession(d) for d in visit)
        for d in visit:
            known = d.get("trainer")
            kinds[id(d)] = known if known in ("class", "profession") else "profession" if profession else "class"
    return kinds


def _deposits_not_lost(db, activities):
    """How much of each auction's lost deposit a sale gave back, by auctionKey, and the
    auctions whose last outcome is a sale.

    Earlier addon versions read Forever's AUCTION_CANCELED, which fires when an auction
    sells or expires, as a cancel. The auction stayed "cancelled" and the sale mail that
    followed matched nothing. So a sale's deposit refund goes back to its own auction or,
    unmatched, to the same character's auctions of that item and unit price whose deposit
    was marked lost, most recently left first. A partly sold commodity keeps the rest.
    """
    posted = {}
    for data, in db.execute("SELECT data FROM events WHERE kind='auction_posted'"):
        d = json.loads(data)
        posted[d.get("key")] = d
    lost, final = {}, {}
    for moment, data in db.execute("SELECT time,data FROM events WHERE kind='auction_outcome' ORDER BY time"):
        d = json.loads(data)
        final[d.get("auctionKey")] = d.get("outcome")
        if d.get("depositLost"):
            lost[d.get("auctionKey")] = (d.get("leftAt") or moment, d["depositLost"])
    keys = {}
    for event_id, data in db.execute("SELECT id,data FROM events WHERE kind='auction_sale'"):
        keys[event_id] = json.loads(data).get("auctionKey")

    refunded = defaultdict(int)
    for moment, d, character in activities:
        refund = d.get("depositRefund") or 0
        if d.get("category") != "auction_sale" or (d.get("amount") or 0) <= 0 or refund <= 0:
            continue
        key = keys.get(d.get("saleID"))
        if key:
            candidates = [key] if key in lost else []
        else:
            name, quantity, gross = (d.get("item") or {}).get("name"), d.get("quantity"), d.get("gross")
            candidates = [k for k, a in posted.items() if k in lost and a.get("character") == character
                          and (a.get("item") or {}).get("name") == name and lost[k][0] <= moment
                          and quantity and gross is not None and a.get("quantity") and a.get("totalPrice") is not None
                          and gross * a["quantity"] == a["totalPrice"] * quantity]
            candidates.sort(key=lambda k: -lost[k][0])
        for k in candidates:
            take = min(refund, lost[k][1] - refunded[k])
            if take > 0:
                refunded[k] += take
                refund -= take
    sold = {k for k, outcome in final.items() if outcome == "sold"}
    return refunded, sold


def _lost_listing_fees(db, activities):
    """Each deposit kept by the auction house because a listing came back unsold.

    Returns (time, copper, character, item, units) per loss, with copper None when the
    deposit is not on record and units None when the quantity isn't. A partly sold
    commodity counts only the units its lost deposit was for, as the deposit is per unit.
    A server-identified outcome carries its deposit, less what a sale of
    that auction gave back (see `_deposits_not_lost`). Otherwise, as on
    the old auction house, a returned listing takes the same character's earliest
    earlier deposit for the same item and quantity that no sale has claimed back.
    """
    timeline = []
    for moment, d, character in activities:
        category = d.get("category")
        if category == "auction_deposit" and not d.get("auctionKey"):
            timeline.append((moment, 0, "deposit", d, character))
        elif category == "auction_sale":
            timeline.append((moment, 1, "sale", d, character))
    for moment, kind, data, character in db.execute(
            "SELECT time,kind,data,character FROM events WHERE kind IN ('auction_outcome','auction_return')"):
        timeline.append((moment, 1, kind, json.loads(data), character))
    timeline.sort(key=lambda row: (row[0], row[1]))

    refunded, sold = _deposits_not_lost(db, activities)
    listed = _postings(db)
    unsold, losses = {}, []
    for moment, _, kind, d, character in timeline:
        key = (character, (d.get("item") or {}).get("name"), d.get("quantity"))
        deposits = unsold.setdefault(key, deque())
        if kind == "deposit":
            deposits.append(-(d.get("amount") or 0))
        elif kind == "sale":
            if deposits:
                refund = d.get("depositRefund")
                if refund in deposits:
                    deposits.remove(refund)
                else:
                    deposits.popleft()
        elif kind == "auction_outcome":
            key = d.get("auctionKey")
            if d.get("depositLost") and key not in sold and d["depositLost"] > refunded[key]:
                posting = listed.get(key, {})
                lost, quantity = d["depositLost"] - refunded[key], d.get("quantity") or posting.get("quantity")
                units = round(quantity * lost / d["depositLost"]) if quantity else None
                losses.append((moment, lost, character, d.get("item") or posting.get("item") or {}, units))
                refunded[key] = d["depositLost"]  # An auction loses its deposit once.
        elif not d.get("auctionKey"):
            losses.append((moment, deposits.popleft() if deposits else None, character, d.get("item") or {},
                           d.get("quantity") or None))
    return losses


@_once
def _postings(db):
    """Each auction posted, by its key, with what was listed. An outcome may leave that
    out, and a later posting record can be a bare status change, so those are skipped."""
    posted = {}
    for data, in db.execute("SELECT data FROM events WHERE kind='auction_posted'"):
        d = json.loads(data)
        if d.get("item"):
            posted[d.get("key")] = d
    return posted


STACK_IN_SUBJECT = re.compile(r"\((\d+)\)\s*$")


def _returned_listings(db, activities):
    """Each listing that came back without selling: (time, character, item, units), with
    units None when the quantity isn't known.

    An auction the house identified counts by its last outcome, as one marked cancelled
    can turn out sold. Earlier addon versions marked sales and expiries cancelled too, so
    the deposit a sale gave back says how much of a lost one really sold (see
    `_deposits_not_lost`), and a partly sold commodity counts only the units left. Units
    come from the outcome or else its posting.

    A listing comes back as a mail per stack, each with the units that came back in its
    subject, as "Auction expired: Mild Spices (79)". A mail names its auction only
    sometimes. One that doesn't belongs to the earliest outcome for the same character and
    item at or before it that was listed with at least that many units and isn't yet
    accounted for, and the units mailed replace the outcome's own count, as they show
    what really came back. Only what no outcome takes counts on its own.
    """
    refunded, sold = _deposits_not_lost(db, activities)
    posted, last = _postings(db), {}
    for moment, character, data in db.execute(
            "SELECT time,character,data FROM events WHERE kind='auction_outcome' ORDER BY time,id"):
        d = json.loads(data)
        if d.get("auctionKey"):
            last[d["auctionKey"]] = (moment, character, d)
    outcomes, waiting = [], defaultdict(list)
    for key, (moment, character, d) in last.items():
        if d.get("outcome") not in ("expired", "cancelled") or key in sold:
            continue
        posting = posted.get(key, {})
        item = d.get("item") or posting.get("item") or {}
        stack = d.get("quantity") or posting.get("quantity") or None
        lost = d.get("depositLost")
        if lost and refunded[key] >= lost:
            continue  # A sale gave the whole deposit back.
        units = round(stack * (lost - refunded[key]) / lost) if lost and stack else stack
        if units == 0:
            continue
        outcome = {"time": moment, "character": character, "item": item, "units": units, "stack": stack, "mailed": 0}
        outcomes.append(outcome)
        if stack:
            waiting[(character, item.get("name"))].append(outcome)
    for claims in waiting.values():
        claims.sort(key=lambda outcome: outcome["time"])
    returned = []
    for moment, character, data in db.execute(
            "SELECT time,character,data FROM events WHERE kind='auction_return' ORDER BY time,id"):
        d = json.loads(data)
        if d.get("auctionKey") in last:
            continue
        item = d.get("item") or {}
        stacks = [i.get("quantity") or 0 for i in d.get("items") or [] if (i.get("item") or {}).get("id") == item.get("id")]
        units = sum(stacks) or d.get("quantity") or None
        left = STACK_IN_SUBJECT.search(d.get("subject") or "")
        size = int(left.group(1)) if left else units
        if not d.get("auctionKey") and units:
            for outcome in waiting.get((character, item.get("name")), []):
                room = outcome["stack"] - outcome["mailed"]
                if outcome["time"] <= moment and size <= outcome["stack"] and room > 0:
                    take = min(room, units)
                    outcome["mailed"], units = outcome["mailed"] + take, units - take
                    if not units:
                        break
            if units == 0:
                continue
        returned.append((moment, character, item, units))
    returned += [(o["time"], o["character"], o["item"], o["mailed"] or o["units"]) for o in outcomes]
    returned.sort(key=lambda row: row[0])
    return returned


def cost_figure(db, window):
    """What was spent in a window on six kinds of cost, largest first.

    Auction house costs are listing fees lost to unsold auctions plus the house's
    cut of each sale, which never reached the wallet. A listing still up has cost
    nothing yet. Purchases are net of bids the auction house sent back.
    """
    start, end = window["start"], window["end"]
    activities = _activities(db)
    inside = [row for row in activities if start <= row[0] <= end]
    tally = _Tally(COST_ROWS, COST_PARTS)
    book, piece, counts, pieces = tally.book, tally.piece, tally.counts, tally.pieces

    trainings = [row for row in inside if row[1].get("category") == "training"]
    kinds = _training_kinds(trainings, lambda: _item_names(db))
    for _, d, character in inside:
        category, amount = d.get("category"), d.get("amount") or 0
        if category == "training":
            key = f"{kinds[id(d)]}_training"
            book(character, key, -amount)
            counts[key] += 1
        elif category in ("repair", "flight"):
            book(character, category, -amount)
            counts[category] += 1
        elif category in AH_BOUGHT:
            piece(character, "bought", -amount)
            counts["ah_purchases"] += 1
        elif category == "auction_cancel_fee":
            piece(character, "listing_fees", -amount)
            counts["ah_fees"] += 1
        elif category == "auction_sale" and d.get("commission") and amount > 0:
            # A sale mail read again without its money taken is not another sale.
            piece(character, "ah_cut", d["commission"])
        elif category == "mail_received" and amount > 0 and "Auction House" in (d.get("sender") or ""):
            piece(character, "bid_refunds", amount)

    unpriced = 0
    for moment, copper, character, *_ in _lost_listing_fees(db, activities):
        if start <= moment <= end:
            if copper is None:
                unpriced += 1
            else:
                piece(character, "listing_fees", copper)
                counts["ah_fees"] += 1
    for character, p in pieces.items():
        book(character, "ah_fees", p["listing_fees"] + p["ah_cut"])
        book(character, "ah_purchases", p["bought"] - p["bid_refunds"])

    result = tally.result(db, window)
    parts = result["parts"]
    for row in result["rows"]:
        if row["key"] == "ah_fees":
            row["parts"] = [{"label": "Unsold listing fees", "value": parts["listing_fees"]},
                            {"label": "Auction house cut", "value": parts["ah_cut"]}]
    return dict(result, unpriced_returns=unpriced)


def revenue_figure(db, window):
    """What came in during a window, from five kinds of revenue, largest first.

    Auction house sales count at the price the buyer paid, so that, with the house's
    cut counted as a cost, revenue less costs is what was really made. A returned
    deposit was never a cost, so it is not revenue either. Gold from your own
    characters, and bids the auction house sends back, are not revenue.
    """
    start, end = window["start"], window["end"]
    owners = _owners(db)
    tally = _Tally(REVENUE_ROWS, REVENUE_PARTS)
    for moment, d, character in _activities(db):
        category, amount = d.get("category"), d.get("amount") or 0
        if not start <= moment <= end or amount <= 0:
            continue
        if category == "auction_sale":
            cut, back = d.get("commission") or 0, d.get("depositRefund") or 0
            sold_for = d.get("gross") or amount + cut - back
            tally.book(character, "ah_sales", sold_for)
            tally.counts["ah_sales"] += 1
            for key, copper in (("sold_for", sold_for), ("ah_cut", cut), ("deposits_back", back), ("collected", amount)):
                tally.piece(character, key, copper)
        elif category in ("loot", "quest", "vendor_sale"):
            tally.book(character, category, amount)
            tally.counts[category] += 1
        elif (category in PLAYER_CATEGORIES and not _is_internal(d, owners)
              and "Auction House" not in (d.get("sender") or "")):
            tally.book(character, "players", amount)
            tally.counts["players"] += 1
    return tally.result(db, window)


class _Tally:
    """Copper per character for each row of a breakdown, plus per-character parts that
    explain a row, and how many records each row came from."""

    def __init__(self, row_defs, part_keys):
        self.row_defs, self.part_keys = row_defs, part_keys
        self.amounts, self.pieces = {}, {}
        self.counts = {key: 0 for key, _ in row_defs}

    def book(self, character, key, copper):
        rows = self.amounts.setdefault(character, {key: 0 for key, _ in self.row_defs})
        rows[key] += copper

    def piece(self, character, key, copper):
        found = self.pieces.setdefault(character, {key: 0 for key in self.part_keys})
        found[key] += copper

    def result(self, db, window):
        """Rows largest first, each with its share per character, and the characters
        that have any, in their fixed order."""
        amounts = self.amounts
        totals = {key: sum(rows[key] for rows in amounts.values()) for key, _ in self.row_defs}
        order = {key: i for i, (key, _) in enumerate(self.row_defs)}
        rows = [{"key": key, "label": label, "value": totals[key], "count": self.counts[key],
                 "by_character": {c: v[key] for c, v in amounts.items() if v[key]}} for key, label in self.row_defs]
        rows.sort(key=lambda row: (-row["value"], order[row["key"]]))
        known = dict(_characters(db))
        for character in amounts:
            known.setdefault(character, {"id": character, "name": character, "slot": len(known)})
        characters = [dict(known[c], total=sum(amounts[c].values()))
                      for c in sorted(amounts, key=lambda c: known[c]["slot"]) if any(amounts[c].values())]
        return {"start": window["start"], "end": window["end"], "total": sum(totals.values()), "rows": rows,
                "parts": {key: sum(p[key] for p in self.pieces.values()) for key in self.part_keys},
                "parts_by_character": self.pieces, "characters": characters, "has_activity": any(totals.values())}


@_once
def _characters(db):
    """Every character with a fixed place in line, so it keeps one colour whatever the
    window or selection: the order each first did anything with money."""
    rows = db.execute(
        "SELECT character, MIN(time), (SELECT e2.character_name FROM events e2 WHERE e2.character=e.character "
        "ORDER BY e2.time DESC LIMIT 1) FROM events e WHERE kind='activity' GROUP BY character "
        "ORDER BY MIN(time), character").fetchall()
    short = [(name or character).split("-")[0] for character, _, name in rows]
    result = {}
    for slot, ((character, _, name), first) in enumerate(zip(rows, short)):
        # Two characters with one name on different realms keep the realm to tell them apart.
        label = first if short.count(first) == 1 else (name or character)
        result[character] = {"id": character, "name": label, "slot": slot}
    return result


def _item_id(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


@_once
def _names_by_id(db):
    """Item names by ID, from item records and chat links anywhere outside snapshots.

    TBC snapshots carry links with no name in them, so their items are named from here.
    """
    names = {}

    def walk(value):
        if isinstance(value, dict):
            item_id, name = _item_id(value.get("id")), value.get("name")
            if item_id and isinstance(name, str) and name:
                names.setdefault(item_id, name)
            for inner in value.values():
                walk(inner)
        elif isinstance(value, list):
            for inner in value:
                walk(inner)
        elif isinstance(value, str) and "|Hitem:" in value:
            for match in ITEM_LINK.finditer(value):
                if match.group(2):
                    names.setdefault(int(match.group(1)), match.group(2))

    for (data,) in db.execute("SELECT data FROM events WHERE kind NOT IN ('snapshot','valuation')"):
        walk(json.loads(data))
    return names


def item_catalog(db, words="", limit=30):
    """Items this ledger has named, matching the words, best matches first: [{item_id, name}]."""
    words = words.strip().casefold()
    found = [(name.casefold().find(words), name.casefold(), item_id, name)
             for item_id, name in _names_by_id(db).items() if words in name.casefold()]
    found.sort(key=lambda row: (row[0] != 0, row[1], row[2]))
    return [{"item_id": item_id, "name": name} for _, _, item_id, name in found[:limit]]


@_once
def _unrecorded_vendor_buys(db):
    """Vendor buys recorded only as gold leaving at a merchant: (time, item ID, name, quantity, copper).

    Before the addon read Forever's merchant interface, a buy there made no intent, so
    its gold change was left unresolved. Each "You receive item" line goes with the
    character's nearest spend at a merchant, a second or two away at most. An
    unresolved reconciliation whose every gold change was such a spend, and whose lines
    all name one item, is a buy of that many for its unexplained gold. Lines nearest a
    spend that is already explained, and anything mixed, are left alone.
    """
    spends = {}  # (source, character) -> [(time, balance ID)]
    for event_id, source, character, moment, data in db.execute(
            "SELECT id,source_id,character,time,data FROM events WHERE kind='balance'"):
        d = json.loads(data)
        if (d.get("delta") or 0) < 0 and (d.get("context") or {}).get("merchant"):
            spends.setdefault((source, character), []).append((moment, event_id))
    for found in spends.values():
        found.sort()
    owner = {}  # balance ID -> index of the unresolved reconciliation it belongs to
    unresolved = []
    for source, character, data in db.execute(
            "SELECT source_id,character,data FROM events WHERE kind='reconciliation' "
            "AND json_extract(data,'$.status')='unresolved' ORDER BY time,source_id,sequence"):
        d = json.loads(data)
        known = {event_id for _, event_id in spends.get((source, character), [])}
        ids = d.get("balanceIDs") or []
        if (d.get("residual") or 0) < 0 and ids and all(i in known for i in ids):
            owner.update((i, len(unresolved)) for i in ids)
            unresolved.append({"time": 0, "cost": -d["residual"], "lines": []})
    if not unresolved:
        return []
    for source, character, moment, data in db.execute(
            "SELECT source_id,character,time,data FROM events WHERE kind='loot_message' ORDER BY time,source_id,sequence"):
        text = json.loads(data).get("text") or ""
        match = ITEM_LINK.search(text) if text.startswith(RECEIVED_PREFIX) else None
        if not match:
            continue
        found = spends.get((source, character), [])
        first = bisect.bisect_left(found, (moment - MERCHANT_LINE_SECONDS,))
        last = bisect.bisect_left(found, (moment + MERCHANT_LINE_SECONDS + 1,))
        near = [(abs(moment - t), t > moment, t, i) for t, i in found[first:last]]
        if not near:
            continue
        _, _, spent_at, balance = min(near)  # The nearest, and on a tie the spend before the line.
        if balance in owner:
            buy = unresolved[owner[balance]]
            buy["time"] = max(buy["time"], spent_at)
            buy["lines"].append((int(match.group(1)), match.group(2), int(match.group(3) or 1)))
    return [(buy["time"], buy["lines"][0][0], buy["lines"][0][1], sum(q for _, _, q in buy["lines"]), buy["cost"])
            for buy in unresolved
            if buy["lines"] and len({i for i, _, _ in buy["lines"]}) == 1 and buy["lines"][0][1]]


@_once
def _stock_snapshots(db):
    """Where every snapshot of a place that keeps items sits, without its rows:
    [(character, place, time, source, sequence, ID)]. Snapshots are most of a ledger, so
    they are gone through once here and afterwards only the few needed are read."""
    return db.execute(
        "SELECT character, json_extract(data,'$.location') AS place, time, source_id, sequence, id FROM events "
        f"WHERE kind='snapshot' AND place IN ({','.join('?' * len(STOCK_PLACES))})", STOCK_PLACES).fetchall()


def _stock_at(db, end):
    """Units held at a moment, from each character's latest snapshot of every place that
    keeps items: a list of (item as found in the row, place, units).

    Bags, bank, mailbox and auctions still up count; worn gear doesn't. An auction that
    sold is waiting for its money, so its item is gone. Returns None when no character
    had any of these places on record by then.
    """
    latest = {}  # (character, place) -> (time, source, sequence, ID) of its last snapshot by then
    for character, place, *found in _stock_snapshots(db):
        if found[0] <= end and tuple(found) > latest.get((character, place), ()):
            latest[(character, place)] = tuple(found)
    if not latest:
        return None
    held = []
    for *_, event_id in latest.values():
        d = json.loads(db.execute("SELECT data FROM events WHERE id=?", (event_id,)).fetchone()[0])
        place = d.get("location")
        for row in d.get("rows") or []:
            if place == "auctions" and row.get("status") not in (None, 0):
                continue
            # A mail holds a list of items; every other place holds one per row.
            for entry in (row.get("items") or []) if place == "mail" else [row]:
                held.append((entry.get("item") or {}, place, entry.get("quantity") or 0))
    return held


class ItemLedger:
    """Each item's sales, purchases, loot and crafts over all recorded history, by name.

    Names group the records, as in the auction figure, because a sale read from mail
    often has no item ID. Loot and crafts come from the recording character's own chat
    lines, so another player's loot is never counted. A bid the auction house sent back
    is not a purchase.
    """

    def __init__(self, db):
        self.db = db
        self.names = _names_by_id(db)
        self.ids = {name: item_id for item_id, name in self.names.items()}
        self.records, self._bag_cache, self._recipes, self._costs, self._stock, self._uses = {}, {}, {}, {}, {}, {}
        self._bag_index = None
        refunds = []
        activities = _activities(db)
        posted = _postings(db)
        for moment, d, _ in activities:
            category, item = d.get("category"), d.get("item") or {}
            name = self._name(item)
            if category == "auction_deposit" and name:
                units = d.get("quantity") or posted.get(d.get("auctionKey"), {}).get("quantity") or None
                self._record(name, item)["listed"].append({"time": moment, "deposit": -(d.get("amount") or 0),
                                                           "units": units})
            elif category in ITEM_SOLD and name:
                if category == "auction_sale":
                    commission = d.get("commission") or 0
                    revenue = (d["gross"] - commission if d.get("gross") is not None
                               else (d.get("amount") or 0) - (d.get("depositRefund") or 0))
                    gross = revenue + commission
                else:
                    gross = revenue = d.get("amount") or 0
                self._record(name, item)["sold"].append({"time": moment, "kind": ITEM_SOLD[category],
                                                         "quantity": d.get("quantity") or 0, "gross": gross or 0,
                                                         "revenue": revenue})
            elif category in ITEM_BOUGHT and name:
                self._record(name, item)["bought"].append({"time": moment, "kind": ITEM_BOUGHT[category],
                                                           "quantity": d.get("quantity") or None,
                                                           "cost": -(d.get("amount") or 0)})
            elif (category == "mail_received" and (d.get("amount") or 0) > 0
                  and "Auction House" in (d.get("sender") or "") and (d.get("subject") or "").startswith(OUTBID_PREFIX)):
                refunds.append((moment, d["subject"][len(OUTBID_PREFIX):].strip(), d["amount"]))
        for moment, name, amount in refunds:
            bids = self.records.get(name, {}).get("bought", [])
            bid = next((b for b in bids if b["kind"] == "auction" and b["cost"] == amount and b["time"] <= moment
                        and not b.get("refunded")), None)
            if bid:
                bid["refunded"] = True
        for record in self.records.values():
            record["bought"] = [b for b in record["bought"] if not b.get("refunded")]
        for moment, item_id, name, quantity, cost in _unrecorded_vendor_buys(db):
            self._record(name, {"id": item_id})["bought"].append(
                {"time": moment, "kind": "vendor", "quantity": quantity, "cost": cost, "inferred": True})
        for moment, copper, _, item, units in _lost_listing_fees(db, activities):
            name = self._name(item)
            if name:
                self._record(name, item)["unsold"].append({"time": moment, "fee": copper, "units": units})
        for moment, _, item, units in _returned_listings(db, activities):
            name = self._name(item)
            if name:
                self._record(name, item)["returned"].append({"time": moment, "units": units})

        for source, character, sequence, moment, data in db.execute(
                "SELECT source_id,character,sequence,time,data FROM events WHERE kind='loot_message' "
                "ORDER BY time,source_id,sequence"):
            text = json.loads(data).get("text") or ""
            kind = "farmed" if text.startswith(FARMED_PREFIX) else "crafted" if text.startswith(CRAFTED_PREFIX) else None
            match = ITEM_LINK.search(text) if kind else None
            if not match:
                continue
            item_id = int(match.group(1))
            name = match.group(2) or self.names.get(item_id)
            if name:
                self._record(name, {"id": item_id})[kind].append({
                    "time": moment, "quantity": int(match.group(3) or 1),
                    "source": source, "character": character, "sequence": sequence})

    def warm(self):
        """Work out every recipe now, so the first analysis doesn't wait for them."""
        for name, record in self.records.items():
            if record["crafted"]:
                self.recipe(name)

    def _name(self, item):
        name = item.get("name")
        if isinstance(name, str) and name:
            return name
        return self.names.get(_item_id(item.get("id")))

    def _record(self, name, item):
        record = self.records.setdefault(name, dict(self._empty(name), item_id=None))
        record["item_id"] = record["item_id"] or _item_id(item.get("id"))
        return record

    def _empty(self, name):
        return {"item_id": self.ids.get(name), **{key: [] for key in RECORD_KEYS}}

    def name_of(self, item_id):
        return self.names.get(item_id) or f"Item {item_id}"

    def _bags(self, craft, later):
        """The character's bag snapshot just before or after a record: {id, time, counts}, or None."""
        if self._bag_index is None:
            # Where every bag snapshot sits in its log, read once: {(source, character): ([sequence], [id])}.
            self._bag_index = defaultdict(lambda: ([], []))
            bags = sorted((source, sequence, character, event_id) for character, place, _, source, sequence, event_id
                          in _stock_snapshots(self.db) if place == "bags")
            for source, sequence, character, event_id in bags:
                sequences, ids = self._bag_index[(source, character)]
                sequences.append(sequence)
                ids.append(event_id)
        sequences, ids = self._bag_index.get((craft["source"], craft["character"]), ([], []))
        at = (bisect.bisect_right(sequences, craft["sequence"]) if later
              else bisect.bisect_left(sequences, craft["sequence"]) - 1)
        if not 0 <= at < len(ids):
            return None
        event_id = ids[at]
        if event_id not in self._bag_cache:
            # Only each slot's item and count are needed, so SQLite picks them out of the rows.
            counts, moment = Counter(), None
            for moment, item_id, quantity in self.db.execute(
                    "SELECT e.time, json_extract(r.value,'$.item.id'), json_extract(r.value,'$.quantity') "
                    "FROM events e LEFT JOIN json_each(e.data,'$.rows') r WHERE e.id=?", (event_id,)):
                item_id = _item_id(item_id)
                if item_id:
                    counts[item_id] += quantity or 0
            self._bag_cache[event_id] = {"id": event_id, "time": moment, "counts": counts}
        return self._bag_cache[event_id]

    def recipe(self, name):
        """What one craft of an item makes and uses: {makes, reagents: {item ID: count}, seen}.

        The bags just before and just after a run of crafts show what went in. A run counts
        only when the item made is the only thing that arrived and every amount divides
        evenly by the crafts. The recipe seen most often wins, then the latest. None when
        no run was clean.
        """
        if name in self._recipes:
            return self._recipes[name]
        record = self.records.get(name) or self._empty(name)
        product = record["item_id"] or self.ids.get(name)
        runs = {}
        for craft in record["crafted"]:
            before, after = self._bags(craft, later=False), self._bags(craft, later=True)
            if not before or not after or after["time"] - craft["time"] > CRAFT_SNAPSHOT_SECONDS:
                continue
            run = runs.setdefault((before["id"], after["id"]),
                                  {"before": before["counts"], "after": after["counts"], "casts": 0, "made": 0, "time": 0})
            run["casts"] += 1
            run["made"] += craft["quantity"]
            run["time"] = max(run["time"], craft["time"])
        seen, latest = Counter(), {}
        for run in runs.values():
            change = {k: run["after"][k] - run["before"][k] for k in set(run["after"]) | set(run["before"])}
            gained = {k for k, v in change.items() if v > 0}
            used = {k: -v for k, v in change.items() if v < 0}
            casts = run["casts"]
            if gained != {product} or change[product] != run["made"]:
                continue
            if run["made"] % casts or any(v % casts for v in used.values()):
                continue
            found = (run["made"] // casts, tuple(sorted((k, v // casts) for k, v in used.items())))
            seen[found] += 1
            latest[found] = max(latest.get(found, 0), run["time"])
        result = None
        if seen:
            best = max(seen, key=lambda r: (seen[r], latest[r]))
            result = {"makes": best[0], "reagents": dict(best[1]), "seen": seen[best]}
        self._recipes[name] = result
        return result

    def unit_cost(self, name, end, visiting=frozenset()):
        """Average copper per unit gained up to `end`, or None when none was.

        Bought units cost what was paid, farmed ones nothing, and crafted ones what their
        materials cost. A purchase with no quantity on record can't be split into units,
        so it is left out.
        """
        key = (name, end)
        if key in self._costs and not visiting:
            return self._costs[key]
        record = self.records.get(name) or self._empty(name)
        bought = [b for b in record["bought"] if b["time"] <= end and b["quantity"]]
        units = sum(b["quantity"] for b in bought) + sum(f["quantity"] for f in record["farmed"] if f["time"] <= end)
        spent = sum(b["cost"] for b in bought)
        made = sum(c["quantity"] for c in record["crafted"] if c["time"] <= end)
        if made and name not in visiting:
            each = self._materials_each(name, end, visiting | {name})
            if each is not None:
                units += made
                spent += each * made
        result = spent / units if units else None
        if not visiting:
            self._costs[key] = result
        return result

    def _materials_each(self, name, end, visiting):
        recipe = self.recipe(name)
        if not recipe:
            return None
        total = sum((self.unit_cost(self.name_of(item_id), end, visiting) or 0) * count
                    for item_id, count in recipe["reagents"].items())
        return total / recipe["makes"]

    def summary(self, name, start, end):
        """How much of an item moved inside a span, for choosing one."""
        record, inside = self._inside(name, start, end)
        return {"name": name, "item_id": record["item_id"] or self.ids.get(name),
                "sold": sum(r["quantity"] for r in inside["sold"]),
                "revenue": sum(r["revenue"] for r in inside["sold"]),
                "farmed": sum(r["quantity"] for r in inside["farmed"]),
                "crafted": sum(r["quantity"] for r in inside["crafted"]),
                "bought": sum(r["quantity"] or 0 for r in inside["bought"]),
                "purchases": len(inside["bought"]), "listed": len(inside["listed"])}

    def _used_in_crafts(self, start, end):
        """Units of each item used inside a span to craft others: {material: {product: units}}.

        Each product's crafts here use what its recipe says. A product whose recipe was
        never seen says nothing about what it used.
        """
        key = (start, end)
        if key not in self._uses:
            uses = defaultdict(Counter)
            for product, record in self.records.items():
                crafts = sum(1 for c in record["crafted"] if start <= c["time"] <= end)
                recipe = self.recipe(product) if crafts else None
                for item_id, per_craft in (recipe or {}).get("reagents", {}).items():
                    uses[self.name_of(item_id)][product] += per_craft * crafts
            self._uses[key] = uses
        return self._uses[key]

    def _inside(self, name, start, end):
        record = self.records.get(name) or self._empty(name)
        return record, {key: [r for r in record[key] if start <= r["time"] <= end] for key in RECORD_KEYS}

    def analyse(self, name, start, end):
        """Sales, where the item came from, and what it cost, inside a span. Copper throughout.

        Spent is purchases of the item itself plus the materials used by its crafts here,
        each material at its average cost per unit up to the span's end, plus deposits
        kept by the auction house when a listing came back unsold, less the units used
        here to craft other items at that same average cost, as those items count them
        among their materials. Prices are per unit, from auction sales before the
        commission, or vendor sales when there were none.
        """
        record, inside = self._inside(name, start, end)
        sold = inside["sold"]
        auction = [s for s in sold if s["kind"] == "auction" and s["quantity"]]
        priced = auction or [s for s in sold if s["quantity"]]
        prices = [round(s["gross"] / s["quantity"]) for s in priced]
        crafts = inside["crafted"]
        recipe = self.recipe(name) if crafts else None
        reagents = []
        for item_id, per_craft in (recipe or {}).get("reagents", {}).items():
            reagent = self.name_of(item_id)
            used, each = per_craft * len(crafts), self.unit_cost(reagent, end)
            history = self.records.get(reagent) or self._empty(reagent)
            reagents.append({
                "name": reagent, "item_id": item_id, "per_craft": per_craft, "used": used,
                "unit_cost": None if each is None else round(each), "cost": 0 if each is None else round(each * used),
                "bought": sum(b["quantity"] or 0 for b in history["bought"] if b["time"] <= end),
                "farmed": sum(f["quantity"] for f in history["farmed"] if f["time"] <= end),
                "crafted": sum(c["quantity"] for c in history["crafted"] if c["time"] <= end)})
        reagents.sort(key=lambda r: (-r["cost"], r["name"]))
        bought_cost = sum(b["cost"] for b in inside["bought"])
        materials = sum(r["cost"] for r in reagents)
        revenue = sum(s["revenue"] for s in sold)
        unsold, returned = inside["unsold"], inside["returned"]
        fees = sum(u["fee"] or 0 for u in unsold)
        # Units that went into crafting other items are part of those items' cost, so their
        # cost comes off here. It never takes off more than was spent on the item here.
        into = self._used_in_crafts(start, end).get(name, {})
        used_units, each = sum(into.values()), self.unit_cost(name, end) if into else None
        used_value = round(each * used_units) if each is not None else 0
        credited = min(used_value, bought_cost + materials)
        return {
            "name": name, "item_id": record["item_id"] or self.ids.get(name), "start": start, "end": end,
            "sold": {"quantity": sum(s["quantity"] for s in sold), "sales": len(sold), "revenue": revenue,
                     "auction": sum(s["quantity"] for s in sold if s["kind"] == "auction"),
                     "vendor": sum(s["quantity"] for s in sold if s["kind"] == "vendor"),
                     "highest": max(prices) if prices else None, "lowest": min(prices) if prices else None,
                     "price_from": (priced[0]["kind"] if priced else None)},
            "gained": {"farmed": sum(f["quantity"] for f in inside["farmed"]),
                       "crafted": sum(c["quantity"] for c in crafts), "crafts": len(crafts),
                       "bought": sum(b["quantity"] or 0 for b in inside["bought"]),
                       "unknown_purchases": sum(1 for b in inside["bought"] if not b["quantity"]),
                       "inferred_purchases": sum(1 for b in inside["bought"] if b.get("inferred"))},
            "spent": {"bought": bought_cost, "purchases": len(inside["bought"]), "materials": materials,
                      "listing_fees": fees, "used_in_crafts": credited,
                      "total": bought_cost + materials + fees - credited},
            "used": {"units": used_units, "value": used_value, "credited": credited, "unpriced": bool(into) and each is None,
                     "into": [{"name": product, "units": units} for product, units
                              in sorted(into.items(), key=lambda pair: (-pair[1], pair[0]))]},
            "listings": {"listed": len(inside["listed"]), "unsold": len(unsold),
                         "unpriced": sum(1 for u in unsold if u["fee"] is None),
                         "listed_units": sum(r["units"] or 0 for r in inside["listed"]),
                         "listed_unknown": sum(1 for r in inside["listed"] if not r["units"]),
                         "returned": len(returned),
                         "returned_units": sum(r["units"] or 0 for r in returned),
                         "returned_unknown": sum(1 for r in returned if not r["units"])},
            "recipe": None if not recipe else {"makes": recipe["makes"], "seen": recipe["seen"], "reagents": reagents},
            "materials_unknown": bool(crafts) and (not recipe or any(r["unit_cost"] is None for r in reagents)),
            "net": revenue - bought_cost - materials - fees + credited,
            "has_activity": any(inside.values()),
        }

    def compare(self, name, start, end):
        """One item's row in a comparison: profit, units sold and held, margin and how
        listings went.

        Net is as in `analyse`: money in less money out, so stock bought or crafted and not
        yet sold lowers it. Profit on what sold counts only the units sold, each at the
        item's average cost, less deposits kept on unsold listings; the stock held at the
        span's end, valued at that same cost, is what the difference went into. Each sold
        for is the average a unit brought in after the auction house cut, and the margin
        is that less the average cost per unit up to the span's end (see `unit_cost`).
        Listings count units: those put up in the span, and those that came back in it
        (see `_returned_listings`). The sales rate is the share of auction units that sold, of
        those that sold or came back in the span, so a big stack that sold outweighs a
        single one that didn't. None where a figure can't be worked out.
        """
        found = self.analyse(name, start, end)
        sold, listings = found["sold"], found["listings"]
        each = sold["revenue"] / sold["quantity"] if sold["quantity"] else None
        cost = self.unit_cost(name, end)
        margin = None if each is None or cost is None else each - cost
        finished = sold["auction"] + listings["returned_units"]
        places = self.stock(name, end)
        units = None if places is None else sum(places.values())
        fees = found["spent"]["listing_fees"]
        return {
            "name": name, "item_id": found["item_id"], "net": found["net"], "sold": sold["quantity"],
            # What the units sold made over what they cost, less deposits kept on unsold listings.
            "profit_sold": None if cost is None else round(sold["revenue"] - cost * sold["quantity"] - fees),
            "stock": units, "stock_places": places,
            "stock_value": None if units is None or cost is None else round(units * cost),
            "auction_sold": sold["auction"], "revenue": sold["revenue"],
            "each": None if each is None else round(each), "unit_cost": None if cost is None else round(cost),
            "margin": None if margin is None else round(margin),
            "margin_share": None if margin is None or not cost else margin / cost,
            "listed": listings["listed_units"], "auctions": listings["listed"],
            "returned": listings["returned_units"], "returned_auctions": listings["returned"],
            "listed_partial": bool(listings["listed_unknown"]),
            "sales_rate": sold["auction"] / finished if finished else None,
            "spent": found["spent"]["total"], "listing_fees": fees,
            "cost_partial": found["materials_unknown"] or self._cost_partial(name, end),
            "rate_partial": bool(listings["returned_unknown"]),
            "has_activity": found["has_activity"],
        }

    def stock(self, name, end):
        """Units of an item held at `end`, by place ({} when none), or None with no snapshot on record."""
        if end not in self._stock:
            held = _stock_at(self.db, end)
            by_name = None
            if held is not None:
                by_name = defaultdict(Counter)
                for item, place, units in held:
                    found = self._name(item)
                    if found and units > 0:
                        by_name[found][place] += units
            self._stock[end] = by_name
        by_name = self._stock[end]
        if by_name is None:
            return None
        places = by_name.get(name, {})
        return {place: places[place] for place in STOCK_PLACES if places.get(place)}

    def _cost_partial(self, name, end):
        """Whether an item's unit cost leaves out purchases or crafts it couldn't price."""
        record = self.records.get(name) or self._empty(name)
        if any(not b["quantity"] for b in record["bought"] if b["time"] <= end):
            return True
        crafted = any(c["time"] <= end for c in record["crafted"])
        return crafted and self._materials_each(name, end, frozenset({name})) is None


def item_ledger(db):
    """The item ledger of this database, built once per `Reader.memo`."""
    memo = getattr(db, "memo", None)
    if memo is None:
        return ItemLedger(db)
    if "item_ledger" not in memo:
        memo["item_ledger"] = ItemLedger(db)
    items = memo["item_ledger"]
    items.db = db  # The connection it was built on is closed by now.
    return items


# What every figure needs from the whole ledger, slowest last, each called with a `Reader`
# to have it ready ahead of the first request.
WARMERS = (windows, _characters, _stock_snapshots, lambda db: item_ledger(db).warm(), _item_names)


def item_figure(db, window, name=None):
    """One item's analysis inside a window, and the items worth choosing from.

    Items are offered by what they sold for, then by how many moved. With no name, the
    first of them is analysed.
    """
    items = item_ledger(db)
    start, end = window["start"], window["end"]
    choices = _item_choices(items, start, end)
    name = name or (choices[0]["name"] if choices else None)
    return {"window": window, "choices": choices, "item": items.analyse(name, start, end) if name else None}


def _item_choices(items, start, end):
    choices = [items.summary(item, start, end) for item in items.records]
    choices = [c for c in choices if c["sold"] or c["farmed"] or c["crafted"] or c["purchases"] or c["listed"]]
    choices.sort(key=lambda c: (-c["revenue"], -(c["sold"] + c["farmed"] + c["crafted"] + c["bought"]), c["name"]))
    return choices[:MAX_ITEM_CHOICES]


def compare_figure(db, window, names=None):
    """Several items side by side inside a window, in the order given, and the items
    worth choosing from. With names None, none chosen yet, the best three sellers are
    compared. Blank names are left out, so [""] compares nothing."""
    items = item_ledger(db)
    start, end = window["start"], window["end"]
    choices = _item_choices(items, start, end)
    if names is None:
        chosen = [c["name"] for c in choices[:3]]
    else:
        chosen = list(dict.fromkeys(n for n in names if n))[:MAX_COMPARED_ITEMS]
    return {"window": window, "choices": choices, "limit": MAX_COMPARED_ITEMS,
            "items": [items.compare(name, start, end) for name in chosen]}


def default_periods(db, window_id):
    """Two windows to compare an item across, starting from an episode's window: the
    window of the same kind just before it, then it. Everything has nothing before it,
    so the last two markers are compared, or else the last two days. Fewer than two
    windows of a kind gives what there is."""
    found = windows(db)
    current = next((w for w in found if w["id"] == window_id), None)
    if current and current["kind"] != "all":
        earlier = [w for w in found if w["kind"] == current["kind"] and w["start"] < current["start"]]
        before = max(earlier, key=lambda w: w["start"], default=None)
        return [w for w in (before, current) if w]
    for kind in ("marker", "day"):
        same = sorted((w for w in found if w["kind"] == kind), key=lambda w: w["start"])
        if len(same) >= 2:
            return same[-2:]
    return [w for w in found if w["kind"] == "all"]


def periods_figure(db, periods, name=None):
    """One item in two windows side by side, earliest first, and the items worth choosing
    from, which are those with activity in either. With no name, the first of them."""
    items = item_ledger(db)
    periods = sorted(periods, key=lambda w: (w["start"], w["end"]))
    choices = _item_choices(items, min(w["start"] for w in periods), max(w["end"] for w in periods))
    name = name or (choices[0]["name"] if choices else None)
    rows = [dict(items.compare(name, w["start"], w["end"]), window=w) for w in periods] if name else []
    return {"windows": periods, "choices": choices, "name": name, "items": rows}


TOP_ITEMS = 6


def top_items(db, window, limit=TOP_ITEMS):
    """The items that sold the most units, made the most and lost the most inside a window.

    Sales are ranked by units sold, then by what they brought in after the auction house
    cut (`revenue`). Profit and loss are the item's net as in `ItemLedger.analyse`. Each
    row has all three, and appears in every list it makes. Items with no known ID are left
    out, as a card can't show them.
    """
    items = item_ledger(db)
    start, end = window["start"], window["end"]
    rows = []
    for choice in _item_choices(items, start, end):
        found = items.analyse(choice["name"], start, end)
        if found["item_id"]:
            rows.append({"name": found["name"], "item_id": found["item_id"], "sold": found["sold"]["quantity"],
                         "revenue": found["sold"]["revenue"], "net": found["net"]})
    return {
        "window": window,
        "sales": sorted((r for r in rows if r["sold"] > 0), key=lambda r: (-r["sold"], -r["revenue"], r["name"]))[:limit],
        "profit": sorted((r for r in rows if r["net"] > 0), key=lambda r: (-r["net"], r["name"]))[:limit],
        "loss": sorted((r for r in rows if r["net"] < 0), key=lambda r: (r["net"], r["name"]))[:limit],
    }


def highlights(db, window):
    """Moments marked in game to find in the recording, oldest first, inside the window.

    Each is numbered and timed like the addon shows it: within the marker running on
    its own account, or within its local day when none was. A removed one is left out.
    """
    removed = {row[0] for row in db.execute(
        "SELECT json_extract(data,'$.highlightID') FROM events WHERE kind='highlight_removed'")}
    markers, counts, result = {}, {}, []
    for event_id, source, character, moment, kind, data in db.execute(
            "SELECT id,source_id,character_name,time,kind,data FROM events "
            "WHERE kind IN ('episode_start','episode_end','highlight') ORDER BY source_id,sequence"):
        d = json.loads(data)
        if kind == "episode_start":
            # A linked account's earlier start of the running marker moves its start back.
            name, began, running = d.get("name") or "Unnamed marker", d.get("occurredAt") or moment, markers.get(source)
            if running and running[0] == name:
                markers[source] = (name, min(running[1], began), running[2])
            else:
                markers[source] = (name, began, event_id)
        elif kind == "episode_end":
            markers.pop(source, None)
        elif event_id not in removed:
            marker = markers.get(source)
            group = (source, "marker", marker[2]) if marker else (
                source, "day", datetime.datetime.fromtimestamp(moment).date())
            counts[group] = counts.get(group, 0) + 1
            if window["start"] <= moment <= window["end"]:
                result.append({"time": moment, "number": counts[group], "note": d.get("note"),
                               "zone": d.get("zone"), "subzone": d.get("subzone"), "character": character,
                               "marker": marker[0] if marker else None,
                               "since": moment - marker[1] if marker else None})
    result.sort(key=lambda h: h["time"])
    return result


def figures(db, window_id, chart_range):
    window = resolve_window(db, window_id)
    return {"window": window, "range": chart_range, "start": start_figure(db, window),
            "auction": auction_figure(db, window, chart_range), "value": value_figure(db, window, chart_range),
            "costs": cost_figure(db, window), "revenue": revenue_figure(db, window), "highlights": highlights(db, window)}
