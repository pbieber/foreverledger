# Validation

The release is a development preview. Automated tests execute the actual addon files under Lua 5.1 using `lupa`, plus the real Python importer and SQLite views. API mocks simulate event ordering; they do not prove the live client's payloads, UI templates or persistence behavior.

## Automated coverage

- Opening balances, duplicate balance events, unknown deltas and login gaps.
- Quest evidence before/after wallet updates; no duplicate counting.
- Failed, stale, ambiguous, uniquely matched and batched action intents.
- Auction intent versus confirmed creation; duplicate confirmations; commodity totals.
- Returned deposits, cancellation followed by return mail, offline FIFO allocation and unmatched/partial sales.
- Mail success/failure, repeated success, open-all item versus money confirmation, postage and trade completion/cancellation.
- Localized-format money parsing, nil API return positions, immutable payloads and JSON/UTF-8 escaping.
- Partial mailbox snapshots, owned-auction disappearance, inventory valuation and stable export pages.
- Addon login/logout wiring.
- Actual Lua export into SQLite, repeat imports, conflicting IDs with rollback, two-account transfers, missing pages, latest-snapshot selection and selling-cost losses.
- Restricted SavedVariables parser, including rejected executable Lua, UTF-8 byte escapes and CSV export.
- Marker absence/acceptance, blank input and native popup edit-box access.
- BoE equip/unequip binding, owner-specific Enchanting, unlearning, DE fee/vendor floor and missing materials.
- Immutable history, disjoint stacking, realm isolation, settled bag/equipment events and GUID deduplication.
- All versus oldest-50-plus-unpriced queues, material dependencies, quote age, throttling, paging, wrong-item responses, incomplete caches, timeouts and competing searches.
- Modern item/commodity and TBC legacy search adapters, schema-1 upgrades, native menu widget wiring and stacked line coordinates.
- Valuation/price SQLite views and CSV exports.

## First live-client check

Use small amounts and record expected results before the video series begins:

1. Enable script errors (`/console scriptErrors 1`), log in, open `/fl`, then `/reload`. Verify the ledger survives and no diagnostic is created.
2. Loot money, finish a quest and buy/sell a cheap item. Check exact copper against wallet deltas and inspect reconciliation.
3. Try an unsuccessful purchase, cancel a trade and cancel mail before sending. None should become a confirmed expense/income solely because of the click.
4. Send a known amount between your accounts, including postage; collect it and import both files twice. Check no duplicate records and no internal-transfer income. Repeat with a direct trade in both directions.
5. Post one auction and cancel it; collect the returned item. Verify a single deposit loss. Let a second expire, including while logged out.
6. Sell an auction. Verify gross price, AH commission, returned deposit and collected wallet amount against the mail invoice. Repeat with commodities/partial purchases and Postal/open-all if used.
7. Post identical lots, cancel one and relist. Inspect match confidence rather than assuming exact identity. Test several fast vendor sales and combined gold updates.
8. Open bags, bank, mailbox and owned auctions. Verify complete/partial flags, item quantities and price units. Move items across locations and inspect timestamps for stale overlap.
9. Check estimates with and without Auctionator. Unknown prices must not become zero-value claims. Recheck sold-awaiting-delivery versus uncollected mail to avoid counting the same proceeds twice.
10. Import both SavedVariables into SQLite. Verify reported balances, fees, unresolved records and totals independently. Keep the input files as test fixtures for future regressions.
11. Clear the marker with `/fl end`, reload, and accept/decline the prompt. A set marker must persist and suppress the next prompt. Declining must not stop tracking.
12. At the AH, run both scan modes; compare several unit prices manually. Test no listings, multiple pages, another search, closing the AH and a temporary disconnect. Never treat a timeout as a zero quote.
13. Scan a cheap BoE, equip it, then unequip it. Auction-item value must disappear permanently. Repeat with an enchanter and a non-enchanter; only the bound item's owner grants DE eligibility. Check missing material prices and vendor-dominant items.
14. Verify chart presets and custom stacking, hover values, small-screen scaling and saved selection. Gold + assets + equipment must equal total exactly. Current price changes must not alter earlier points.

TBC Anniversary can cover steps 1–4 and 8–14 plus available sale invoice fields. Its legacy auction-ID lifecycle is outside this preview, so steps 5–7 still require Forever. Outland DE outcomes are not modeled. Native rendering in either client remains untested; the widget tests are mocks, not screenshots from a running game.

Do not describe the preview as tracking every source perfectly until these checks pass against the actual client. All observed gold differences are retained; detailed source attribution and auction matching can remain incomplete and explicitly flagged.
