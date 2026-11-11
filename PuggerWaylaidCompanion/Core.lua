--[[
Pugger Waylaid Companion: Craftsman's Writs, Waylaid Crates and where they go.

This file is the part with no frames in it: the lists the pages and the map draw from,
what the player holds, and what is done for today. UI.lua is the window, Overview.lua its
first page, Map.lua the world map markers, Minimap.lua the minimap button, and Learn.lua
notes down turn-ins the shipped data does not know yet.
]]

local ADDON, ns = ...

ns.TITLE = "Pugger Waylaid Companion"
ns.ICON = "Interface/AddOns/PuggerWaylaidCompanion/Media/pugger"

-- Writ tiers by index, as Data/Writs.lua stores them.
ns.WRIT_TIERS = { "Journeyman", "Expert", "Artisan" }
ns.WRIT_REP = { 75, 125, 200 }
-- Crate tiers have one more rung below.
ns.CRATE_TIERS = { "Apprentice", "Journeyman", "Expert", "Artisan" }

ns.PROFESSIONS = { "Alchemy", "Blacksmithing", "Engineering", "Leatherworking", "Tailoring" }

-- Tier colours: the game's uncommon, rare and epic for the three writ tiers.
ns.WRIT_COLOR = { "ff1eff00", "ff0070dd", "ffa335ee" }
ns.CRATE_COLOR = { "ffffffff", "ff1eff00", "ff0070dd", "ffa335ee" }

function ns.Color(hex, text)
  return "|c" .. hex .. text .. "|r"
end

-- ---------------------------------------------------------------------------
-- The game's functions, under whichever name this client has them
-- ---------------------------------------------------------------------------

local GetItemInfo = GetItemInfo or (C_Item and C_Item.GetItemInfo)
local GetItemCount = GetItemCount or (C_Item and C_Item.GetItemCount)
local GetItemIcon = GetItemIcon or (C_Item and C_Item.GetItemIconByID)
local IsQuestDone = (C_QuestLog and C_QuestLog.IsQuestFlaggedCompleted) or IsQuestFlaggedCompleted

--- An item's name and icon. The name is the game's once it has loaded the item, until
--- then the one from the data.
function ns.Item(id, fallback)
  local name, _, _, _, _, _, _, _, _, icon
  if GetItemInfo then name, _, _, _, _, _, _, _, _, icon = GetItemInfo(id) end
  if not icon and GetItemIcon then icon = GetItemIcon(id) end
  return name or fallback or ("item " .. id), icon or "Interface/Icons/INV_Misc_QuestionMark"
end

--- How many of an item are in the bags (not the bank).
function ns.Count(id)
  return GetItemCount and GetItemCount(id) or 0
end

local function character()
  local name = UnitName and UnitName("player") or "?"
  return name .. "-" .. (GetRealmName and GetRealmName() or "?")
end

--- How many of an item this character has, and where: { bags, bank, mail, total,
--- mailSeen }. The bank count is the game's own, kept from the last visit. The mailbox
--- is what was in it when it was last open; mailSeen is false until it has been opened.
function ns.Holdings(id)
  local bags = ns.Count(id)
  local bank = math.max(0, (GetItemCount and GetItemCount(id, true) or bags) - bags)
  local seen = ns.db and ns.db.mail and ns.db.mail[character()]
  local mail = seen and seen[id] or 0
  return { bags = bags, bank = bank, mail = mail, total = bags + bank + mail, mailSeen = seen ~= nil }
end

local mailOpen = false
--- Note what the open mailbox holds, per item. Only the mails the game lists are counted.
local function scanMail()
  if not mailOpen or not ns.db or not GetInboxNumItems or not GetInboxItem then return end
  local held = {}
  for index = 1, GetInboxNumItems() or 0 do
    for slot = 1, ATTACHMENTS_MAX_RECEIVE or 16 do
      local _, id, _, count = GetInboxItem(index, slot)
      if type(id) ~= "number" then
        local link = GetInboxItemLink and GetInboxItemLink(index, slot)
        id = link and tonumber(link:match("item:(%d+)"))
      end
      if id then held[id] = (held[id] or 0) + (tonumber(count) or 1) end
    end
  end
  ns.db.mail[character()] = held
end

-- ---------------------------------------------------------------------------
-- Prices
-- ---------------------------------------------------------------------------

local function auctionator()
  local api = Auctionator and Auctionator.API and Auctionator.API.v1
  return api and api.GetAuctionPriceByItemID and api or nil
end

--- Whether there is anything to ask for prices (Auctionator).
function ns.HasPrices()
  return auctionator() ~= nil
end

--- What one of an item costs on the auction house, in copper, as Auctionator last saw
--- it; nil when it has no price for it.
function ns.Price(id)
  local api = auctionator()
  if not api then return nil end
  local ok, price = pcall(api.GetAuctionPriceByItemID, ADDON, id)
  if ok and type(price) == "number" and price > 0 then return price end
  return nil
end

--- Copper as coloured "12g 34s 56c", leaving out the parts that are zero.
function ns.Money(copper)
  copper = math.floor(copper + 0.5)
  local gold, silver, rest = math.floor(copper / 10000), math.floor(copper / 100) % 100, copper % 100
  local parts = {}
  if gold > 0 then parts[#parts + 1] = ns.Color("ffffd100", gold .. "g") end
  if silver > 0 then parts[#parts + 1] = ns.Color("ffc7c7cf", silver .. "s") end
  if rest > 0 or #parts == 0 then parts[#parts + 1] = ns.Color("ffeda55f", rest .. "c") end
  return table.concat(parts, " ")
end

--- What a writ costs to do from nothing: { writ, each, material (each x count), total
--- (of the parts with a price), partial (a part has none) }.
function ns.WritCost(writ)
  local paper, each = ns.Price(writ.writItem), ns.Price(writ.item)
  local material = each and each * writ.count
  return {
    writ = paper, each = each, material = material,
    total = (paper or 0) + (material or 0), partial = not (paper and material),
  }
end

--- What a crate costs to fill from nothing, with the cheapest of its bundles that has a
--- price: { crate, bundle (nil when none has a price), material, total, partial }.
function ns.CrateCost(crate)
  local box = ns.Price(crate.item)
  local bundle, material
  for _, b in ipairs(crate.bundles) do
    local each = ns.Price(b.item)
    if each and (not material or each * b.count < material) then
      bundle, material = b, each * b.count
    end
  end
  return {
    crate = box, bundle = bundle, material = material,
    total = (box or 0) + (material or 0), partial = not (box and material),
  }
end

--- True once a writ's quest has been handed in today. The writs are daily quests, so
--- the game's "completed" flag for one clears at the daily reset.
function ns.DoneToday(quest)
  return IsQuestDone and IsQuestDone(quest) and true or false
end

-- "A" or "H", nil before the game knows (or for a neutral character).
function ns.Side()
  local group = UnitFactionGroup and UnitFactionGroup("player")
  if group == "Alliance" then return "A" end
  if group == "Horde" then return "H" end
  return nil
end

-- ---------------------------------------------------------------------------
-- Writs
-- ---------------------------------------------------------------------------

ns.writs = {}
ns.writByQuest = {}
for _, row in ipairs(ns.WRITS) do
  local writ = {
    quest = row[1], writItem = row[2], item = row[3], count = row[4],
    profession = row[5], tier = row[6], skill = row[7], npc = row[8], side = row[9],
    name = row[10],
  }
  ns.writs[#ns.writs + 1] = writ
  ns.writByQuest[writ.quest] = writ
end

-- What players have recorded in game and scripts/bake_waylaid.py has written into
-- Data/Recorded.lua: places (an NPC id, or "at:map:x:y" for a spot nobody has named yet)
-- and which writ goes to which.
for id, place in pairs(ns.RECORDED_NPCS or {}) do
  if not ns.WRIT_NPCS[id] then ns.WRIT_NPCS[id] = place end
end
for quest, id in pairs(ns.RECORDED_WRITS or {}) do
  local writ = ns.writByQuest[quest]
  if writ and not writ.npc and ns.WRIT_NPCS[id] then writ.npc = id end
end

--- Whether the player's side can do a writ. A few are limited to one side.
function ns.ForPlayer(writ)
  local side = ns.Side()
  return writ.side == nil or side == nil or writ.side == side
end

--- Where a writ is handed in: { id, name, map, x, y, zone }, from the shipped data or
--- from what this account has recorded; nil when neither knows.
function ns.WritNpc(writ)
  local db = ns.db
  -- A shipped NPC first, then what this account recorded, then a shipped unnamed spot.
  local id = (type(writ.npc) == "number" and writ.npc) or (db and db.writNpc[writ.quest]) or writ.npc
  if not id then return nil end
  local n = (db and db.npcs[id]) or ns.WRIT_NPCS[id]
  if not n then return nil end
  return { id = id, name = n[1], map = n[2], x = n[3], y = n[4], zone = n[5] }
end

local continents = {}
--- The continent a map is on: its name and map id ("Elsewhere", 0 when the game can't say).
function ns.Continent(map)
  local known = continents[map]
  if known then return known[1], known[2] end
  local name, id = "Elsewhere", 0
  local at, steps = map, 0
  while at and at > 0 and steps < 10 and C_Map and C_Map.GetMapInfo do
    local info = C_Map.GetMapInfo(at)
    if not info then break end
    if info.mapType == 2 then
      name, id = info.name, at
      break
    end
    at, steps = info.parentMapID, steps + 1
  end
  if id ~= 0 then continents[map] = { name, id } end
  return name, id
end

--- "holding" the writ, and "ready" when the requested items are in the bags too.
function ns.WritState(writ)
  if ns.DoneToday(writ.quest) then return "done" end
  if ns.Count(writ.writItem) > 0 then
    if ns.Count(writ.item) >= writ.count then return "ready" end
    return "holding"
  end
  return "open"
end

--- Every place writs are handed in, each with its writs (the player's side only),
--- sorted by zone then name: { npc = {...}, writs = {...}, open = n, held = n }.
function ns.Stops()
  local byId, stops = {}, {}
  for _, writ in ipairs(ns.writs) do
    local npc = ns.ForPlayer(writ) and ns.WritNpc(writ)
    if npc then
      local stop = byId[npc.id]
      if not stop then
        stop = { npc = npc, writs = {}, open = 0, held = 0 }
        byId[npc.id] = stop
        stops[#stops + 1] = stop
      end
      stop.writs[#stop.writs + 1] = writ
      local state = ns.WritState(writ)
      if state ~= "done" then stop.open = stop.open + 1 end
      if state == "holding" or state == "ready" then stop.held = stop.held + 1 end
    end
  end
  for _, stop in ipairs(stops) do
    table.sort(stop.writs, function(a, b)
      if a.tier ~= b.tier then return a.tier < b.tier end
      return a.name < b.name
    end)
  end
  table.sort(stops, function(a, b)
    if a.npc.zone ~= b.npc.zone then return a.npc.zone < b.npc.zone end
    return a.npc.name < b.npc.name
  end)
  return stops
end

--- How many of the player's writs have a known turn-in, and how many there are.
function ns.KnownTurnIns()
  local known, total = 0, 0
  for _, writ in ipairs(ns.writs) do
    if ns.ForPlayer(writ) then
      total = total + 1
      if ns.WritNpc(writ) then known = known + 1 end
    end
  end
  return known, total
end

-- ---------------------------------------------------------------------------
-- Crates
-- ---------------------------------------------------------------------------

ns.crates = {}
for _, row in ipairs(ns.CRATES) do
  local crate = { item = row[1], tier = row[2], kind = row[3], name = row[4], bundles = {} }
  for _, b in ipairs(row[5]) do
    crate.bundles[#crate.bundles + 1] = { item = b[1], count = b[2], name = b[3] }
  end
  ns.crates[#ns.crates + 1] = crate
end

--- The Merchant's Favor a filled crate of a tier pays, as the amounts known for it,
--- smallest first: from the shipped data and from what this account has seen paid.
--- Empty when nobody knows yet.
function ns.CrateFavor(tier)
  local seen, amounts = {}, {}
  local function add(n)
    if n and not seen[n] then
      seen[n] = true
      amounts[#amounts + 1] = n
    end
  end
  for _, n in ipairs(ns.CRATE_FAVOR[tier] or {}) do add(n) end
  for _, source in ipairs({ ns.RECORDED_FAVOR or {}, ns.db and ns.db.favor or {} }) do
    for key, paid in pairs(source) do
      if ns.SealedTier(key) == tier then
        for amount, times in pairs(paid) do
          -- A turn-in has a small chance to pay double: leave out an amount that is
          -- twice another and rare next to it.
          local half = paid[amount / 2]
          if not (half and half > times * 4) then add(amount) end
        end
      end
    end
  end
  table.sort(amounts)
  return amounts
end

--- The player's crate turn-in: { id, name, map, x, y, zone, faction }, nil for no side.
function ns.Camp()
  local c = ns.CAMPS[ns.Side() or ""]
  if not c then return nil end
  return { id = c[1], name = c[2], map = c[3], x = c[4], y = c[5], zone = c[6], faction = c[7] }
end

-- ---------------------------------------------------------------------------
-- Reputation
-- ---------------------------------------------------------------------------

-- The trade factions' ids, and how much reputation each standing (1 Hated .. 7 Revered)
-- holds before the next.
local FACTION_ID = { A = 2586, H = 2587 }
local STANDING_SIZE = { 36000, 3000, 3000, 3000, 6000, 12000, 21000 }
local STANDING_NAME = { "Hated", "Hostile", "Unfriendly", "Neutral", "Friendly", "Honored", "Revered", "Exalted" }
local EXALTED = 8

local function readFaction(id)
  if not id then return nil end
  if C_Reputation and C_Reputation.GetFactionDataByID then
    local d = C_Reputation.GetFactionDataByID(id)
    if d and d.name then
      return d.name, d.reaction, d.currentReactionThreshold, d.nextReactionThreshold, d.currentStanding
    end
  end
  if GetFactionInfoByID then
    local name, _, standing, low, high, value = GetFactionInfoByID(id)
    if name then return name, standing, low, high, value end
  end
  return nil
end

function ns.StandingName(standing)
  return _G["FACTION_STANDING_LABEL" .. standing] or STANDING_NAME[standing] or "?"
end

--- The player's standing with their trade faction: { name, standing, low, high, value
--- (reputation in total, with low and high the ends of the current standing), toNext,
--- toExalted, exalted, unknown (the game has no standing yet) }. nil for no side.
function ns.Reputation()
  local camp = ns.Camp()
  if not camp then return nil end
  -- The side's own id first; the other one in case the ids are the other way round.
  local side = ns.Side()
  local standing, low, high, value
  for _, id in ipairs({ FACTION_ID[side], FACTION_ID[side == "A" and "H" or "A"] }) do
    local n, s, l, h, v = readFaction(id)
    if n == camp.faction then
      standing, low, high, value = s, l, h, v
      break
    end
  end
  local rep = { name = camp.faction }
  if standing and low and high and value then
    rep.standing, rep.low, rep.high, rep.value = standing, low, high, value
  else
    rep.standing, rep.low, rep.high, rep.value, rep.unknown = 4, 0, 3000, 0, true
  end
  rep.exalted = rep.standing >= EXALTED
  if rep.exalted then
    rep.toNext, rep.toExalted = 0, 0
  else
    rep.toNext = math.max(0, rep.high - rep.value)
    rep.toExalted = rep.toNext
    for s = rep.standing + 1, EXALTED - 1 do rep.toExalted = rep.toExalted + STANDING_SIZE[s] end
  end
  return rep
end

--- What is left to hand in today, per writ tier and in all:
--- { [tier] = { open, total, rep }, open = n, total = n, rep = n }.
function ns.Today()
  local today = { open = 0, total = 0, rep = 0 }
  for tier = 1, #ns.WRIT_TIERS do today[tier] = { open = 0, total = 0, rep = 0 } end
  for _, writ in ipairs(ns.writs) do
    if ns.ForPlayer(writ) then
      local t = today[writ.tier]
      t.total, today.total = t.total + 1, today.total + 1
      if not ns.DoneToday(writ.quest) then
        local gain = ns.WRIT_REP[writ.tier]
        t.open, today.open = t.open + 1, today.open + 1
        t.rep, today.rep = t.rep + gain, today.rep + gain
      end
    end
  end
  return today
end

-- ---------------------------------------------------------------------------
-- Saved settings, and telling the pages something changed
-- ---------------------------------------------------------------------------

local DEFAULTS = { page = "overview", writSort = "level", crateSort = "level", pins = true }

local listeners = {}
--- Call fn whenever what the pages show may have changed (bags, quests, item names).
function ns.OnChange(fn)
  listeners[#listeners + 1] = fn
end

local pending = false
--- Tell the listeners, once, shortly: bag and item events come in bursts.
function ns.Changed()
  if pending then return end
  pending = true
  C_Timer.After(0.2, function()
    pending = false
    for _, fn in ipairs(listeners) do fn() end
  end)
end

local loaded = {}
--- Call fn once the saved settings are in ns.db.
function ns.WhenLoaded(fn)
  loaded[#loaded + 1] = fn
end

if not CreateFrame then return end

-- Events that mean a writ's quest, or its point on the map, may have just arrived.
local QUEST_EVENTS = { PLAYER_ENTERING_WORLD = true, QUEST_ACCEPTED = true, QUEST_LOG_UPDATE = true, QUEST_POI_UPDATE = true }

local events = CreateFrame("Frame")
for _, event in ipairs({ "ADDON_LOADED", "PLAYER_LOGIN", "BAG_UPDATE", "QUEST_TURNED_IN", "GET_ITEM_INFO_RECEIVED",
  "UPDATE_FACTION", "QUEST_COMPLETE", "CHAT_MSG_CURRENCY", "PLAYER_ENTERING_WORLD", "QUEST_ACCEPTED", "QUEST_LOG_UPDATE", "QUEST_POI_UPDATE",
  "MAIL_SHOW", "MAIL_INBOX_UPDATE", "MAIL_CLOSED", "BANKFRAME_OPENED", "PLAYERBANKSLOTS_CHANGED" }) do
  -- Registering an event this client does not have is an error.
  pcall(events.RegisterEvent, events, event)
end
events:SetScript("OnEvent", function(_, event, arg1)
  if event == "ADDON_LOADED" then
    if arg1 ~= ADDON then return end
    PuggerWaylaidCompanionDB = PuggerWaylaidCompanionDB or {}
    local db = PuggerWaylaidCompanionDB
    for key, value in pairs(DEFAULTS) do
      if db[key] == nil then db[key] = value end
    end
    db.npcs = db.npcs or {}
    db.writNpc = db.writNpc or {}
    db.minimap = db.minimap or { angle = 215, hide = false }
    db.favor = db.favor or {}
    db.mail = db.mail or {}
    ns.db = db
    for _, fn in ipairs(loaded) do fn() end
    return
  end
  -- The inbox only fills in after MAIL_SHOW, and reads as empty once it is closed.
  if event == "MAIL_SHOW" then mailOpen = true return end
  if event == "MAIL_CLOSED" then mailOpen = false return end
  if event == "MAIL_INBOX_UPDATE" then scanMail() end
  if QUEST_EVENTS[event] and ns.LocateSoon then ns.LocateSoon() end
  if event == "QUEST_COMPLETE" then return ns.CrateOffered and ns.CrateOffered() end
  if event == "CHAT_MSG_CURRENCY" then return ns.CurrencyPaid and ns.CurrencyPaid(arg1) end
  if event == "QUEST_TURNED_IN" and ns.Learn then
    ns.Learn(arg1)
    ns.CrateHandedIn(arg1)
  end
  ns.Changed()
  -- The completed flag can trail the turn-in by a moment.
  if event == "QUEST_TURNED_IN" then C_Timer.After(1.5, ns.Changed) end
end)

SLASH_PUGGERWAYLAID1 = "/pwc"
SLASH_PUGGERWAYLAID2 = "/waylaid"
SlashCmdList.PUGGERWAYLAID = function(msg)
  msg = (msg or ""):lower():match("^%s*(.-)%s*$")
  if msg == "map" or msg == "pins" then
    ns.db.pins = not ns.db.pins
    print(ns.TITLE .. ": map markers " .. (ns.db.pins and "shown" or "hidden") .. ".")
    ns.Changed()
  elseif msg == "minimap" then
    ns.db.minimap.hide = not ns.db.minimap.hide
    print(ns.TITLE .. ": minimap button " .. (ns.db.minimap.hide and "hidden" or "shown") .. ".")
    if ns.MinimapRefresh then ns.MinimapRefresh() end
  elseif msg == "where" then
    ns.Where()
  elseif ns.Toggle then
    ns.Toggle(msg ~= "" and msg or nil)
  end
end

function PuggerWaylaidCompanion_OnAddonCompartmentClick()
  if ns.Toggle then ns.Toggle() end
end
