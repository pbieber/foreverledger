"""Bake what Pugger Waylaid Companion recorded in game into the addon's shipped data.

Reads every account's SavedVariables/PuggerWaylaidCompanion.lua in the WoW Forever client
(read-only), merges it with what is already in PuggerWaylaidCompanion/Data/Recorded.lua,
and rewrites that file:

  - where each Craftsman's Writ is handed in (an NPC, or a map spot nobody has named yet);
  - the Merchant's Favor each sealed crate paid.

Nothing is ever dropped: a writ already in Recorded.lua stays unless the saved data knows
better (an NPC's name for what was only a spot).

    python scripts/bake_waylaid.py [--wow "C:/Program Files (x86)/World of Warcraft"] [--dry-run]

Needs lupa (pip install lupa) to read the Lua files.
"""
from pathlib import Path
import argparse
import sys

try:
    from lupa import lua51 as lupa
except ImportError:  # older lupa builds
    import lupa

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / 'PuggerWaylaidCompanion'
OUT = ADDON / 'Data' / 'Recorded.lua'


def to_py(value):
    """A Lua table as a dict, recursively."""
    if lupa.lua_type(value) == 'table':
        return {to_py(k): to_py(v) for k, v in value.items()}
    if isinstance(value, float) and value == int(value):
        return int(value)
    return value


def load_saved(path):
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(path.read_bytes())
    return to_py(lua.globals().PuggerWaylaidCompanionDB) or {}


def load_shipped():
    """(shipped NPC ids, writ quest -> shipped NPC id or None, quest -> name, recorded)."""
    lua = lupa.LuaRuntime(unpack_returned_tuples=True)
    ns = lua.table()
    files = ['Data/Writs.lua'] + (['Data/Recorded.lua'] if OUT.exists() else [])
    for name in files:
        chunk = lua.eval('function(src, name) return assert(loadstring(src, name)) end')(
            (ADDON / name).read_bytes(), name)
        chunk('PuggerWaylaidCompanion', ns)
    writs = {}
    names = {}
    for row in to_py(ns.WRITS).values():
        writs[row[1]] = row.get(8)
        names[row[1]] = row[10]
    recorded = {
        'npcs': to_py(ns.RECORDED_NPCS) if ns.RECORDED_NPCS else {},
        'writs': to_py(ns.RECORDED_WRITS) if ns.RECORDED_WRITS else {},
        'favor': to_py(ns.RECORDED_FAVOR) if ns.RECORDED_FAVOR else {},
    }
    return set(to_py(ns.WRIT_NPCS)), writs, names, recorded


def place(table):
    """{1: name, 2: map, ...} -> [name, map, x, y, zone]."""
    return [table[i] for i in range(1, 6)]


def lua_key(key):
    return '[%d]' % key if isinstance(key, int) else '["%s"]' % key


def lua_string(text):
    return '"' + str(text).replace('\\', '\\\\').replace('"', '\\"') + '"'


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--wow', default='C:/Program Files (x86)/World of Warcraft')
    parser.add_argument('--dry-run', action='store_true', help='report, write nothing')
    args = parser.parse_args()

    shipped_npcs, writs, names, recorded = load_shipped()
    npcs = {k: place(v) for k, v in recorded['npcs'].items()}
    where = dict(recorded['writs'])
    favor = {k: dict(v) for k, v in recorded['favor'].items()}
    before = (len(where), sum(isinstance(v, int) for v in where.values()))

    saved = sorted((Path(args.wow) / '_forever_' / 'WTF' / 'Account').glob(
        '*/SavedVariables/PuggerWaylaidCompanion.lua'))
    if not saved:
        sys.exit('No PuggerWaylaidCompanion.lua found under ' + args.wow)
    for path in saved:
        db = load_saved(path)
        account_npcs = {k: place(v) for k, v in (db.get('npcs') or {}).items()}
        account_writs = db.get('writNpc') or {}
        print('%s: %d writs, %d places, %d favor entries' % (
            path.parts[-3], len(account_writs), len(account_npcs), len(db.get('favor') or {})))
        for quest, at in account_writs.items():
            if quest not in writs:
                print('  ! quest %s is not a known writ, skipped' % quest)
                continue
            if writs[quest] is not None:
                continue  # Data/Writs.lua already has its NPC
            if at not in account_npcs and at not in shipped_npcs and at not in npcs:
                print('  ! quest %s points at %s, which has no place, skipped' % (quest, at))
                continue
            old = where.get(quest)
            # An NPC beats an unnamed spot; otherwise the first one recorded stays.
            if old is None or (isinstance(at, int) and not isinstance(old, int)):
                where[quest] = at
            elif old != at:
                print('  ! quest %s (%s): keeping %s, saved data says %s' % (quest, names[quest], old, at))
            if at in account_npcs and at not in shipped_npcs:
                npcs.setdefault(at, account_npcs[at])
        # Counts are folded in as the larger of the two, not added, so that baking the
        # same saved file twice does not double them.
        for key, paid in (db.get('favor') or {}).items():
            kept = favor.setdefault(key, {})
            for amount, times in paid.items():
                kept[amount] = max(kept.get(amount, 0), times)

    used = set(where.values())
    npcs = {k: v for k, v in npcs.items() if k in used}
    named = sum(isinstance(v, int) for v in where.values())
    total = len(writs)
    known = sum(1 for q, npc in writs.items() if npc is not None or q in where)

    def order(key):
        return (isinstance(key, str), key)

    lines = [
        "-- Recorded in game by Pugger Waylaid Companion and written here by",
        "-- scripts/bake_waylaid.py. Do not edit by hand: run the script again instead.",
        "local _, ns = ...",
        "",
        "-- Places writs are handed in that Data/Writs.lua does not have:",
        "-- [NPC id, or \"at:map:x:y\" for a spot nobody has named yet] = { name, uiMapID, x, y, zone }",
        "ns.RECORDED_NPCS = {",
    ]
    for key in sorted(npcs, key=order):
        name, map_id, x, y, zone = npcs[key]
        lines.append('  %s = { %s, %d, %s, %s, %s },' % (
            lua_key(key), lua_string(name), map_id, x, y, lua_string(zone)))
    lines += ["}", "", "-- [writ quest] = place", "ns.RECORDED_WRITS = {"]
    for quest in sorted(where):
        lines.append('  [%d] = %s, -- %s' % (
            quest, where[quest] if isinstance(where[quest], int) else lua_string(where[quest]), names[quest]))
    lines += ["}", "",
              "-- Merchant's Favor paid for a filled crate:",
              "-- [sealed crate item, or \"q<quest>\" when the crate was not seen] = { [amount] = times seen }",
              "ns.RECORDED_FAVOR = {"]
    for key in sorted(favor, key=order):
        paid = ', '.join('[%d] = %d' % (a, favor[key][a]) for a in sorted(favor[key]))
        lines.append('  %s = { %s },' % (lua_key(key), paid))
    lines += ["}", ""]

    print('Recorded writs: %d (was %d), %d with a named NPC (was %d).' % (len(where), before[0], named, before[1]))
    print('Turn-in known for %d of %d writs.' % (known, total))
    if args.dry_run:
        print('Dry run: nothing written.')
        return
    OUT.write_text('\n'.join(lines), encoding='utf-8', newline='\n')
    print('Wrote ' + str(OUT.relative_to(ROOT)))


if __name__ == '__main__':
    main()
