# Ledger menu

Native WoW frame and fonts; the chart fills the opening page, and the text
audit has its own Summary view. Left-aligned controls and values.

Solid fills that follow the softened lines exactly, with at least 5% headroom above the highest value. The value axis steps by a power of ten in gold. Palette: green #2AA968 for wallet gold, blue #4A9BD8 for unequipped assets,
violet #8F5FDC for Equipped Gear (validated for colorblind separation), ivory
#E8E0CF for labels and charcoal #242424 for the plot. GameFontNormal and
GameFontHighlight retain the client's font and scaling preferences.

```
Forever Ledger                          close
Chart | Summary | Profit | Records | Refresh | Set marker | Sync
Total Value          legend            Total on sale
Total Gold           (3 x 3)            Cost to list
Gain today
This character | All Characters | Characters: n/m | Value v | Type | Category | Character
        stacked history in equal time steps, episode markers
        highlight strip: ivory ticks on the same time axis
first observation                       latest
Scan all prices | Oldest 50 + unpriced | Stop       Mark highlight
scan status and last-observed valuation caveat
```

The window is 644 x 532. Native font sizes stay as they are, so the plot gives up the space rather than the text shrinking. The highlight strip took 14px of plot height for that reason. Highlights never draw on the plot: its ticks are ivory, like labels, so they can't be mistaken for a series.

Summary opens the scrollable account and collection details. Records opens its own view: Recent records | Export JSON | Previous | Next. Sync opens its own view: Add character | Sync now, a status line, then one row per linked account with a progress bar and Unlink. Profit opens its own view: Today | All time, then one row per item category, most profitable first, and a total.

Review: avoid separate decorative statistic cards. The colored boundaries in
one plot explain how total value is composed. Total is a preset, never an
additional series that would double-count gold. Price scans get explicit
names distinct from refreshing inventory. No animated interpolation of data.

Native rendering still requires a client smoke test. Automated tests exercise
the plot geometry, selection, history and native-widget wiring with API mocks.
