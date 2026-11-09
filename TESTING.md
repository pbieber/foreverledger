# Validation

The release is a development preview. Automated tests execute the actual addon files under Lua 5.1 using `lupa`, plus the real Python importer and SQLite views. API mocks simulate event ordering; they do not prove the live client's payloads, UI templates or persistence behavior.

## Automated coverage

- Opening balances, duplicate balance events, unknown deltas and login gaps.
- Quest evidence before/after wallet updates; no duplicate counting.
- Failed, stale, ambiguous, uniquely matched and batched action intents.
- Auction intent versus confirmed creation; duplicate confirmations; commodity totals.
- Returned deposits, cancellation followed by return mail, offline FIFO allocation and unmatched/partial sales.
- Mail collected as it leaves the inbox: sales right after an item mail, retried takes, failed takes, repeated confirmations, identical sales, rows still loading, returned and deleted mail, partial attachments, COD, postage and trade completion/cancellation.
- Mail backfill: sales hidden behind an item mail, retried takes recorded twice, refusal unless the gold matches to the copper, unread rows, the original character and time, the current batch left alone, running once from login, per-period counting and the importer's report.
- Total on sale and Cost to list: active listings only, recorded and estimated deposits, the commission setting, selected characters and linked accounts.
- Localized-format money parsing, nil API return positions, immutable payloads and JSON/UTF-8 escaping.
- Partial mailbox snapshots, owned-auction disappearance, inventory valuation and stable export pages.
- Addon login/logout wiring.
- Actual Lua export into SQLite, repeat imports, conflicting IDs with rollback, two-account transfers, missing pages, latest-snapshot selection and selling-cost losses.
- Restricted SavedVariables parser, including rejected executable Lua, UTF-8 byte escapes and CSV export.
- Marker absence/acceptance, blank input and native popup edit-box access.
- Highlights: numbering per marker and per day, time into the marker, undo, no effect on gold, the strip under the plot, minimap Shift-click, and the studio's timeline and `highlights` view.
- BoE equip/unequip binding, owner-specific Enchanting, unlearning, DE fee/vendor floor and missing materials.
- Immutable history, disjoint stacking, realm isolation, settled bag/equipment events and GUID deduplication.
- All versus oldest-50-plus-unpriced queues, material dependencies, quote age, throttling, paging, wrong-item responses, incomplete caches, timeouts and competing searches.
- Modern item/commodity and TBC legacy search adapters, schema-1 upgrades, native menu widget wiring and stacked line coordinates.
- Valuation/price SQLite views and CSV exports.
- Item categories from recorded classes, profit per category and period, and the sync progress states.
- Two addon copies joined by a fake whisper bus: confirmation before sharing, declines, whole-account sync in both directions, message size and pacing, throttled and offline send results, resuming, reconnecting on another character, restored backups, rejected strangers and keys, unlinking and no synced data in exports, and the recording marker set or ended on either account, kept from its original start after being apart, the same marker set on both, and checked when received.

## First live-client check

Use small amounts and record expected results before the video series begins:

1. Enable script errors (`/console scriptErrors 1`), log in, open `/fl`, then `/reload`. Verify the ledger survives and no diagnostic is created.
2. Loot money, finish a quest and buy/sell a cheap item. Check exact copper against wallet deltas and inspect reconciliation.
3. Try an unsuccessful purchase, cancel a trade and cancel mail before sending. None should become a confirmed expense/income solely because of the click.
4. Send a known amount between your accounts, including postage; collect it and import both files twice. Check no duplicate records and no internal-transfer income. Repeat with a direct trade in both directions.
5. Post one auction and cancel it; collect the returned item. Verify a single deposit loss. Let a second expire, including while logged out.
6. Sell an auction. Verify gross price, AH commission, returned deposit and collected wallet amount against the mail invoice. Repeat with commodities/partial purchases and Postal/TSM/open-all if used. Collect a mailbox holding an expired item followed by several sales: every sale must appear under Auction house sales, with nothing added to Not identified.
7. Post identical lots, cancel one and relist. Inspect match confidence rather than assuming exact identity. Test several fast vendor sales and combined gold updates.
8. Open bags, bank, mailbox and owned auctions. Verify complete/partial flags, item quantities and price units. Move items across locations and inspect timestamps for stale overlap.
9. Check estimates with and without Auctionator. Unknown prices must not become zero-value claims. Recheck sold-awaiting-delivery versus uncollected mail to avoid counting the same proceeds twice.
10. Import both SavedVariables into SQLite. Verify reported balances, fees, unresolved records and totals independently. Keep the input files as test fixtures for future regressions.
11. Clear the marker with `/fl end`, reload, and accept/decline the prompt. A set marker must persist and suppress the next prompt. Declining must not stop tracking.
12. At the AH, run both scan modes; compare several unit prices manually. Test no listings, multiple pages, another search, closing the AH and a temporary disconnect. Never treat a timeout as a zero quote.
13. Scan a cheap BoE, equip it, then unequip it. Auction-item value must disappear permanently. Repeat with an enchanter and a non-enchanter; only the bound item's owner grants DE eligibility. Check missing material prices and vendor-dominant items.
14. Verify chart series and character selection, custom stacking, hover values, small-screen scaling and saved selection. Switch between **Type**, **Category** and **Character** with several values selected: the top of the stack and the axis must not move, the active button must stay highlighted, and the legend must name every band and fit without covering the stats. Check that curves have no notches or stray pixels where they turn, at more than one UI scale, and that the area meets the line with no gap. Check that the minimap icon shows the small journal bottom right and the ape up and left of it, with no map showing through the opening. Gold + assets + equipment must equal total exactly. Current price changes must not alter earlier points. Check that the top axis label is fully readable below the controls. Repair, loot, finish a quest, sell to a vendor and collect an auction sale, then hover Gain today: each must appear under its own row, and the rows must add up to the gain. Post one auction and one multi-stack auction, through both the Blizzard UI and Auctionator: the deposits must appear under Auction house fees and match the deposit each UI showed, not under Not identified.

15. With both accounts online, check the window at 644 x 532: no clipped button labels, chart controls or hover text. Then link them from **Sync**. Confirm the popup names the right character, that declining shares nothing, and that accepting brings over every recorded character on the other account. Check chart totals on both sides against `/fl` on each account. Log out the linked character, log in another on that account and confirm it reconnects without `No player named` chat lines. Note how long a first sync takes and whether the client ever refuses messages. During a first sync, the bar in **Sync** must fill, turn green and read **Complete** when it ends. Log the other account off midway: it must read **Paused**, and continue from there after logging back in. Set a marker on one account: the other must print **Marker from**, close its marker prompt if open, and show the marker at the same place on its chart. End it there and check the first account ends too.

16. On the first login with this version, each account reads back its earlier mailbox records once and prints how many missed collections it recovered. Compare Not identified and Auction house sales in Gain today before and after. Check that `/fl journal` shows `mail_backfill` records, and that a second reload recovers nothing more. A send with money should show only the real postage in Gain today, and earlier such sends are corrected once, with their own `mail_backfill` records marked `repair="postage"`.

17. List two auctions, one with a deposit and one for an item without a vendor price, then reopen the AH. **Total on sale** must match their buyout prices, sit right-aligned on the Total Value line, and **Cost to list** must match the deposits the AH showed. Hover it: the cut must equal the `/fl fee` percentage of the total. Let one sell and revisit the AH: both figures must drop.

18. Open **Profit**. Check that labels fit their columns. Buy a stack from the AH, sell one, and gather something: each must land in its own category, with Profit equal to Sold + Spent + Stock change on every row. Switch between Today and All time. With a linked account online, select its characters: its sold, spent and held figures must be added, and must match its own **Profit** view with only those characters selected. Log it off and set a marker: the yellow notice must show, and clear when it returns.

19. Bind **Mark a highlight**, set a marker and press the key twice, a minute apart. Each press must print one chat line with the clock time and time into the marker. Shift-click the minimap button and use `/fl highlight test note`. Open the chart: four ticks must sit on the strip under the plot, not on it, and their tooltips must match the chat lines. `/fl highlight undo` must remove the last tick. After `/reload`, import the file into the studio and check the same highlights and times in **Data**.

TBC Anniversary can cover steps 1–4 and 8–19 plus available sale invoice fields. Its legacy auction-ID lifecycle is outside this preview, so steps 5–7 still require Forever. Outland DE outcomes are not modeled. Native rendering in either client remains untested; the widget tests are mocks, not screenshots from a running game.

Do not describe the preview as tracking every source perfectly until these checks pass against the actual client. All observed gold differences are retained; detailed source attribution and auction matching can remain incomplete and explicitly flagged.
