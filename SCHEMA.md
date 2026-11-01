# Record format — schema 1

The SavedVariables root is `ForeverLedgerDB`. The immutable `events` array is the source of truth. `characters`, `auctions`, settings and UI caches are derived conveniences; database imports use the events.

Every record contains:

| Field | Meaning |
|---|---|
| `schema` | Schema version, currently 1 |
| `sourceID` | Generated once per account's saved database |
| `sequence` | Monotonic source-local integer, starting at 1 |
| `id` | `sourceID:sequence`; never regenerated during export |
| `character`, `characterName`, `realm` | Character GUID and readable identity |
| `time` | Observation time, server Unix seconds |
| `session` | Session-start record ID, absent on that start record |
| `episode` | Optional user label |
| `kind`, `data` | Event type and immutable payload |

`time` is when an event was observed, not necessarily when an offline sale happened. Money is integer copper. Missing fields mean unknown/not applicable, not zero. Empty Lua tables export as `{}`; consumers should normalize `{}` to `[]` for known array fields such as empty `rows` or `events`.

## Event families

| Kind | Important payloads |
|---|---|
| `baseline` | `balance`, `previous`, `gap` |
| `balance` | `before`, `after`, `delta`, interaction `context` |
| `intent` | `category`, expected signed `amount`, action `details` |
| `activity` | `category`, signed `amount`, `confidence`, transaction details |
| `reconciliation` | `balanceIDs`, `activityIDs`, `observed`, `explained`, `residual`, `status` |
| `auction_post_intent` | Requested item, quantity, deposit estimate, price, duration |
| `auction_posted` | `key`, `auctionID`, character, item, quantity, `deposit`, `totalPrice` |
| `auction_outcome` | `auctionKey`, `outcome`, `depositLost`, `confidence`, evidence ID |
| `auction_sale` | Item, quantity, `gross`, `commission`, `depositRefund`, collected `money`, optional auction match |
| `auction_purchase_invoice` | Purchase cost evidence; does not create another wallet expense |
| `auction_return` | Returned item, quantity, expiration/cancellation and optional allocation |
| `mail_sent`, `mail_collected` | Counterparty, money, items, postage/COD where available |
| `snapshot` | Location, rows, completeness, location-specific metadata |
| `price` | Realm/faction/client `scope`, variant `key`, item and quote (`price`, `updatedAt`, source, status) |
| `valuation` | Account/scope `gold`, `assets`, `equipped`, `total`, `unpricedRows`, per-character subtotals/snapshot ages, model and fee assumption |
| `professions` | Owner's observed Enchanting presence, skill and capability availability |
| `price_scan_start`, `price_scan_end`, `price_scan_error` | Scan mode, progress and termination/failure reason |
| `valuation_settings` | Estimated commission in basis points |
| `loot_message`, `loot_money_message`, `quest_item` | Supporting activity evidence |
| `session`, `logout`, `episode_start`, `episode_end`, `owner`, `account_label` | Lifecycle/configuration history |
| `diagnostic`, `capability_missing` | Collector errors and unavailable interfaces |

`auction_posted.totalPrice` is a total for the posting. Commodity unit prices are multiplied by quantity; item-auction buyout amounts are already totals. A multisell posting creates one `auction_posted` per auction, each with its share of the quantity and deposit. Returned auction deposits are kept separate from commissions.

A `snapshot` is written when a location's contents change, or on an explicit refresh; an unchanged rescan writes nothing. Likewise a `valuation` is written only when a value or snapshot completeness changes.

An intent alone is not a transaction. Confirmed event activity can precede or follow `PLAYER_MONEY`; the collector waits for a two-second quiet window before writing a reconciliation record. A unique amount match becomes `correlated_amount`; an exact sum of multiple pending intents becomes `correlated_batch`. Neither is a server-confirmed cause. Ambiguous or stale candidates remain intents. Unresolved windows are retained even if later windows happen to offset them.

## Auction confidence

- `server_id`: the server event identified the auction.
- `ordered_confirmation`: a successful creation event was paired with the pending posting queue.
- `inferred_unique`: one known posting matched the invoice/return details.
- `allocated_fifo`: more than one posting matched; earliest observed posting was allocated deterministically.
- `unmatched`: no posting met the matching criteria; no deposit loss is invented.

Item report grouping uses item ID where available and otherwise item name. This is an item-type summary, not a guaranteed individual-item or random-suffix profit report. Full links remain in the raw records for later variant-aware analysis.

## Database integration

The SQLite `events.raw` field preserves the complete event JSON. `events.data` preserves the payload. Views supplied: `cash_movements`, `activities`, `reconciliation`, `auction_sales`, `auction_outcomes`, `snapshots`, `valuations`, `prices`. Sources and ownership are stored separately.

Version 0.2 adds event families without rewriting schema-1 records. `markets` (catalog/prices by client, realm and faction) and `history` (chart samples) are SavedVariables caches. All new estimates are exported through immutable events. Item rows include `bound`, `equipped`, optional instance `guid` and a `valuation` as of the snapshot; later price events may change the current valuation without rewriting that snapshot. A valuation's `total` already includes gold, assets and equipped salvage. Do not stack or sum that total with those components, or sum historical samples. Latest account valuations remain separate by source/scope in reports; cross-account transfers can cause stale overlaps until both sides refresh.

Import is append-only and transactional per input file. Repeated identical IDs are ignored. Different contents for an existing ID abort the file's import. Source sequence gaps are flagged in reports. Restoring an old SavedVariables backup and continuing to record can reuse IDs; preserve the conflicting files and investigate rather than editing away the conflict.

For later analysis, use immutable events as facts, explicit attribution/allocation records as interpretations, and price snapshots as estimates. Never add activity cash amounts to the authoritative balance deltas. Likewise, do not treat `auction_sale` plus its corresponding `activity` as two sales.
