"""Import Forever Ledger JSON exports or WoW SavedVariables. Python 3.10+, stdlib only.

Never executes Lua. The SavedVariables reader accepts only literal tables, strings,
numbers, booleans and nil. Imports are transactional and duplicate-safe.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import time
from pathlib import Path


class LuaReader:
    whitespace = re.compile(r"\s+|--[^\n]*(?:\n|$)")
    assignment = re.compile(r"([A-Za-z_]\w*)\s*=")
    number = re.compile(r"-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")

    def __init__(self, text):
        self.text, self.pos = text, 0

    def space(self):
        while self.pos < len(self.text):
            m = self.whitespace.match(self.text, self.pos)
            if not m:
                return
            self.pos += len(m[0])

    def take(self, token):
        self.space()
        if self.text.startswith(token, self.pos):
            self.pos += len(token)
            return True
        return False

    def need(self, token):
        if not self.take(token):
            raise ValueError(f"Expected {token!r} at character {self.pos}")

    def string(self):
        quote = self.text[self.pos]
        self.pos += 1
        out = []
        escapes = {"n": "\n", "r": "\r", "t": "\t", "a": "\a", "b": "\b", "f": "\f", "v": "\v"}
        while self.pos < len(self.text):
            char = self.text[self.pos]
            self.pos += 1
            if char == quote:
                return b"".join(out).decode("utf-8")
            if char == "\\":
                if self.pos >= len(self.text):
                    break
                char = self.text[self.pos]
                self.pos += 1
                if char.isdigit():
                    digits = char
                    for _ in range(2):
                        if self.pos < len(self.text) and self.text[self.pos].isdigit():
                            digits += self.text[self.pos]
                            self.pos += 1
                    out.append(bytes([int(digits)]))
                elif char in escapes:
                    out.append(escapes[char].encode("utf-8"))
                elif char in ("\\", "'", '"', "\n"):
                    out.append(char.encode("utf-8"))
                else:
                    raise ValueError(f"Unsupported Lua escape \\{char}")
            else:
                out.append(char.encode("utf-8"))
        raise ValueError("Unterminated Lua string")

    def value(self, depth=0):
        if depth > 50:
            raise ValueError("SavedVariables nesting too deep")
        self.space()
        if self.pos >= len(self.text):
            raise ValueError("Unexpected end of SavedVariables")
        if self.text[self.pos] in ('"', "'"):
            return self.string()
        if self.take("{"):
            result, index = {}, 1
            while not self.take("}"):
                if self.take("["):
                    key = self.value(depth+1)
                    self.need("]")
                    self.need("=")
                    value = self.value(depth+1)
                else:
                    self.space()
                    m = self.assignment.match(self.text, self.pos)
                    if m:
                        self.pos += len(m[0])
                        key, value = m[1], self.value(depth+1)
                    else:
                        key, value = index, self.value(depth+1)
                        index += 1
                if not isinstance(key, (str, int)):
                    raise ValueError("Unsupported table key")
                if key in result:
                    raise ValueError("Duplicate table key")
                result[key] = value
                if not self.take(",") and not self.take(";"):
                    self.need("}")
                    break
            if result and set(result) == set(range(1, len(result)+1)):
                return [result[i] for i in range(1, len(result)+1)]
            return result
        self.space()
        m = self.number.match(self.text, self.pos)
        if m:
            self.pos += len(m[0])
            number = float(m[0])
            return int(number) if number.is_integer() else number
        for word, value in (("true", True), ("false", False), ("nil", None)):
            if self.take(word):
                return value
        raise ValueError(f"Non-literal Lua at character {self.pos}; no code will be executed")

    def read(self):
        self.need("ForeverLedgerDB")
        self.need("=")
        result = self.value()
        self.space()
        if self.pos != len(self.text):
            raise ValueError("Unexpected content after ForeverLedgerDB")
        return result


def sequence(value):
    if value == {} or value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Expected an array")
    return value


def read_export(path):
    text = Path(path).read_text(encoding="utf-8-sig")
    obj = LuaReader(text).read() if text.lstrip().startswith(("ForeverLedgerDB", "--")) else json.loads(text)
    if obj.get("schema") != 1 or not isinstance(obj.get("sourceID"), str):
        raise ValueError("Unsupported or missing schema/sourceID")
    obj["events"] = sequence(obj.get("events"))
    return obj


def connect(path):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.executescript("""
    CREATE TABLE IF NOT EXISTS events (
      id TEXT PRIMARY KEY, source_id TEXT NOT NULL, sequence INTEGER NOT NULL,
      character TEXT NOT NULL, character_name TEXT NOT NULL, realm TEXT NOT NULL,
      time INTEGER NOT NULL, episode TEXT, kind TEXT NOT NULL, data TEXT NOT NULL,
      raw TEXT NOT NULL, UNIQUE(source_id, sequence));
    CREATE INDEX IF NOT EXISTS events_kind_time ON events(kind,time);
    CREATE TABLE IF NOT EXISTS sources (
      source_id TEXT PRIMARY KEY, label TEXT, last_sequence INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS owners (name TEXT PRIMARY KEY);
    DROP VIEW IF EXISTS cash_movements;
    CREATE VIEW cash_movements AS
      SELECT id,source_id,character_name,time,episode,
        json_extract(data,'$.delta') AS copper,
        json_extract(data,'$.before') AS balance_before,
        json_extract(data,'$.after') AS balance_after FROM events WHERE kind='balance'
        AND id NOT IN (SELECT json_extract(data,'$.balanceID') FROM events WHERE kind='balance_correction');
    CREATE VIEW IF NOT EXISTS activities AS
      SELECT id,source_id,character_name,time,episode,
        json_extract(data,'$.category') AS category,
        json_extract(data,'$.amount') AS copper,
        json_extract(data,'$.confidence') AS confidence,data FROM events WHERE kind='activity';
    CREATE VIEW IF NOT EXISTS reconciliation AS
      SELECT id,source_id,character_name,time,episode,
        json_extract(data,'$.observed') AS observed,
        json_extract(data,'$.explained') AS explained,
        json_extract(data,'$.residual') AS residual,data FROM events WHERE kind='reconciliation';
    CREATE VIEW IF NOT EXISTS auction_sales AS
      SELECT id,source_id,character_name,time,episode,
        json_extract(data,'$.item.id') AS item_id,
        json_extract(data,'$.item.name') AS item_name,
        json_extract(data,'$.quantity') AS quantity,
        json_extract(data,'$.gross') AS gross,
        json_extract(data,'$.commission') AS commission,
        json_extract(data,'$.depositRefund') AS deposit_refund,
        json_extract(data,'$.auctionKey') AS auction_key,
        json_extract(data,'$.matchConfidence') AS match_confidence,data
        FROM events WHERE kind='auction_sale';
    CREATE VIEW IF NOT EXISTS auction_outcomes AS
      SELECT id,source_id,character_name,time,
        json_extract(data,'$.auctionKey') AS auction_key,
        json_extract(data,'$.outcome') AS outcome,
        json_extract(data,'$.depositLost') AS deposit_lost,
        json_extract(data,'$.confidence') AS confidence,data
        FROM events WHERE kind='auction_outcome';
    CREATE VIEW IF NOT EXISTS snapshots AS
      SELECT id,source_id,character_name,time,
        json_extract(data,'$.location') AS location,
        json_extract(data,'$.complete') AS complete,data
        FROM events WHERE kind='snapshot';
    CREATE VIEW IF NOT EXISTS valuations AS
      SELECT id,source_id,time,episode,json_extract(data,'$.scope') AS scope,
        json_extract(data,'$.gold') AS gold,json_extract(data,'$.assets') AS assets,
        json_extract(data,'$.equipped') AS equipped,json_extract(data,'$.total') AS total,
        json_extract(data,'$.unpricedRows') AS unpriced_rows,data
        FROM events WHERE kind='valuation';
    CREATE VIEW IF NOT EXISTS prices AS
      SELECT id,source_id,time,json_extract(data,'$.scope') AS scope,
        json_extract(data,'$.key') AS item_key,json_extract(data,'$.quote.price') AS unit_price,
        json_extract(data,'$.quote.updatedAt') AS updated_at,
        json_extract(data,'$.quote.source') AS price_source,data
        FROM events WHERE kind='price';
    DROP VIEW IF EXISTS highlights;
    CREATE VIEW highlights AS
      SELECT id,source_id,character_name,time,episode,
        json_extract(data,'$.note') AS note,json_extract(data,'$.zone') AS zone,
        json_extract(data,'$.subzone') AS subzone FROM events WHERE kind='highlight'
        AND id NOT IN (SELECT json_extract(data,'$.highlightID') FROM events
          WHERE kind='highlight_removed' AND json_extract(data,'$.highlightID') IS NOT NULL);
    """)
    return db


def import_file(db, path, export=None):
    """Import one export. A caller that already parsed the file can pass it as `export`."""
    obj = export if export is not None else read_export(path)
    added = 0
    highest = max((e["sequence"] for e in obj["events"]), default=0)
    with db:
        for e in obj["events"]:
            if e.get("schema") != 1 or e.get("sourceID") != obj["sourceID"]:
                raise ValueError("Event schema/source differs from export")
            if type(e.get("sequence")) is not int or e["sequence"] < 1 or e.get("id") != f'{obj["sourceID"]}:{e["sequence"]}':
                raise ValueError("Invalid event ID/sequence")
            raw = json.dumps(e, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            old = db.execute("SELECT raw FROM events WHERE id=?", (e["id"],)).fetchone()
            if old:
                if old[0] != raw:
                    raise ValueError(f'Conflicting contents for {e["id"]}; import rolled back')
                continue
            db.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                e["id"],e["sourceID"],e["sequence"],e["character"],e["characterName"],
                e["realm"],e["time"],e.get("episode"),e["kind"],
                json.dumps(e["data"],ensure_ascii=False),raw))
            added += 1
        db.execute("""INSERT INTO sources VALUES(?,?,?) ON CONFLICT(source_id) DO UPDATE SET
            label=CASE WHEN excluded.last_sequence>=sources.last_sequence THEN excluded.label ELSE sources.label END,
            last_sequence=MAX(sources.last_sequence,excluded.last_sequence)""",
            (obj["sourceID"],obj.get("accountLabel"),highest))
        for name, owned in obj.get("owners", {}).items():
            if owned:
                db.execute("INSERT OR IGNORE INTO owners VALUES(?)",(name,))
        for e in obj["events"]:
            db.execute("INSERT OR IGNORE INTO owners VALUES(?)",(e["characterName"],))
    return added


def character_key(name):
    """The character a recorded name points to. Forever mail and trade names add a surname
    ("Setha Bank") and the recording character's hidden realm, which is often not the
    other character's, so only the first name identifies it."""
    return name.split("-", 1)[0].strip().split(" ", 1)[0].casefold()


def owned_keys(db):
    return {character_key(r[0]) for r in db.execute("SELECT name FROM owners")}


def all_events(db):
    return [json.loads(r[0]) for r in db.execute("SELECT raw FROM events ORDER BY time,source_id,sequence")]


def report(db, costs=None):
    events = all_events(db)
    owners = owned_keys(db)
    balances, snapshots, items, unresolved, login_gaps = {}, {}, {}, [], []
    unmatched_returns, diagnostics = [], []
    valuations = {}
    net, transfers, external_in, external_out, storage_transfers = 0, 0, 0, 0, 0
    attempts, outcomes, sales, cancel_fees = {}, {}, [], []
    def item_row(item):
        key = str(item.get("id")) if item.get("id") else "name:"+str(item.get("name", "unknown"))
        return items.setdefault(key, {"item_key":key,"name":item.get("name"),"listings":0,
            "sold_quantity":0,"gross":0,"commission":0,"cancellation_fees":0,"deposits_forfeited":0,
            "allocated_deposits_forfeited":0,"purchase_spend":0,"unmatched_sales":0})
    corrected = {e["data"]["balanceID"] for e in events if e["kind"]=="balance_correction"}
    # Backfilled corrections are appended; the record they cancel stays in the log.
    voided = {e["data"][key] for e in events if e["kind"]=="activity"
        for key in ("correctsActivityID","correctsSaleID") if e["data"].get(key)}
    backfilled = {i for e in events if e["kind"]=="mail_backfill" and e["data"].get("status")=="applied"
        for i in sequence(e["data"].get("reconciliationIDs"))}
    for e in events:
        d,k=e["data"],e["kind"]
        character=(e["sourceID"],e["character"])
        if k=="baseline":
            balances[character]={"character":e["characterName"],"balance":d["balance"],"time":e["time"]}
            if d.get("gap"):
                login_gaps.append({"event":e["id"],"gap":d["gap"]})
        elif k=="balance" and e["id"] in corrected:
            pass
        elif k=="balance":
            net += d["delta"]
            balances[character]={"character":e["characterName"],"balance":d["after"],"time":e["time"]}
        elif k=="activity" and (e["id"] in voided or d.get("correctsActivityID")):
            pass
        elif k=="activity":
            peer=d.get("counterparty") or d.get("sender") or d.get("recipient")
            internal=d["category"] in ("trade","mail_received","mail_sent") and peer and character_key(peer) in owners
            if internal:
                transfers += d["amount"]
            elif d["category"] in ("bank_deposit","bank_withdrawal"):
                storage_transfers += d["amount"]
            elif d["category"]=="trade" and "moneyIn" in d and "moneyOut" in d:
                external_in += d["moneyIn"]
                external_out += d["moneyOut"]
            else:
                # These are classified cash movements, not economic revenue:
                # AH collection includes refunded deposits.
                if d["amount"]>0: external_in+=d["amount"]
                else: external_out-=d["amount"]
            if d["category"] in ("vendor_purchase","vendor_buyback") and d.get("item"):
                item_row(d["item"])["purchase_spend"]+=-d["amount"]
            if d["category"]=="auction_cancel_fee":
                cancel_fees.append(d)
        elif k=="reconciliation" and d["residual"] and not corrected.intersection(d["balanceIDs"]) and e["id"] not in backfilled:
            unresolved.append({"event":e["id"],"residual":d["residual"]})
        elif k=="snapshot":
            snapshots[character+(d["location"],)]=e
        elif k=="valuation":
            valuations[(e["sourceID"],d["scope"])]=dict(source_id=e["sourceID"],time=e["time"],**d)
        elif k=="auction_posted":
            attempts[d["key"]]=e
            item_row(d.get("item") or {})["listings"]+=1
        elif k=="auction_outcome":
            outcomes[d["auctionKey"]]=e
            if d.get("depositLost") is not None:
                row=item_row(d.get("item") or {})
                field="deposits_forfeited" if d["confidence"]=="server_id" else "allocated_deposits_forfeited"
                row[field]+=d["depositLost"]
        elif k=="auction_sale":
            if e["id"] not in voided: sales.append(e)
        elif k=="auction_return" and not d.get("auctionKey"):
            unmatched_returns.append({"event":e["id"],"item":d.get("item"),"failure":d.get("failure")})
        elif k in ("diagnostic","capability_missing"):
            diagnostics.append({"event":e["id"],"kind":k,"details":d})
        elif k=="auction_purchase_invoice":
            item_row(d.get("item") or {})["purchase_spend"]+=d.get("gross") or 0
    # A sale invoice often has only an item name; resolve through the allocated posting.
    for d in cancel_fees:
        post=attempts.get(d.get("auctionKey"))
        item_row((post["data"].get("item") if post else None) or {})["cancellation_fees"]+=-d["amount"]
    for e in sales:
        d=e["data"]
        post=attempts.get(d.get("auctionKey"))
        item=(post["data"].get("item") if post else None) or d.get("item") or {}
        row=item_row(item)
        row["gross"]+=d.get("gross") or 0
        row["commission"]+=d.get("commission") or 0
        row["sold_quantity"]+=d.get("quantity") or 0
        if not post: row["unmatched_sales"]+=1
    for row in items.values():
        row["margin_before_acquisition"]=row["gross"]-row["commission"]-row["cancellation_fees"]-row["deposits_forfeited"]-row["allocated_deposits_forfeited"]
        row["selling_costs_exceed_revenue"]=row["margin_before_acquisition"]<0
        unit_cost=(costs or {}).get(row["item_key"])
        row["profit_at_supplied_unit_cost"]=(row["margin_before_acquisition"]-unit_cost*row["sold_quantity"]) if unit_cost is not None else None
    inventory=[]
    for _, e in snapshots.items():
        d=e["data"]
        summary={"character":e["characterName"],"location":d["location"],"time":e["time"],
            "complete":d["complete"],"vendor_value":0,"market_value":0,"unpriced_rows":0,
            "active_asking_value":0,"sold_awaiting_delivery_gross":0,"mail_money":0,
            "estimated_net_value":0,"rows":d["rows"]}
        for r in sequence(d["rows"]):
            if d["location"]=="auctions":
                field="active_asking_value" if r.get("status")==0 else "sold_awaiting_delivery_gross"
                summary[field]+=r.get("totalBuyout") or r.get("bid") or 0
            elif d["location"]=="mail":
                summary["mail_money"]+=r.get("money",0)
                for attachment in sequence(r.get("items")):
                    item=attachment.get("item",{})
                    summary["vendor_value"]+=(item.get("vendorPrice") or 0)*attachment.get("quantity",0)
                    if item.get("marketPrice") is not None:
                        summary["market_value"]+=item["marketPrice"]*attachment.get("quantity",0)
                    else:
                        summary["unpriced_rows"]+=1
            else:
                item=r.get("item",{})
                summary["vendor_value"]+=(item.get("vendorPrice") or 0)*r.get("quantity",0)
                if r.get("valuation") is not None:
                    value=r["valuation"]
                    summary["estimated_net_value"]+=value["value"]*r.get("quantity",0)
                    summary["market_value"]+=value.get("marketGross",0)*r.get("quantity",0)
                    if value.get("partial"): summary["unpriced_rows"]+=1
                elif item.get("marketPrice") is not None:
                    summary["market_value"]+=item["marketPrice"]*r.get("quantity",0)
                else:
                    summary["unpriced_rows"]+=1
        inventory.append(summary)
    unresolved_deposits=sum((e["data"].get("deposit") or 0) for key,e in attempts.items() if key not in outcomes)
    missing_sequences=[]
    for source, count, highest in db.execute("SELECT source_id,COUNT(*),MAX(sequence) FROM events GROUP BY source_id"):
        if count!=highest: missing_sequences.append({"source":source,"imported":count,"highest":highest})
    return {"currency":"copper","record_count":len(events),"observed_net_gold":net,
        "classified_external_cash_in":external_in,"classified_external_cash_out":external_out,
        "internal_transfer_net":transfers,"bank_wallet_transfer_net":storage_transfers,"balances":list(balances.values()),
        "unresolved_reconciliation":unresolved,"login_gaps":login_gaps,"incomplete_imports":missing_sequences,
        "unmatched_auction_returns":unmatched_returns,"collector_diagnostics":diagnostics,
        "deposits_without_matched_outcome":unresolved_deposits,
        "items":list(items.values()),"latest_snapshots":inventory,"latest_valuations":list(valuations.values()),
        "notes":["Gold changes and activities are two views of the same money; do not add them together.",
            "Internal-transfer net may be nonzero for gold in transit or missing account exports.",
            "Snapshot values are last observed and may overlap after movements; do not sum into exact net worth.",
            "Item margins cover captured history and allocated failures, before acquisition cost unless supplied.",
            "Purchase spend is not cost of goods sold: some purchased stock may still be held.",
            "Mail and sold-auction snapshots can describe the same proceeds; do not add both."]}


def export_csv(db, folder):
    folder=Path(folder)
    folder.mkdir(parents=True,exist_ok=True)
    for view in ("events","cash_movements","activities","reconciliation","auction_sales","auction_outcomes","snapshots","valuations","prices","highlights"):
        cursor=db.execute(f"SELECT * FROM {view}")
        with (folder/(view+".csv")).open("w",encoding="utf-8",newline="") as out:
            writer=csv.writer(out)
            writer.writerow([c[0] for c in cursor.description])
            writer.writerows(cursor)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files",nargs="*",help=".json exports or account SavedVariables/ForeverLedger.lua files")
    parser.add_argument("--db",default="forever-ledger.sqlite")
    parser.add_argument("--report",help="Write JSON report")
    parser.add_argument("--csv",help="Export SQL tables/views to this folder")
    parser.add_argument("--unit-costs",help='Optional JSON map of item ID -> copper per unit, e.g. {"2447":100}')
    parser.add_argument("--watch",action="store_true",help="Reimport files when WoW saves them; stop with Ctrl+C")
    args=parser.parse_args()
    costs=json.loads(Path(args.unit_costs).read_text(encoding="utf-8-sig")) if args.unit_costs else None
    db=connect(args.db)
    mtimes={}
    changed=True
    try:
        while True:
            for filename in args.files:
                try:
                    stamp=Path(filename).stat().st_mtime_ns
                    if mtimes.get(filename)==stamp:
                        continue
                    added=import_file(db,filename)
                    mtimes[filename]=stamp
                    changed=changed or added>0
                    print(f"{filename}: {added} new records")
                except (OSError,ValueError,KeyError,sqlite3.Error) as err:
                    if not args.watch: raise
                    print(f"Waiting for complete saved file: {filename}: {err}")
            if not changed:
                time.sleep(5)
                continue
            changed=False
            result=report(db,costs)
            if args.report:
                Path(args.report).write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf-8")
            if args.csv: export_csv(db,args.csv)
            if not args.watch:
                print(f"{result['record_count']} records; {len(result['unresolved_reconciliation'])} unresolved windows; "
                      f"{len(result['incomplete_imports'])} incomplete sources")
                break
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    finally:
        db.close()


if __name__=="__main__":
    main()
