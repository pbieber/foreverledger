# Ledger menu

Native WoW frame and fonts; the chart occupies the top half of the ledger,
with a readable text audit below it. Left-aligned controls and values.

Palette: parchment gold #D7B56D for wallet gold, auction blue #65B7DD for
unequipped assets, enchanting violet #B798DF for equipped salvage, ivory
#E8E0CF for labels and charcoal #242424 for the plot. GameFontNormal and
GameFontHighlight retain the client's font and scaling preferences.

```
Forever Ledger                          close
Summary | Records | Export | Prev | Next | Refresh
Gold only | Total value | Gear only
[x] Gold  [x] Other assets  [x] Equipped salvage
        stacked history, copper stored / gold axis
first observation                       latest
Scan all prices | Oldest 50 + unpriced | Stop
scan status and last-observed valuation caveat
scrollable account and collection details
```

Review: avoid separate decorative statistic cards. The colored boundaries in
one plot explain how total value is composed. Total is a preset, never an
additional series that would double-count gold. Price scans get explicit
names distinct from refreshing inventory. No animated interpolation of data.

Native rendering still requires a client smoke test. Automated tests exercise
the plot geometry, selection, history and native-widget wiring with API mocks.
