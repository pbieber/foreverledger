"""Deterministic made-up ledger export, in the addon's real format.

It goes through the same importer as real data, so charts can be designed before
Forever data exists. Nothing here describes real results.
"""
from __future__ import annotations

import datetime
import random
from collections import Counter

SOURCE_ID = "Mock-Main:1:1"
REALM = "Mock"
SCOPE = "forever:Mock:Alliance"
MAIN = ("Player-Mock-Main", "Goldrun-Mock")
BANK = ("Player-Mock-Bank", "Mockbank-Mock")
ITEMS = ["Linen Cloth", "Wool Cloth", "Silk Cloth", "Copper Bar", "Tin Bar", "Iron Bar", "Light Leather",
         "Medium Leather", "Peacebloom", "Silverleaf", "Mageroyal", "Briarthorn", "Minor Healing Potion"]
LINEN = {"id": 2589, "name": "Linen Cloth"}
BOLT = {"id": 2996, "name": "Bolt of Linen Cloth"}
THREAD = {"id": 2320, "name": "Coarse Thread"}
LINEN_BAG = {"id": 4238, "name": "Linen Bag"}


def chat_link(item, quantity=1):
    count = f"x{quantity}" if quantity > 1 else ""
    return f"|cffffffff|Hitem:{item['id']}::::::::20::::::::::|h[{item['name']}]|h|r{count}."


def build_export(seed=7):
    rng = random.Random(seed)
    events = []

    def emit(kind, data, moment, character=MAIN, episode=None):
        sequence = len(events) + 1
        event = {"schema": 1, "sourceID": SOURCE_ID, "sequence": sequence, "id": f"{SOURCE_ID}:{sequence}",
                 "character": character[0], "characterName": character[1], "realm": REALM, "time": int(moment),
                 "kind": kind, "data": data}
        if episode:
            event["episode"] = episode
        events.append(event)
        return event

    gold, bank_gold, stock = 0, 0, 0
    day_one = datetime.datetime(2026, 11, 5, 18, 0)
    emit("baseline", {"balance": 0}, day_one.timestamp() - 60)
    emit("baseline", {"balance": 0}, day_one.timestamp() - 50, BANK)

    def valuation(moment, episode):
        emit("valuation", {"scope": SCOPE, "gold": gold + bank_gold, "assets": stock, "equipped": 900 + stock // 40,
                           "total": gold + bank_gold + stock + 900 + stock // 40, "unpricedRows": rng.randint(0, 2),
                           "estimate": True, "model": "mock", "commissionBps": 500}, moment, episode=episode)

    def spend_or_earn(category, amount, moment, episode, **details):
        nonlocal gold
        before, gold = gold, gold + amount
        emit("balance", {"before": before, "after": gold, "delta": amount}, moment, episode=episode)
        if category:
            emit("activity", {"category": category, "amount": amount, "confidence": "mock", **details},
                 moment, episode=episode)

    # Tailoring, with the bag snapshots the addon writes as bags change, so recipes can be
    # read from them. It draws nothing random, so the rest of the history stays as it was.
    bags = Counter()

    def bag_snapshot(moment, episode):
        rows = [{"item": {"id": item_id}, "quantity": count} for item_id, count in sorted(bags.items()) if count > 0]
        emit("snapshot", {"location": "bags", "rows": rows}, moment, episode=episode)

    def gain(prefix, item, quantity, moment, episode):
        emit("loot_message", {"text": f"{prefix}{chat_link(item, quantity)}"}, moment, episode=episode)
        bags[item["id"]] += quantity
        bag_snapshot(moment + 1, episode)

    def tailoring(day, moment, episode):
        spend_or_earn("auction_purchase", -10 * (260 + 25 * day), moment, episode, item=LINEN, quantity=10)
        gain("You receive item: ", LINEN, 10, moment + 1, episode)
        moment += 10
        for _ in range(min(9, bags[LINEN["id"]] // 2)):
            bags[LINEN["id"]] -= 2
            gain("You create: ", BOLT, 1, moment, episode)
            moment += 4
        made = bags[BOLT["id"]] // 3
        if made:
            spend_or_earn("vendor_purchase", -10 * 3 * made, moment, episode, item=THREAD, quantity=3 * made)
            gain("You receive item: ", THREAD, 3 * made, moment + 1, episode)
            moment += 10
        for _ in range(made):
            bags[BOLT["id"]] -= 3
            bags[THREAD["id"]] -= 3
            gain("You create: ", LINEN_BAG, 1, moment, episode)
            moment += 5
        for sale in range(bags[LINEN_BAG["id"]]):
            gross = 4200 + 550 * day + 375 * sale
            commission = gross // 20
            moment += 20  # Well inside the gap before the next step.
            spend_or_earn("auction_sale", gross - commission, moment, episode, item={"id": False, "name": LINEN_BAG["name"]},
                          quantity=1, gross=gross, commission=commission)
            bags[LINEN_BAG["id"]] -= 1
            bag_snapshot(moment + 1, episode)

    deposits = 0
    for day in range(1, 8):
        name = f"Day {day}"
        scale = day ** 1.8
        moment = (day_one + datetime.timedelta(days=day - 1)).timestamp()
        emit("episode_start", {"name": name}, moment, episode=name)
        valuation(moment + 1, name)
        if day in (2, 5):
            for lesson, cost in (("Journeyman Tailoring", 500), ("Woolen Cape", 225)):
                spend_or_earn("training", -int(cost * scale), moment + 20, name, service=lesson, trainer="profession")
        for step in range(44):
            moment += rng.randint(240, 620)
            roll = rng.random()
            item = {"id": False, "name": rng.choice(ITEMS)}
            if roll < 0.30:
                spend_or_earn("loot", int(rng.randint(90, 420) * scale), moment, name)
            elif roll < 0.48:
                spend_or_earn("quest", int(rng.randint(250, 900) * scale), moment, name)
            elif roll < 0.58:
                spend_or_earn("vendor_sale", int(rng.randint(100, 500) * scale), moment, name)
            elif roll < 0.74:
                quantity = rng.randint(2, 20)
                money = int(rng.randint(400, 1800) * scale)
                spend_or_earn("auction_sale", money, moment, name, item=item, quantity=quantity,
                              commission=money // 19)
            elif roll < 0.84:
                spend_or_earn("auction_purchase_or_bid", -int(rng.randint(250, 1300) * scale), moment, name, item=item)
            elif roll < 0.92:
                spend_or_earn("auction_deposit", -int(rng.randint(15, 80) * scale), moment, name, item=item, quantity=5)
                deposits += 1
                if deposits % 3 == 0:
                    # Every third listing comes back unsold, and its deposit stays with the house.
                    emit("auction_return", {"item": item, "quantity": 5, "failure": "expired"}, moment + 200, episode=name)
            elif roll < 0.96:
                spend_or_earn("repair", -int(rng.randint(60, 240) * scale), moment, name)
            else:
                spend_or_earn("flight", -int(rng.randint(30, 110) * scale), moment, name)
            if step == 30 and day > 1:
                # A balance change no record explains, as happens with drag-to-vendor sales.
                spend_or_earn(None, int(rng.randint(40, 200) * scale), moment + 5, name)
            if step in (9, 27):
                # Marked in game to find again in the recording. No random draw, so the
                # rest of the made-up history stays as it was.
                marked = {"zone": "Elwynn Forest", "subzone": "Goldshire"}
                if step == 9 and day % 3:
                    marked["note"] = "Big auction sale"
                emit("highlight", marked, moment + 3, episode=name)
            if step in (7, 19, 33):
                gain("You receive loot: ", LINEN, 3 + (day + step) % 4, moment + 7, name)
            if step == 41:
                tailoring(day, moment + 9, name)
            stock = max(0, stock + int(rng.randint(-250, 520) * scale))
            if step % 4 == 0:
                valuation(moment + 2, name)
        if day == 4:
            spend_or_earn("training", -int(gold * 0.8), moment + 30, name, service="Summon Felsteed", trainer="class")
        if day % 2 == 0 and gold > 0:
            # Gold moved to the bank character is not income or a cost.
            amount = int(gold * 0.3)
            spend_or_earn("mail_sent", -amount, moment + 60, name, recipient=BANK[1])
            before, bank_gold = bank_gold, bank_gold + amount
            emit("balance", {"before": before, "after": bank_gold, "delta": amount}, moment + 90, BANK, name)
            emit("activity", {"category": "mail_received", "amount": amount, "confidence": "mock", "sender": MAIN[1]},
                 moment + 90, BANK, name)
        valuation(moment + 120, name)
        emit("episode_end", {}, moment + 180, episode=name)
    return {"format": "forever-ledger", "schema": 1, "sourceID": SOURCE_ID, "accountLabel": "Mock",
            "owners": {MAIN[1]: True, BANK[1]: True}, "events": events}
