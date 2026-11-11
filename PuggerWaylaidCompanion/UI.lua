--[[
The window: a menu down the left, a page on the right.

  Overview           - reputation and what is left today (Overview.lua)
  Craftsman's Writs  - every writ, by level or by profession
  Waylaid Crates     - every crate and what fills it, by level or by profession
  Turn-ins           - where writs and crates go; the same places Map.lua marks

Each list page builds plain entries ({ header = ... } or { cells = {...} }) and hands them
to one shared list, which draws them with pooled rows.
]]

local _, ns = ...
if not CreateFrame then return end

local WIDTH, HEIGHT, MENU = 860, 560, 170
local ROW = 20
local GREY, GOLD, GREEN = "ff808080", "ffffd100", "ff40d040"

local window, list, sortBar, note, overview
local pages = {}

-- ---------------------------------------------------------------------------
-- The shared list
-- ---------------------------------------------------------------------------

local function showTooltip(row)
  local entry = row.entry
  if not entry then return end
  if entry.item then
    GameTooltip:SetOwner(row, "ANCHOR_RIGHT")
    if GameTooltip.SetItemByID then
      GameTooltip:SetItemByID(entry.item)
    else
      GameTooltip:SetHyperlink("item:" .. entry.item)
    end
    if entry.tip then GameTooltip:AddLine(entry.tip, 0.8, 0.8, 0.8, true) end
    GameTooltip:Show()
  elseif entry.tip then
    GameTooltip:SetOwner(row, "ANCHOR_RIGHT")
    GameTooltip:AddLine(entry.tip, 1, 1, 1, true)
    GameTooltip:Show()
  end
end

local function makeRow(parent)
  local row = CreateFrame("Button", nil, parent)
  row:SetHeight(ROW)
  row.stripe = row:CreateTexture(nil, "BACKGROUND")
  row.stripe:SetAllPoints()
  row.icon = row:CreateTexture(nil, "ARTWORK")
  row.icon:SetSize(ROW - 4, ROW - 4)
  row.cells = {}
  for i = 1, 5 do
    local text = row:CreateFontString(nil, "ARTWORK", "GameFontHighlightSmall")
    text:SetJustifyH("LEFT")
    text:SetWordWrap(false)
    row.cells[i] = text
  end
  row:SetHighlightTexture("Interface/QuestFrame/UI-QuestTitleHighlight", "ADD")
  row:SetScript("OnEnter", showTooltip)
  row:SetScript("OnLeave", function() GameTooltip:Hide() end)
  row:SetScript("OnClick", function(self)
    if self.entry and self.entry.click then self.entry.click() end
  end)
  return row
end

local function makeList(parent)
  local l = {}
  l.scroll = CreateFrame("ScrollFrame", "PuggerWaylaidCompanionScroll", parent, "UIPanelScrollFrameTemplate")
  l.child = CreateFrame("Frame", nil, l.scroll)
  l.child:SetSize(10, 10)
  l.scroll:SetScrollChild(l.child)
  l.rows = {}

  --- Draw entries. `columns` is the left edge of each cell, the last entry the width.
  function l:Set(entries, columns)
    local width = columns[#columns]
    self.child:SetWidth(width)
    for i, entry in ipairs(entries) do
      local row = self.rows[i]
      if not row then
        row = makeRow(self.child)
        self.rows[i] = row
      end
      row.entry = entry
      row:SetWidth(width)
      row:ClearAllPoints()
      row:SetPoint("TOPLEFT", 0, -(i - 1) * ROW)
      local indent = entry.indent or 0
      if entry.header then
        row.stripe:SetColorTexture(1, 0.82, 0, 0.12)
        row.icon:Hide()
        row.cells[1]:ClearAllPoints()
        row.cells[1]:SetPoint("LEFT", 6, 0)
        row.cells[1]:SetWidth(width - 12)
        row.cells[1]:SetFontObject("GameFontNormal")
        row.cells[1]:SetText(entry.header)
        for c = 2, 5 do row.cells[c]:SetText("") end
      else
        row.stripe:SetColorTexture(1, 1, 1, i % 2 == 0 and 0.04 or 0)
        if entry.icon then
          row.icon:SetTexture(entry.icon)
          row.icon:ClearAllPoints()
          row.icon:SetPoint("LEFT", 4 + indent, 0)
          row.icon:Show()
        else
          row.icon:Hide()
        end
        for c = 1, 5 do
          local cell = row.cells[c]
          local x = columns[c]
          local value = entry.cells[c]
          if x and c < #columns and value then
            local left = x + (c == 1 and indent + ROW + 4 or 0)
            cell:ClearAllPoints()
            cell:SetPoint("LEFT", left, 0)
            cell:SetWidth(columns[c + 1] - left - 6)
            cell:SetFontObject("GameFontHighlightSmall")
            cell:SetText(value)
          else
            cell:SetText("")
          end
        end
      end
      row:EnableMouse(not entry.header)
      row:Show()
    end
    for i = #entries + 1, #self.rows do self.rows[i]:Hide() end
    self.child:SetHeight(math.max(1, #entries * ROW))
  end
  return l
end

-- ---------------------------------------------------------------------------
-- Pages
-- ---------------------------------------------------------------------------

local STATE_TEXT = {
  done = ns.Color(GREY, "Done today"),
  ready = ns.Color(GREEN, "Ready to hand in"),
  holding = ns.Color(GOLD, "Writ in bags"),
  open = "",
}

local function turnInText(writ)
  local npc = ns.WritNpc(writ)
  if not npc then return ns.Color(GREY, "Accept the writ to record") end
  return ("%s, %s"):format(npc.name, npc.zone)
end

local function writEntry(writ, byLevel)
  local name, icon = ns.Item(writ.item, writ.name)
  if writ.count > 1 then name = writ.count .. " x " .. name end
  local npc = ns.WritNpc(writ)
  local second
  if byLevel then
    second = ("%s %d"):format(writ.profession, writ.skill)
  else
    second = ns.Color(ns.WRIT_COLOR[writ.tier], ns.WRIT_TIERS[writ.tier]) .. " " .. writ.skill
  end
  local tip = "Craftsman's Writ: " .. writ.name
  if npc then
    tip = tip .. ("\nHand in to %s, %s (%.1f, %.1f). Click to open the map."):format(npc.name, npc.zone, npc.x, npc.y)
  else
    tip = tip .. "\nTurn-in not known yet. It is saved when you accept the writ's quest."
  end
  if writ.side then
    tip = tip .. "\n" .. (writ.side == "A" and "Alliance only." or "Horde only.")
  end
  return {
    icon = icon,
    item = writ.item,
    tip = tip,
    cells = {
      ns.Color(ns.WRIT_COLOR[writ.tier], name),
      second,
      "+" .. ns.WRIT_REP[writ.tier],
      turnInText(writ),
      STATE_TEXT[ns.WritState(writ)],
    },
    click = npc and function() ns.OpenMap(npc.map) end or nil,
  }
end

local WRIT_COLUMNS = { 0, 220, 345, 390, 560, 650 }

pages.writs = {
  title = "Craftsman's Writs",
  sortKey = "writSort",
  build = function()
    local byLevel = ns.db.writSort == "level"
    local sorted = {}
    for _, writ in ipairs(ns.writs) do
      if ns.ForPlayer(writ) then sorted[#sorted + 1] = writ end
    end
    table.sort(sorted, function(a, b)
      if byLevel then
        if a.tier ~= b.tier then return a.tier < b.tier end
        if a.profession ~= b.profession then return a.profession < b.profession end
      else
        if a.profession ~= b.profession then return a.profession < b.profession end
        if a.tier ~= b.tier then return a.tier < b.tier end
      end
      if a.skill ~= b.skill then return a.skill < b.skill end
      return a.name < b.name
    end)
    local entries, last = {}, nil
    for _, writ in ipairs(sorted) do
      local group = byLevel and writ.tier or writ.profession
      if group ~= last then
        last = group
        if byLevel then
          entries[#entries + 1] = { header = ("%s  (+%d reputation each)"):format(ns.WRIT_TIERS[writ.tier], ns.WRIT_REP[writ.tier]) }
        else
          entries[#entries + 1] = { header = writ.profession }
        end
      end
      entries[#entries + 1] = writEntry(writ, byLevel)
    end
    local known, total = ns.KnownTurnIns()
    return entries, WRIT_COLUMNS,
      ("Each writ can be handed in once a day. Turn-in known for %d of %d; the rest are saved when you accept the writ."):format(known, total)
  end,
}

local CRATE_COLUMNS = { 0, 290, 400, 500, 650 }

--- The Merchant's Favor column for a crate tier, and the line for its tooltip.
local function favorText(tier)
  local amounts = ns.CrateFavor(tier)
  if #amounts == 0 then
    return ns.Color(GREY, "Favor not known yet"),
      "Nobody has recorded the Merchant's Favor for this tier yet. It is saved when you deliver one."
  end
  local text = table.concat(amounts, " or ") .. " Favor"
  if #amounts > 1 then
    return text, "Merchant's Favor: " .. table.concat(amounts, " or ")
      .. ", depending on the crate's quality (an uncommon, green crate pays more than a common one)."
  end
  return text, "Merchant's Favor: " .. amounts[1] .. "."
end

pages.crates = {
  title = "Waylaid Crates",
  sortKey = "crateSort",
  build = function()
    local byLevel = ns.db.crateSort == "level"
    local kindOrder = {}
    for i, kind in ipairs(ns.CRATE_KINDS) do kindOrder[kind] = i end
    local sorted = {}
    for _, crate in ipairs(ns.crates) do sorted[#sorted + 1] = crate end
    table.sort(sorted, function(a, b)
      if byLevel then
        if a.tier ~= b.tier then return a.tier < b.tier end
        if a.kind ~= b.kind then return kindOrder[a.kind] < kindOrder[b.kind] end
      else
        if a.kind ~= b.kind then return kindOrder[a.kind] < kindOrder[b.kind] end
        if a.tier ~= b.tier then return a.tier < b.tier end
      end
      return a.name < b.name
    end)
    local entries, last = {}, nil
    for _, crate in ipairs(sorted) do
      local group = byLevel and crate.tier or crate.kind
      if group ~= last then
        last = group
        if byLevel then
          entries[#entries + 1] = { header = ("%s  (level %d)"):format(ns.CRATE_TIERS[crate.tier], ns.CRATE_LEVEL[crate.tier]) }
        else
          entries[#entries + 1] = { header = ("%s  (%s)"):format(crate.kind, ns.CRATE_SKILL[crate.kind]) }
        end
      end
      local _, icon = ns.Item(crate.item)
      local held = ns.Count(crate.item)
      local favor, favorTip = favorText(crate.tier)
      entries[#entries + 1] = {
        icon = icon,
        item = crate.item,
        tip = "Requires one of the items listed below it.\n" .. favorTip,
        cells = {
          ns.Color(ns.CRATE_COLOR[crate.tier], "Waylaid Crate: " .. crate.name),
          byLevel and ns.CRATE_SKILL[crate.kind] or ("Level " .. ns.CRATE_LEVEL[crate.tier]),
          held > 0 and ns.Color(GOLD, held .. " in bags") or "",
          favor,
        },
      }
      for _, bundle in ipairs(crate.bundles) do
        local name, bundleIcon = ns.Item(bundle.item, bundle.name)
        local have = ns.Count(bundle.item)
        local color = have >= bundle.count and GREEN or (have > 0 and GOLD or GREY)
        entries[#entries + 1] = {
          icon = bundleIcon,
          item = bundle.item,
          indent = 22,
          cells = {
            ("%d x %s"):format(bundle.count, name),
            ns.Color(color, ("%d / %d"):format(have, bundle.count)),
            "",
          },
        }
      end
    end
    local camp = ns.Camp()
    local where = camp and ("Filled crates are delivered to %s at the %s camp, %s (%.1f, %.1f)."):format(camp.name, camp.faction, camp.zone, camp.x, camp.y)
      or "Filled crates are delivered to your faction's camp."
    return entries, CRATE_COLUMNS, "A crate requires one of the items listed. " .. where
  end,
}

local STOP_COLUMNS = { 0, 230, 400, 480, 650 }

pages.turnins = {
  title = "Turn-ins",
  build = function()
    local entries = {}
    local camp = ns.Camp()
    if camp then
      entries[#entries + 1] = { header = "Waylaid Crates" }
      entries[#entries + 1] = {
        icon = "Interface/Icons/INV_Crate_01",
        tip = camp.faction .. "\nClick to open the map.",
        cells = { camp.name, camp.zone, ("%.1f, %.1f"):format(camp.x, camp.y), "All filled crates" },
        click = function() ns.OpenMap(camp.map) end,
      }
    end
    -- Writ turn-ins, a continent at a time.
    local stops = ns.Stops()
    local order = {}
    for i, stop in ipairs(stops) do
      stop.continent = ns.Continent(stop.npc.map)
      order[stop] = i
    end
    table.sort(stops, function(x, y)
      if x.continent ~= y.continent then
        -- Whatever the game can't place goes last.
        if x.continent == "Elsewhere" then return false end
        if y.continent == "Elsewhere" then return true end
        return x.continent < y.continent
      end
      return order[x] < order[y]
    end)
    local continent
    for _, stop in ipairs(stops) do
      if stop.continent ~= continent then
        continent = stop.continent
        entries[#entries + 1] = { header = "Craftsman's Writs: " .. continent }
      end
      local npc = stop.npc
      local names = {}
      for _, writ in ipairs(stop.writs) do
        local state = ns.WritState(writ)
        names[#names + 1] = ns.Color(ns.WRIT_COLOR[writ.tier], writ.name)
          .. (state == "done" and ns.Color(GREY, " (done today)") or "")
      end
      local status
      if stop.open == 0 then
        status = ns.Color(GREY, "All done today")
      elseif stop.held > 0 then
        status = ns.Color(GREEN, ("%d writ%s in bags"):format(stop.held, stop.held == 1 and "" or "s"))
      else
        status = ("%d of %d available"):format(stop.open, #stop.writs)
      end
      entries[#entries + 1] = {
        icon = "Interface/Icons/INV_Misc_Note_01",
        tip = npc.name .. "\n" .. table.concat(names, "\n") .. "\nClick to open the map.",
        cells = { npc.name, npc.zone, ("%.1f, %.1f"):format(npc.x, npc.y), status },
        click = function() ns.OpenMap(npc.map) end,
      }
    end
    local known, total = ns.KnownTurnIns()
    return entries, STOP_COLUMNS,
      ("These places are marked on the world map (/pwc map hides the markers). %d of %d writ turn-ins are known so far."):format(known, total)
  end,
}

pages.overview = { title = "Overview" }

local MENU_ORDER = { "overview", "writs", "crates", "turnins" }

-- ---------------------------------------------------------------------------
-- The window
-- ---------------------------------------------------------------------------

--- Open the world map on a zone.
function ns.OpenMap(mapID)
  if InCombatLockdown and InCombatLockdown() then
    print(ns.TITLE .. ": the map can't be opened from here in combat.")
    return
  end
  if not WorldMapFrame:IsShown() then ToggleWorldMap() end
  if WorldMapFrame.SetMapID then WorldMapFrame:SetMapID(mapID) end
end

local function refresh()
  if not window or not window:IsShown() then return end
  local key = ns.db.page
  local page = pages[key] or pages.overview
  window.heading:SetText(page.title)
  for id, button in pairs(window.menu) do
    if id == key then button:LockHighlight() else button:UnlockHighlight() end
  end

  if page.build then
    local entries, columns, text = page.build()
    list:Set(entries, columns)
    note:SetText(text or "")
    list.scroll:Show()
    overview:Hide()
  else
    list.scroll:Hide()
    note:SetText("")
    overview:Show()
    overview:Refresh()
  end

  if page.sortKey then
    sortBar.key = page.sortKey
    local byLevel = ns.db[page.sortKey] == "level"
    sortBar.level:SetEnabled(not byLevel)
    sortBar.profession:SetEnabled(byLevel)
    sortBar:Show()
  else
    sortBar:Hide()
  end
end

local function build()
  window = CreateFrame("Frame", "PuggerWaylaidCompanionWindow", UIParent, "BasicFrameTemplateWithInset")
  window:SetSize(WIDTH, HEIGHT)
  window:SetPoint("CENTER")
  window:SetFrameStrata("HIGH")
  window:SetMovable(true)
  window:EnableMouse(true)
  window:SetClampedToScreen(true)
  window:RegisterForDrag("LeftButton")
  window:SetScript("OnDragStart", window.StartMoving)
  window:SetScript("OnDragStop", window.StopMovingOrSizing)
  window:Hide()
  tinsert(UISpecialFrames, "PuggerWaylaidCompanionWindow")

  local title = window:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
  title:SetPoint("TOP", 0, -5)
  title:SetText(ns.TITLE)

  -- The menu.
  window.menu = {}
  for i, key in ipairs(MENU_ORDER) do
    local button = CreateFrame("Button", nil, window, "UIPanelButtonTemplate")
    button:SetSize(MENU - 20, 26)
    button:SetPoint("TOPLEFT", 14, -34 - (i - 1) * 30)
    button:SetText(pages[key].title)
    button:SetScript("OnClick", function()
      ns.db.page = key
      list.scroll:SetVerticalScroll(0)
      refresh()
    end)
    window.menu[key] = button
  end

  -- The page.
  window.heading = window:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
  window.heading:SetPoint("TOPLEFT", MENU + 10, -38)

  sortBar = CreateFrame("Frame", nil, window)
  sortBar:SetSize(230, 24)
  sortBar:SetPoint("TOPRIGHT", -34, -34)
  local function sortButton(text, value, anchor)
    local button = CreateFrame("Button", nil, sortBar, "UIPanelButtonTemplate")
    button:SetSize(110, 22)
    button:SetPoint(anchor, 0, 0)
    button:SetText(text)
    button:SetScript("OnClick", function()
      ns.db[sortBar.key] = value
      list.scroll:SetVerticalScroll(0)
      refresh()
    end)
    return button
  end
  sortBar.level = sortButton("By level", "level", "LEFT")
  sortBar.profession = sortButton("By profession", "profession", "RIGHT")

  list = makeList(window)
  list.scroll:SetPoint("TOPLEFT", MENU + 8, -66)
  list.scroll:SetPoint("BOTTOMRIGHT", -34, 44)

  note = window:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
  note:SetPoint("BOTTOMLEFT", MENU + 10, 12)
  note:SetPoint("BOTTOMRIGHT", -14, 12)
  note:SetHeight(26)
  note:SetJustifyH("LEFT")
  note:SetJustifyV("MIDDLE")

  overview = ns.BuildOverview(window, WIDTH - MENU - 22)
  overview:SetPoint("TOPLEFT", MENU + 8, -66)
  overview:SetPoint("BOTTOMRIGHT", -14, 14)

  window:SetScript("OnShow", refresh)
end

--- Show or hide the window; with a page name ("writs", "crates", "turnins"), show that page.
function ns.Toggle(page)
  if not ns.db then return end
  if not window then build() end
  if page and pages[page] then
    ns.db.page = page
    window:Show()
    refresh()
  elseif window:IsShown() then
    window:Hide()
  else
    window:Show()
  end
end

ns.OnChange(refresh)
