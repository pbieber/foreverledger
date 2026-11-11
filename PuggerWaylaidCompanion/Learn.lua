--[[
Most writs' turn-ins are in nobody's data yet (25 of 150 when this was written), and the
game only tells the client where one is once its quest is in the log: the server sends
the map point then, the same one the world map marks. So there are two moments to learn:

  - when a writ's quest is in the quest log, read its map point and keep it. The place has
    no name yet, so it is kept as a "Writ customer" at that spot, or filed under an NPC
    already known to stand there;
  - when a writ is handed in, note who took it (the quest giver is the "npc" unit while
    its window is open) and give the spot its name.

Kept per account in the saved settings, and used wherever the shipped data has nothing.
A noted spot is stored like an NPC, under a text key ("at:map:x:y") instead of an NPC id.
]]

local _, ns = ...

local UNNAMED = "Writ customer"
-- Two map points this close (in map percent) are the same place.
local NEAR = 1.0

local function npcId(guid)
  if not guid then return nil end
  local kind, _, _, _, _, id = strsplit("-", guid)
  if kind ~= "Creature" and kind ~= "Vehicle" and kind ~= "GameObject" then return nil end
  return tonumber(id)
end

local function inLog(quest)
  if C_QuestLog and C_QuestLog.IsOnQuest then return C_QuestLog.IsOnQuest(quest) end
  if GetQuestLogIndexByID then return (GetQuestLogIndexByID(quest) or 0) > 0 end
  return true
end

-- ---------------------------------------------------------------------------
-- Reading a quest's map point
-- ---------------------------------------------------------------------------

local zoneList
--- Every zone map of the two continents.
local function zones()
  if zoneList then return zoneList end
  local list, seen = {}, {}
  if C_Map and C_Map.GetMapChildrenInfo then
    for _, continent in ipairs({ 1414, 1415 }) do
      local ok, children = pcall(C_Map.GetMapChildrenInfo, continent, 3, true)
      if ok and children then
        for _, child in ipairs(children) do
          if not seen[child.mapID] then
            seen[child.mapID] = true
            list[#list + 1] = child.mapID
          end
        end
      end
    end
  end
  if #list == 0 then
    -- The classic zone maps, by id.
    for id = 1411, 1458 do
      if id ~= 1414 and id ~= 1415 then list[#list + 1] = id end
    end
    return list -- not kept: the map data may not have been ready yet
  end
  zoneList = list
  return list
end

--- Every quest the zone maps mark: [quest] = { { map, x, y }, ... } with x and y as 0-1.
--- A zone's map is a rectangle that takes in the edges of its neighbours, and the game
--- lists a quest on every map whose rectangle holds its point: one in northern Un'Goro is
--- also listed for Thousand Needles, in that map's bottom left corner. So a quest can
--- have several points, all the same place, and only one names the zone it is in.
local function questPoints()
  local found = {}
  if not (C_QuestLog and C_QuestLog.GetQuestsOnMap) then return found end
  for _, map in ipairs(zones()) do
    local ok, quests = pcall(C_QuestLog.GetQuestsOnMap, map)
    if ok and quests then
      for _, q in ipairs(quests) do
        local id, x, y = q.questID, q.x, q.y
        if id and x and y and x > 0 and x < 1 and y > 0 and y < 1 then
          found[id] = found[id] or {}
          table.insert(found[id], { map, x, y })
        end
      end
    end
  end
  return found
end

local ZONE = 3 -- Enum.UIMapType.Zone

--- The zone a map point really lies in, and the point on that zone's own map: map, x, y
--- (0-1). nil when the game can't say. A zone map only knows itself, so this asks the
--- continent map, which is how the game tells which zone the cursor is over.
local function settle(map, x, y)
  if not (C_Map and C_Map.GetMapInfoAtPosition and C_Map.GetWorldPosFromMapPos
    and C_Map.GetMapPosFromWorldPos and CreateVector2D) then return nil end
  local _, continent = ns.Continent(map)
  if continent == 0 then return nil end
  local ok, instance, world = pcall(C_Map.GetWorldPosFromMapPos, map, CreateVector2D(x, y))
  if not ok or not world then return nil end
  local ok2, _, at = pcall(C_Map.GetMapPosFromWorldPos, instance, world, continent)
  if not ok2 or not at then return nil end
  local ok3, info = pcall(C_Map.GetMapInfoAtPosition, continent, at:GetXY())
  if not ok3 or not info or info.mapType ~= ZONE then return nil end
  if info.mapID == map then return map, x, y end
  local ok4, _, pos = pcall(C_Map.GetMapPosFromWorldPos, instance, world, info.mapID)
  if not ok4 or not pos then return nil end
  local px, py = pos:GetXY()
  if not px or px <= 0 or px >= 1 or py <= 0 or py >= 1 then return nil end
  return info.mapID, px, py
end

--- The one of a quest's map points to keep: map, x, y (0-1).
local function pick(spots)
  for _, s in ipairs(spots) do
    local map, x, y = settle(s[1], s[2], s[3])
    if map then return map, x, y end
  end
  -- The game would not say. A point in a neighbour's margin is near that map's edge, so
  -- take the map that has it furthest from one.
  local best, margin
  for _, s in ipairs(spots) do
    local m = math.min(s[2], 1 - s[2], s[3], 1 - s[3])
    if not best or m > margin then best, margin = s, m end
  end
  return best[1], best[2], best[3]
end

--- Where the game would send the player next for a quest: map, x, y (0-1), or nil.
local function waypoint(quest)
  if not (C_QuestLog and C_QuestLog.GetNextWaypoint) then return nil end
  local ok, map, x, y = pcall(C_QuestLog.GetNextWaypoint, quest)
  if ok and map and x and y and x > 0 and x < 1 and y > 0 and y < 1 then return map, x, y end
  return nil
end

--- The id of a known place (shipped NPC, learned NPC or noted spot) at a map point,
--- other than the one given.
local function placeAt(map, x, y, except)
  local function near(n) return n[2] == map and math.abs(n[3] - x) < NEAR and math.abs(n[4] - y) < NEAR end
  for id, n in pairs(ns.WRIT_NPCS) do
    if id ~= except and near(n) then return id end
  end
  for id, n in pairs(ns.db.npcs) do
    if id ~= except and near(n) then return id end
  end
  return nil
end

local function round(v) return math.floor(v * 10000 + 0.5) / 100 end

local function spotId(map, x, y) return ("at:%d:%d:%d"):format(map, x * 10, y * 10) end

--- Move a kept place { name, map, x, y, zone } to the zone it really lies in. Returns
--- whether it moved.
local function resettle(n)
  local map, x, y = settle(n[2], n[3] / 100, n[4] / 100)
  if not map or map == n[2] then return false end
  local info = C_Map.GetMapInfo(map)
  n[2], n[3], n[4], n[5] = map, round(x), round(y), info and info.name or n[5]
  return true
end

--- Put right the places kept before the zone was checked: those were filed under whichever
--- map listed the quest first. A corrected shipped recording is kept in the saved settings
--- too, which is where scripts/bake_waylaid.py picks it up.
function ns.Resettle()
  local db = ns.db
  if not db then return 0 end
  local moved, renamed = 0, {}
  for id, n in pairs(db.npcs) do
    if resettle(n) then
      moved = moved + 1
      if type(id) == "string" then renamed[id] = n end
    end
  end
  local corrected = {}
  for id, n in pairs(ns.RECORDED_NPCS or {}) do
    if resettle(n) and not db.npcs[id] then
      moved = moved + 1
      corrected[id] = { n[1], n[2], n[3], n[4], n[5] }
    end
  end
  for id, n in pairs(corrected) do
    db.npcs[id] = n
    if type(id) == "string" then renamed[id] = n end
  end
  -- A noted spot is filed under its map and point, so it moves; it may also turn out to
  -- be a place already known.
  for old, n in pairs(renamed) do
    db.npcs[old] = nil
    local id = placeAt(n[2], n[3], n[4], old)
    if not id then
      id = spotId(n[2], n[3], n[4])
      db.npcs[id] = n
    end
    for _, writ in ipairs(ns.writs) do
      if type(writ.npc) ~= "number" and (db.writNpc[writ.quest] or writ.npc) == old then
        db.writNpc[writ.quest] = id
      end
    end
  end
  if moved > 0 then
    print(("%s: corrected the zone of %d recorded writ turn-in%s."):format(ns.TITLE, moved, moved == 1 and "" or "s"))
    ns.Changed()
  end
  return moved
end

--- Look at the writs in the quest log and keep the map point of any with no known
--- turn-in. Returns how many were newly noted.
function ns.Locate()
  local db = ns.db
  if not db then return 0 end
  local wanted = {}
  for _, writ in ipairs(ns.writs) do
    if not ns.WritNpc(writ) and inLog(writ.quest) then wanted[#wanted + 1] = writ end
  end
  if #wanted == 0 then return 0 end

  local points, noted = questPoints(), 0
  for _, writ in ipairs(wanted) do
    local map, x, y
    local spots = points[writ.quest]
    if spots then
      map, x, y = pick(spots)
    else
      map, x, y = waypoint(writ.quest)
      if map then map, x, y = pick({ { map, x, y } }) end
    end
    if map then
      x, y = round(x), round(y)
      local id = placeAt(map, x, y)
      if not id then
        id = spotId(map, x, y)
        local info = C_Map.GetMapInfo(map)
        db.npcs[id] = { UNNAMED, map, x, y, info and info.name or "" }
      end
      db.writNpc[writ.quest] = id
      noted = noted + 1
      local n = ns.WRIT_NPCS[id] or db.npcs[id]
      print(("%s: noted where Craftsman's Writ: %s is handed in (%s %.1f, %.1f)."):format(
        ns.TITLE, writ.name, n[5], n[3], n[4]))
    end
  end
  if noted > 0 then ns.Changed() end
  return noted
end

local pending, resettled = false, false
--- Locate shortly, once: quest events come in bursts, and the map point can arrive a
--- moment after the quest does.
function ns.LocateSoon()
  if pending or not ns.db then return end
  pending = true
  C_Timer.After(1, function()
    pending = false
    if not resettled then
      resettled = true
      ns.Resettle()
    end
    ns.Locate()
  end)
end

--- /pwc where: say what the game reports for each writ in the quest log, for when a
--- turn-in is not picked up.
function ns.Where()
  ns.Resettle()
  local points, any = questPoints(), false
  for _, writ in ipairs(ns.writs) do
    if inLog(writ.quest) then
      any = true
      local spots = points[writ.quest]
      local p = spots and { pick(spots) }
      local wm, wx, wy = waypoint(writ.quest)
      local npc = ns.WritNpc(writ)
      print(("%s (quest %d): map point %s, waypoint %s, kept as %s"):format(
        writ.name, writ.quest,
        p and ("%d %.1f, %.1f (on %d maps)"):format(p[1], p[2] * 100, p[3] * 100, #spots) or "none",
        wm and ("%d %.1f, %.1f"):format(wm, wx * 100, wy * 100) or "none",
        npc and ("%s, %s %.1f, %.1f"):format(npc.name, npc.zone, npc.x, npc.y) or "nothing"))
    end
  end
  if not any then print(ns.TITLE .. ": no Craftsman's Writ quest is in your quest log.") end
  ns.Locate()
end

-- ---------------------------------------------------------------------------
-- Naming a place at the hand-in
-- ---------------------------------------------------------------------------

--- Called with the quest just handed in.
function ns.Learn(quest)
  local writ = ns.writByQuest[quest]
  local db = ns.db
  if not writ or type(writ.npc) == "number" or not db then return end
  local old = db.writNpc[quest]
  if type(old) == "number" then return end
  old = old or writ.npc

  local id = npcId(UnitGUID("npc")) or npcId(UnitGUID("target"))
  local name = UnitName("npc") or UnitName("target")
  if not (id and name) then return end

  local spot = old and (db.npcs[old] or ns.WRIT_NPCS[old])
  if spot then
    -- The spot was noted from the quest's map point: keep the point, add the name, and
    -- move every writ filed under the spot over to the NPC.
    if not ns.WRIT_NPCS[id] and not db.npcs[id] then
      db.npcs[id] = { name, spot[2], spot[3], spot[4], spot[5] }
    end
    db.npcs[old] = nil
    for _, other in ipairs(ns.writs) do
      if type(other.npc) ~= "number" and (db.writNpc[other.quest] or other.npc) == old then
        db.writNpc[other.quest] = id
      end
    end
  else
    local map = C_Map and C_Map.GetBestMapForUnit and C_Map.GetBestMapForUnit("player")
    local pos = map and C_Map.GetPlayerMapPosition(map, "player")
    if not pos then return end
    local x, y = pos:GetXY()
    if not x or (x == 0 and y == 0) then return end
    local info = C_Map.GetMapInfo(map)
    if not ns.WRIT_NPCS[id] then
      db.npcs[id] = { name, map, round(x), round(y), info and info.name or "" }
    end
    db.writNpc[quest] = id
  end
  print(("%s: noted %s as the turn-in for Craftsman's Writ: %s."):format(ns.TITLE, name, writ.name))
end

-- ---------------------------------------------------------------------------
-- What a filled crate pays
-- ---------------------------------------------------------------------------

-- Nobody has published the Merchant's Favor for every tier, so note it at the camp: which
-- sealed crate left the bags, and the currency the game then says was paid. Kept as
-- db.favor[sealed crate item][amount] = times seen.

local offered  -- the sealed crates in the bags when the camp's hand-in window opened
local paid     -- { amount, time } of the last Merchant's Favor the game announced
local WINDOW = 4

local function sealedCounts()
  local counts = {}
  for item = ns.SEALED_FIRST, ns.SEALED_LAST do counts[item] = ns.Count(item) end
  return counts
end

--- The hand-in window of a quest opened: remember the crates if this is the camp.
function ns.CrateOffered()
  local camp = ns.Camp()
  if camp and npcId(UnitGUID("npc")) == camp.id then offered = sealedCounts() end
end

--- The game announced a currency gain.
function ns.CurrencyPaid(message)
  if type(message) ~= "string" or not message:find("Favor") then return end
  paid = { tonumber(message:match("|h|r%s*x(%d+)")) or 1, GetTime() }
end

--- A quest was handed in: if a sealed crate went with it, note what it paid.
function ns.CrateHandedIn(quest)
  local before = offered
  if not before or not ns.db then return end
  offered = nil
  local at = GetTime()
  C_Timer.After(1.5, function()
    if not paid or math.abs(paid[2] - at) > WINDOW then return end
    local amount, key = paid[1], "q" .. quest
    paid = nil
    for item, count in pairs(sealedCounts()) do
      if count < before[item] then key = item end
    end
    local seen = ns.db.favor[key] or {}
    ns.db.favor[key] = seen
    seen[amount] = (seen[amount] or 0) + 1
    local tier = ns.SealedTier(key)
    print(("%s: noted %d Merchant's Favor for %s."):format(ns.TITLE, amount,
      tier and ("a Sealed " .. (ns.CRATE_TIERS[tier] or "Elite") .. " Crate") or ("quest " .. quest)))
    ns.Changed()
  end)
end
