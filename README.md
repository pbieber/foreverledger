# Forever Ledger 0.1.0 — development preview

A standalone WoW Forever addon for recording gold movements, economic activity, inventory and auctions across a gold-making video series. A companion Python importer merges both accounts into one SQLite database and produces JSON reports and CSV tables.

Built on the assumption that the published Forever APIs and the interfaces used by existing addons function. This release has automated Lua 5.1 and Python tests, but has **not been loaded or validated in a live Forever client**. Start recording from your first login and keep the original data for later reconciliation.

## Install on both accounts

1. Extract the ZIP. Copy the **ForeverLedger** folder into the active Forever client's `Interface/AddOns` directory. The final path must be `Interface/AddOns/ForeverLedger/ForeverLedger.toc`.
2. Enable Forever Ledger on every character you want to record. If both accounts use the same game installation, installing the addon once is enough; each account keeps separate SavedVariables.
3. On the main account run `/fl account Main`. On the second run `/fl account Bank`.
4. Register characters across the accounts with `/fl own Character-Realm`. Use normalized realm names without spaces. Logged-in characters are registered automatically; the database combines ownership from both exports.
5. Use `/fl episode Episode 1 - Starting out` before recording and `/fl end` afterwards. Set the same episode label on both accounts if you want their work grouped together.
6. Open your bank, mailbox and the AH's owned-auctions view to populate those snapshots. `/fl scan` refreshes currently accessible locations. Information for offline characters is explicitly last-observed data.

The addon does not buy, sell, mail, trade or cancel anything. It observes user actions and requests owned-auction data when the AH opens. No external network service is used.

## Commands and display

| Command | Purpose |
|---|---|
| `/fl` or `/foreverledger` | Account balances, collection health and current character's valuation snapshots |
| `/fl account Main` | Label the current account's data source |
| `/fl own Character-Realm` | Mark another character as yours |
| `/fl episode My episode` | Begin an episode label |
| `/fl end` | Finish the episode |
| `/fl scan` | Record bags, accessible bank/mail/auctions |
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

Add `--watch` to keep merging whenever WoW saves either account. Stop with Ctrl+C. This is synchronization into the local database, **not in-game account-to-account communication**. Files on another computer must first be made available locally. The addon window displays the local account only.

Alternatively, copy each `/fl export <page>` into a UTF-8 JSON file and import those files with the same command. Reimporting or overlapping export pages is safe. A conflicting event ID causes that file's import to roll back instead of overwriting data. The report flags missing sequence ranges. For larger histories, the complete SavedVariables file is easier than copying pages.

## What is recorded

- Every observed `PLAYER_MONEY` balance delta, opening/login balances, unexplained login gaps and reconciliation windows.
- Quest reward money and item evidence; loot money messages and item chat messages, with zone/map context where available.
- Confirmed trades with both directions of money and item transfers.
- Mail sends, postage, COD, collections and auction invoice components. Mail bodies are not recorded.
- Vendor purchase/sale/buyback intents, junk-selling intents, repairs, flights and training. A matching balance change is required before these become classified activities, with a correlation label rather than a false claim of server-confirmed causality.
- Confirmed auction postings, deposits, server auction IDs, exact cancellation/expiration events when provided, sale invoices, commission, returned deposits and auction return evidence.
- Bags, equipment, accessible character bank, visible mailbox and owned-auction snapshots. Partial mailbox/AH results are marked partial. Items carry item links/IDs and vendor values when available.
- Optional Auctionator price observations for item estimates. Missing prices remain unpriced; an observation timestamp is not the underlying Auctionator scan timestamp. No market scan is initiated by this addon.

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

**Inventory valuation:** last-observed snapshots are not a synchronized world state. An item can appear in an old bank/mail snapshot and a newer bag snapshot after being moved. The tool intentionally does not produce a supposedly exact combined net-worth figure from those snapshots. Equipment is separate from saleable stock, and bound/unpriced items should not be treated as auction inventory. Asking prices are not guaranteed sale prices. Mail money and sold-auction snapshots may refer to the same proceeds.

**Scope:** character wallets and accessible character storage are covered. Guild/warband holdings, detailed crafting material transformations, automatic acquisition-lot provenance and in-game cross-account synchronization are not implemented. Unusual purchase/refund paths, drag-to-vendor sales and repairs not caught by a specific hook still appear in wallet changes but may need manual attribution. The tool does not claim a retrospective, complete history.

**No live validation:** see TESTING.md for the first-client checks. Journalator may be run in parallel as a comparison; this addon does not depend on or read its data.

## Source and development

The package includes the addon source, database importer, automated tests and SCHEMA.md. Tests use `lupa`'s Lua 5.1 runtime; production importing needs no third-party Python packages.

```powershell
python -m pip install lupa
python -m unittest discover -s .\ForeverLedger-tools\tests -v
```

API reference: [published Forever UI/API source](https://github.com/Gethe/wow-ui-source/tree/ca8368f2f2380cbe696854f7f2646387c278a61b), particularly `AuctionHouseDocumentation.lua`, `ContainerDocumentation.lua`, `MailInfoDocumentation.lua` and `TradeInfoDocumentation.lua`.

Event-handling reference: [Journalator source](https://github.com/TheMouseNest/Journalator/tree/c6166ead2801d93cde0dbb1d09b0410ad4316b8d). This package is a separate implementation; Journalator is not bundled.

## Repository workflow

Repository: https://github.com/pbieber/foreverledger

From the repository root:

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s ForeverLedger-tools/tests -v
python scripts/package.py
```

The package is written to `dist/`. GitHub Actions runs the tests and packaging check on pushes and pull requests. Gameplay exports and database files should remain local.
