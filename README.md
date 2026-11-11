# Forever Ledger 0.2.0 — development preview

A standalone WoW Forever addon for recording gold movements, economic activity, inventory and auctions across a gold-making video series. A companion Python importer merges both accounts into one SQLite database and produces JSON reports and CSV tables.

Built on the assumption that the published Forever APIs and the interfaces used by existing addons function. This release has automated Lua 5.1 and Python tests, but has **not been loaded or validated in a live Forever client**. Start recording from your first login and keep the original data for later reconciliation.

## Install on both accounts

1. Extract the ZIP. Copy the **ForeverLedger** folder into the active Forever client's `Interface/AddOns` directory. The final path must be `Interface/AddOns/ForeverLedger/ForeverLedger.toc`.
2. Enable Forever Ledger on every character you want to record. If both accounts use the same game installation, installing the addon once is enough; each account keeps separate SavedVariables.
3. On the main account run `/fl account Main`. On the second run `/fl account Bank`.
4. Register characters across the accounts with `/fl own Character-Realm`. Use normalized realm names without spaces. Logged-in characters are registered automatically; the database combines ownership from both exports.
5. Login/reload asks for a recording marker if none is active. Enter an episode name, or choose **Not now** to continue recording without one. `/fl episode Episode 1 - Starting out` and the **Set marker** button also set it; `/fl end` clears it. Linked accounts share the marker: setting or ending it on one does the same on the other, from the same moment, so set it once. An account that was offline picks it up when it next syncs. If both started the same marker, the earlier start counts; otherwise the latest change wins.
6. Open your bank, mailbox and the AH's owned-auctions view to populate those snapshots. `/fl scan` refreshes currently accessible locations. Information for offline characters is explicitly last-observed data.

The addon does not buy, sell, mail, trade or cancel anything. It observes user actions, requests owned-auction data and performs market queries when you start a price scan. No external network service is used; linked accounts talk only through in-game addon whispers.

## Mark highlights to find in the footage

While you record, mark a moment you'll want to find again: a big sale, a lucky drop, a mistake worth showing. Bind a key under **Key Bindings > AddOns > Forever Ledger > Mark a highlight**, Shift-click the minimap button, click **Mark highlight** under the chart, or type `/fl highlight` with an optional note, such as `/fl highlight sold the cloak`. One chat line confirms it with the clock time and, while a marker is set, how far into the marker it is. `/fl highlight undo` takes back the latest one.

Highlights never touch the gold figures. They sit on their own strip directly under the chart, on the same time axis. Hover a tick for its number, time, note, zone and character; a guide line shows where it falls on the chart above. Highlights are numbered within their marker, or within the day when none is set. To find one in a recording, use the clock time, or the time into the marker if you start recording when you set it.

## See which item categories make a profit

**Profit** lists each item category, such as Gear, Cloth, Mining, Herbs, Leather, Enchanting and Consumables, from most to least profitable. **Today** counts from the same point as Gain today; **All time** covers everything recorded. It uses the characters selected on the chart, including characters on linked accounts.

| Column | Meaning |
|---|---|
| **Held now** | Estimated value of those items across bags, bank, mail, auctions and equipped gear |
| **Sold** | Gold received from auction and vendor sales |
| **Spent** | Gold paid for purchases, deposits and auction fees |
| **Stock change** | How much the value held changed in that time |
| **Profit** | Sold - Spent + Stock change |

Counting stock means ore you gathered but haven't sold shows as an estimated profit, and materials you bought but still hold don't show as a loss. It also means a price scan can move these figures. Loot gold, quest rewards and repairs have no item, so they stay in Gain today.

A linked account sends its totals per character while it is online, every five minutes or whenever this view is open. The view shows how old they are. If you set a marker or a new day starts while that account is offline, its **Today** figures wait until it is back; what it holds and its **All time** figures still show.

Limits: items mailed to a character you haven't selected count as a drop, and items in the post between accounts count once the mailbox is opened. Stock is tracked from this version on, so All time has sales from earlier but no stock from before then. A sale counts once you collect its mail, and an auction you sold counts as gone from stock when the AH next shows it.

## Sync your other account in-game

1. Log in on both accounts at the same time, on the same realm (or a connected realm) and faction.
2. On either account, open the ledger, choose **Sync**, then **Add character**, and enter a character on the other account (`Name` or `Name-Realm`). `/fl sync add Name-Realm` does the same. On Forever, enter just the name: each account can sit on a different hidden realm, and the client finds the character by name. If a character comes back on another hidden realm, sync finds it again by name, and prices last seen on its old realm are used until the next scan.
3. On the other account, a popup names the requesting character. Choose **Link accounts**. Nothing is shared before this confirmation.

The **Sync** view shows a progress bar for each linked account. It fills as data arrives, turns green and reads **Complete** when everything has come across, and shows where it paused if that account logs off. A chat message also confirms a finished first sync.

The link is between the accounts, not those two characters. Every character the other account has recorded syncs, and either account can reconnect on any of its characters: each one looks for the other at login, and **Sync now** (`/fl sync now`) tries again on request. While both are online, changes follow within about a minute. A character appears after it has logged in once with the addon enabled.

Sync goes both ways and shares each character's name, class, balance and top items, plus the account's value history and profit totals per item category. Those characters then appear in the chart, the **Characters** list and the summary, with their values as the other account last calculated them. Characters on another realm or faction are listed in the summary but stay off the chart, like your own. On Forever, the numbered hidden realms behind one realm (such as `CAMWOWEU5Realm2PvP` and `CAMWOWEU5Realm6PvP`) count as one realm, so both accounts share the chart. Linking also registers all of them as owned, so transfers between the accounts count as internal in the database.

Synced data is kept apart from recorded events, so it is never exported or imported twice. Raw records stay on the account that made them: use the database below to merge those. Item breakdowns of synced characters show their current items at every point in time. A first sync of a long history can take minutes, because the client limits addon messages; it continues where it stopped after a reload or logout. Each long message is checked on arrival, and one that lost a part on the way is asked for again. Both accounts need this version to sync. The first login after updating fetches the linked account's history once more, because copies synced by earlier versions could have rows missing or joined together. **Unlink** (`/fl sync remove Bank`) removes synced data from this account, and from the other account if it is online. Accept a link only from a character you own.

## Try it in TBC Anniversary

Yes: the package includes `ForeverLedger_TBC.toc` for interface **20506** (2.5.6), plus a legacy AH price-scanning adapter. Copy the same ForeverLedger folder into your Anniversary installation's `Interface/AddOns` directory. If your client has a different interface patch, enable **Load out of date AddOns** for testing. Keep Anniversary test exports in a separate database from your Forever series.

Test gold changes, quests, vendors, trades, mail invoices, marker persistence, price scans, binding changes and the chart. This is a compatibility preview, **not a claim of live TBC validation**. TBC's legacy AH does not provide the Forever auction-ID creation/outcome path this collector uses: exact listing/deposit/return matching is not covered there. Raw wallet changes and available mail invoice fees are still captured. Outland and TBC item-level >60 disenchant estimates deliberately fall back to vendor value; the bundled model covers Forever-era loot. A TBC test cannot validate Forever-specific events.

## History chart and item values

Total Value, Total Gold and Gain today for the selected characters are stacked at the top. Gain today is the change in gold since the active marker started, or since the first login of the day when no marker is active, in green for a gain and red for a loss. A character that first logs in after that point counts from the balance it arrived with. Hover each one for its breakdown: Total Value by gold, other assets, Equipped Gear and character, plus how many rows are only partly valued; Total Gold by character; Gain today by cause, such as loot, quest rewards, repair costs and auction house sales. Those rows always add up to the gain. **Not identified** is gold that changed with no record explaining it, and **Linked accounts** is one row because their raw records stay on that account. **Total on sale**, on the right, adds up the selected characters' active auctions at their buyout price, or their bid when they have none, as last seen at the auction house. Below it, **Cost to list** is the deposit those auctions took: the amount recorded when they were posted, otherwise the vendor-price rate for a 48 hour listing, and its tooltip says how many are estimated. Hover it for the auction house cut if they all sold, using the `/fl fee` percentage. A sale returns its deposit; an expired or cancelled auction keeps it. The **Summary** button holds the text summary of balances and snapshots. **This character**, **All Characters** and the **Characters** list choose any combination of characters on this realm and faction. The dropdown beside them selects gold, other assets and Equipped Gear, and the switch next to it stacks that value by **Type**, **Category** or **Character**, with a legend above the chart. Selected components stack cumulatively; total value is the sum of those components, never a fourth series. A breakdown shows the seven largest bands, and the rest fold into **Other**. The stack always adds up to the same exact total. **Category** puts gold in its own band and Equipped Gear under Gear, and splits other assets by the last item mix recorded before that point, fitted to the exact value. Linked accounts only send what their characters hold now, so their categories use that mix at every point in time. Hover the chart for a vertical line with the total value at that time. Hover a line for its breakdown: characters by gold, in class color, or the top ten items by total value with their amount and character. Under **Category** it lists the characters holding that category, and under **Character** that character's gold, other assets and Equipped Gear. Item breakdowns are recorded from this version on. Episode starts and ends appear as vertical markers; an end that overlaps the next start shows only the start. It displays the whole history in equal time steps up to now, each showing the latest observation at or before it; all observations remain in the export. The lines are softened over a few steps, while the totals and hover values stay exact. History starts with this version and is not retroactively repriced.

- **Gold:** last observed wallets on this account and linked accounts, on this realm and faction.
- **Other assets:** bag/bank items, active AH items and observed non-COD mailbox contents/money. Active auctions use item estimates; their asking prices are shown separately in the summary.
- **Equipped Gear:** vendor or eligible expected disenchant proceeds for equipped gear.

An unbound item uses the highest of vendor price, auction price after commission, and expected disenchant material value after commission. This includes the requested `max(vendor, DE net)` floor. Tradable DE assumes access to an enchanter; no service charge is assumed. Equipped/soulbound items never receive an auction-item value. Their DE option requires Enchanting on the **owning character** (and sufficient modeled skill in TBC). Unequipping a soulbound item does not restore its auction value. Unknown binding falls back conservatively to vendor value.

DE is a probabilistic model, not guaranteed loot. Every possible material must have a price; incomplete/unsupported DE estimates are flagged and use the available alternatives. Prices are copper per item. The default estimated commission is 5%; `/fl fee 15` changes it for neutral-AH estimates, and `/fl fee 5` restores it. This only changes estimates, never recorded invoice fees. Estimates exclude future failed-listing deposits, unknown service costs and time to sell.

## Plan episodes and make charts in Ledger Studio

Ledger Studio is a local website for the video series. It needs Python 3.10 or newer and nothing else:

```powershell
python .\studio\studio.py
```

It opens http://127.0.0.1:8765, reachable only from this computer. The sidebar holds series and titles under Shorts and Longform. Drag episodes to reorder them, or to move them to another series; double-click a name to rename it. Each episode has a **Script**, its **Shots**, and its **Data**.

**Data sources:** Forever, TBC Anniversary and Mock data each have their own database in `studio/data/` and are never merged. An account already imported into one source is refused by the others. The studio finds `_forever_` and `_anniversary_` SavedVariables in the usual install folders (`--wow-root` adds another), reads them shortly after the game saves, and never writes to them. A large file can take a minute or two to import.

**Charts:** choose a marker, calendar day or all history. Nothing recorded after the end of that window is counted, so an episode's numbers stay the same later on. **Export PNG** makes a 1080 x 1920 image for a Short, with content kept clear of the Shorts interface, or 1920 x 1080 for longform. Forever and TBC charts name their source. Mock data charts carry no label, so keep them out of published videos.

Each chart draws itself the first time it comes into view: columns grow in turn, and lines run left to right. Below each chart are **Play**, a scrubber and the animation length for recording, **Wide** or **Vertical** to choose which layout you see, and **Axis from**. **Fit** starts the vertical axis just below the data so a small change is visible, **Custom** takes a number of gold, and the lowest label on the axis shows where it starts. Axis and length are saved per chart for each episode, and exports use them.

**Export MP4** makes the same animation as a 60 fps H.264 video, sized like the PNG, with the finished chart held for 2 more seconds. Every frame is drawn in turn rather than recorded, so a busy computer can't make it stutter; clicking the button again cancels. It needs a browser with video encoding, such as Chrome or Edge.

**Icons:** gold, silver and copper are the game's own coin icons. Item icons come from your Pugger checkout (`--pugger-icons` if it has moved) and are copied to `studio/data/icons/`. For an item Pugger doesn't have, the studio sends its ID or name to Wowhead to find the icon. `--offline` turns that off, leaving a blank slot.

**Visuals:** each episode's **Visuals** tab makes item cards to lay over footage. Search for any item: this data source's own items come first, then anything Wowhead knows by that name. A card shows the item's icon and its tooltip as Wowhead has it for Forever or TBC, with a gold amount beside or below it, green for a gain and red for a loss. Type the amount in gold, silver and copper and choose **Gain** or **Loss**; with no amount the card is just the tooltip. **Item level** and **Sell price** hide those lines. **Export PNG** saves the card at three times the game's tooltip size with a transparent background, and **Copy image** puts the same picture on the clipboard. Tooltips are kept in `studio/data/tooltips/` after the first look. With `--offline`, or when Wowhead can't be reached, a card shows only the item's name. Cards are saved with the episode.

**Highlights:** above the charts, the window's highlights sit on their own timeline, with a table of each one's clock time, time into its marker, note, zone and character. Click a tick to find its row. **Copy list** copies them as text, one per line, to paste into your editor's notes.

- **Starting point:** gold at the start, the change and the end, with the top 3 income and top 2 loss lines. They reconcile to the wallet: **Everything else** holds what isn't shown, and **Not identified** is gold no record explains. Transfers between your own characters are left out.
- **Auction house activity:** cumulative gold collected and spent, with the top 5 items by net gain. Sold is net of commission and includes returned deposits, and counts when the mail is collected. Spent is purchases plus deposits and cancellation fees. Net gain is cash only, so stock still held isn't counted. A dashed line, **With vendor stock**, adds what vendor-bought items cost, counted when they go up for auction and only for the units listed. Units bought but never listed add nothing, and a unit that comes back unsold isn't counted again when it's relisted. It shows only when some vendor stock was listed.
- **Total value:** the sum of each account's latest valuation. It's an estimate, and a price scan can move it even when no gold changes hands. The buttons under it switch the chart between **Total value** and one of its parts on its own: **Gold**, **Other assets** or **Equipped gear**. The choice is saved per episode and names the exported file. While the line draws, the figure above it counts along with it, averaged over a short stretch so it climbs steadily, and finishes on the exact last value.
- **Item analysis:** pick one item, listed by what it sold for in the window. It shows how many sold, the highest and lowest price each, how many were farmed, crafted or bought, and what was spent buying it or the materials to craft it. Farmed and crafted counts come from your own characters' English chat lines ("You receive loot", "You create"), so other players' loot is never counted. Recipes are read from the bags just before and after a craft. A material costs what you paid per unit on average up to the window's end, with farmed ones free and crafted ones costing their own materials. A material you never bought, farmed or crafted on record, such as one mailed from another account, has no cost and is flagged. TBC auction purchases made before this version have no stack size, so they count toward spending but not toward units bought. Forever vendor buys made before this version have no record of their own, because the addon couldn't read Forever's merchant window. The studio rebuilds them from gold spent at a merchant and the "You receive item" line beside it, when that gold is otherwise unexplained and the lines name one item. The table says how many purchases were rebuilt this way. The episode remembers the item until you change data source.

## Refresh prices

Open the AH, then use the menu buttons or:

- `/fl prices all`: query every tracked item variant and the materials needed for its DE estimate.
- `/fl prices oldest`: query **all unpriced items plus the 50 priced items with the oldest price timestamps**. Unknown-age quotes sort first.
- `/fl prices stop`: stop safely; completed observations remain saved.

The tracked catalog consists of item types seen by the addon, including previously held stock. This is not a scan of every item in WoW. There is no Auctionator dependency. Its optional cached prices can seed missing estimates, preserving its reported age (or unknown age), but a refresh uses actual AH queries. The scan follows result pages, waits for throttling, and stops on timeout, AH close or another search. Avoid browsing/scanning with another addon while it runs. Complete no-buyout results remove stale quotes and leave items unpriced for the next run; failed queries preserve existing quotes.

## Commands and display

| Command | Purpose |
|---|---|
| `/fl` or `/foreverledger` | Account balances, collection health and current character's valuation snapshots |
| `/fl account Main` | Label the current account's data source |
| `/fl own Character-Realm` | Mark another character as yours |
| `/fl profit` | Open the profit view, with linked accounts included |
| `/fl sync` | Open the sync view |
| `/fl sync add Name-Realm` | Ask a character on your other account to link accounts |
| `/fl sync now` | Look for the linked account and sync |
| `/fl sync remove Bank` | Unlink an account and remove its synced data |
| `/fl episode My episode` | Begin an episode label |
| `/fl end` | Finish the episode |
| `/fl highlight [note]` or `/fl hl [note]` | Mark a moment to find in the recording |
| `/fl highlight undo` | Remove the latest highlight |
| `/fl scan` | Record bags, accessible bank/mail/auctions |
| `/fl prices all`, `/fl prices oldest`, `/fl prices stop` | Market price scan controls |
| `/fl fee 5` | Assumed AH commission percentage for valuations |
| `/fl journal` | Inspect the most recent 50 raw records |
| `/fl export 1` | Copy JSON export page 1, 50 records per page |

Keep typing `/reload` or logging out normally at useful checkpoints: WoW writes SavedVariables then. A crash can lose records since the last write. Never share or overwrite SavedVariables between accounts; their independent source identities are what make merging safe. Back up the files periodically. This version retains all records and has no automatic pruning.

## Merge both accounts locally

Python 3.10 or newer is needed for the companion tool. The importer uses only Python's standard library. The addon itself has no required dependencies.

Find each account's file under the active client:

```text
WTF/Account/<account>/SavedVariables/ForeverLedger.lua
```

After `/reload` on both clients, run from the extracted package directory:

```powershell
python .\ForeverLedger-tools\ledger.py --db .\series.sqlite --report .\report.json --csv .\csv "C:\Games\World of Warcraft\<client>\WTF\Account\<main>\SavedVariables\ForeverLedger.lua" "C:\Games\World of Warcraft\<client>\WTF\Account\<bank>\SavedVariables\ForeverLedger.lua"
```

Replace the example paths with your actual paths. The tool reads SavedVariables as literal data; it never executes Lua. It never writes back to WoW's files.

Add `--watch` to keep merging whenever WoW saves either account. Stop with Ctrl+C. This is synchronization into the local database, separate from the in-game sync above, and it is the only path that merges raw records. Files on another computer must first be made available locally.

Alternatively, copy each `/fl export <page>` into a UTF-8 JSON file and import those files with the same command. Reimporting or overlapping export pages is safe. A conflicting event ID causes that file's import to roll back instead of overwriting data. The report flags missing sequence ranges. For larger histories, the complete SavedVariables file is easier than copying pages.

## What is recorded

- Every observed `PLAYER_MONEY` balance delta, opening/login balances, unexplained login gaps and reconciliation windows.
- Quest reward money and item evidence; loot money messages and item chat messages, with zone/map context where available.
- Confirmed trades with both directions of money and item transfers.
- Mail collected by earlier versions but left unrecorded is recovered once, on the first login with this version, from the mailbox reads already on file. Each correction must equal, to the copper, the gold nothing explained at that moment, or it is skipped and the gold stays under Not identified. Corrections are added as new records and count in the period the money moved.
- Mail sends, postage, COD, collections and auction invoice components. A collection is recorded when the mail's money or items actually leave the inbox, whichever addon took them. Mail bodies are not recorded.
- Vendor purchase/sale/buyback intents, junk-selling intents, repairs, flights and training. A matching balance change is required before these become classified activities, with a correlation label rather than a false claim of server-confirmed causality.
- Confirmed auction postings, deposits, server auction IDs, exact cancellation/expiration events when provided, sale invoices, commission, returned deposits and auction return evidence.
- Bags, equipment, accessible character bank, visible mailbox and owned-auction snapshots. Partial mailbox/AH results are marked partial. Items carry item links/IDs and vendor values when available.
- Market price observations with source, scan time and missing-price status; optional Auctionator quotes preserve reported age.
- Immutable valuation history, item binding/equipment state, owner profession observations and estimated net liquidation values.

## Read the financial results correctly

The `cash_movements` SQL view is the authoritative history of observed wallet changes. The `activities` view explains those changes; **do not add the two together**. The `reconciliation` view exposes discrepancies. Gold received from sales includes a returned deposit, so classified cash inflow is not the same thing as sales revenue.

The JSON report includes:

- Latest character balances and observed net gold change.
- Classified external cash in/out, internal transfer net, login gaps and unresolved windows.
- Latest inventory and auction snapshots, their timestamps and completeness.
- Per-item listings, sold quantity, gross sales, commission, cancellation fees, confirmed and allocated lost deposits, purchase spend, and margin before acquisition cost.
- `selling_costs_exceed_revenue` flags, unmatched auction returns/sales, collector diagnostics and incomplete imports.

All money is integer **copper**: 10,000 copper = 1 gold.

Economic margin before acquisition cost is:

```text
gross sale revenue - sale commission - cancellation fees - forfeited deposits
```

A returned deposit is neither revenue nor a permanent expense. Active or unmatched deposits are shown as `deposits_without_matched_outcome`; they are never automatically labelled expired just because time passed or an auction vanished from a snapshot.

Purchase spend is exported separately. It is not automatically subtracted from sold-item profit, because some purchased stock may still be unsold. If you have a known acquisition cost, supply a JSON file mapping item IDs to unit costs in copper:

```json
{"2770": 200, "2447": 100}
```

Pass `--unit-costs costs.json` to add `profit_at_supplied_unit_cost`. This is an explicitly supplied cost model, not automatic batch-level cost accounting. The raw data supports a more sophisticated FIFO or weighted-average model in your later database project.

## Precision and current limits

**Captured amounts versus attribution:** the addon preserves observed wallet deltas even when it cannot identify their source. A balance update may combine several actions. Unknown causes, missed events and unavailable/secret data remain visible through residuals and diagnostics; recording a net change cannot recover every unobserved gross flow. Activities that happen while the addon is disabled are not reconstructed from the next balance.

**Auction matching:** server-ID outcomes are distinguished from inferred unique matches and FIFO allocations. Auction mail does not expose an auction ID. Multiple identical lots can therefore require allocation. Partial-stack/aggregated sales that cannot be matched remain unmatched; their reported proceeds, commission and refund are still recorded. Vendor/market prices and copied item links do not prove which farming session produced an item.

**Inventory valuation:** chart totals are estimates from last-observed snapshots, not a synchronized world state. When available, instance GUIDs deduplicate overlapping storage observations. Without them, stale bank/mail/AH snapshots can overlap with bags after movements; opening those locations refreshes them. Offline characters remain stale. Pending sold-AH proceeds and refundable deposits are not counted until observed in mail/wallets, so transfers can temporarily lower the estimate. Snapshot timestamps/completeness and partially priced rows remain visible/exported. Revisit every character after upgrading from 0.1 to establish its realm/faction valuation scope. The chart covers this account and linked accounts; use the database to combine both accounts' records.

**Scope:** character wallets and accessible character storage are covered. Guild/warband holdings, detailed crafting material transformations, automatic acquisition-lot provenance and in-game transfer of raw records between accounts are not implemented. Unusual purchase/refund paths, drag-to-vendor sales and repairs not caught by a specific hook still appear in wallet changes but may need manual attribution. The tool does not claim a retrospective, complete history.

**No live validation:** see TESTING.md for the first-client checks. Journalator may be run in parallel as a comparison; this addon does not depend on or read its data.

## Source and development

The package includes the addon source, database importer, automated tests and SCHEMA.md. Tests use `lupa`'s Lua 5.1 runtime; production importing needs no third-party Python packages.

```powershell
python -m pip install lupa
python -m unittest discover -s .\ForeverLedger-tools\tests -v
```

API reference: [published Forever UI/API source](https://github.com/Gethe/wow-ui-source/tree/ca8368f2f2380cbe696854f7f2646387c278a61b), particularly `AuctionHouseDocumentation.lua`, `ContainerDocumentation.lua`, `MailInfoDocumentation.lua` and `TradeInfoDocumentation.lua`.

Event-handling reference: [Journalator source](https://github.com/TheMouseNest/Journalator/tree/c6166ead2801d93cde0dbb1d09b0410ad4316b8d). This package is a separate implementation; Journalator is not bundled.

TBC adapter reference: [Anniversary Blizzard UI source](https://github.com/Gethe/wow-ui-source/tree/68e0a2ec559d9761dfc4e7f864c3944f9d758a49), particularly `Blizzard_AuctionUI/Classic/Blizzard_AuctionUI.lua`. Disenchant model adapted from [Mailworthy](https://github.com/sjdodge123/mailworthy/blob/main/Mailworthy/Disenchant.lua), with its MIT notices in `ForeverLedger/THIRD_PARTY.txt`.

## Repository workflow

Repository: https://github.com/pbieber/foreverledger

From the repository root:

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s ForeverLedger-tools/tests -v
python scripts/package.py
```

The package is written to `dist/`. GitHub Actions runs the tests and packaging check on pushes and pull requests. Gameplay exports and database files should remain local.
