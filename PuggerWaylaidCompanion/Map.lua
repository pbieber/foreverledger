--[[
Markers on the world map: one for each NPC that takes Craftsman's Writs, and one for the
player's crate camp. Hovering a marker lists the writs handed in there and whether each
is still available today.

The markers are plain frames on the map's canvas, placed by hand, so nothing here goes
through the map's own pin pools (which want XML templates and are easy to taint). On a
zone's own map a marker sits at its zone coordinates; on a continent map those are
converted through world coordinates.
]]

local _, ns = ...
if not CreateFrame or not WorldMapFrame then return end

local SIZE = 22
local CONTINENT = 2 -- Enum.UIMapType.Continent

local pins = {}

local function canvas()
  if WorldMapFrame.GetCanvas then return WorldMapFrame:GetCanvas() end
  return WorldMapFrame.ScrollContainer and WorldMapFrame.ScrollContainer.Child
end

--- Where a zone position (0-100) falls on the shown map, as 0-1; nil if it does not.
local function place(map, x, y, shown)
  x, y = x / 100, y / 100
  if map == shown then return x, y end
  if not (C_Map and C_Map.GetWorldPosFromMapPos and C_Map.GetMapPosFromWorldPos and CreateVector2D) then return nil end
  local info = C_Map.GetMapInfo(shown)
  if not info or info.mapType ~= CONTINENT then return nil end
  local ok, continent, world = pcall(C_Map.GetWorldPosFromMapPos, map, CreateVector2D(x, y))
  if not ok or not world then return nil end
  local ok2, _, pos = pcall(C_Map.GetMapPosFromWorldPos, continent, world, shown)
  if not ok2 or not pos then return nil end
  local px, py = pos:GetXY()
  if not px or px < 0 or px > 1 or py < 0 or py > 1 then return nil end
  return px, py
end

local function showTooltip(pin)
  local stop = pin.stop
  GameTooltip:SetOwner(pin, "ANCHOR_RIGHT")
  GameTooltip:AddLine(stop.npc.name, 1, 0.82, 0)
  GameTooltip:AddLine(("%s  %.1f, %.1f"):format(stop.npc.zone, stop.npc.x, stop.npc.y), 0.7, 0.7, 0.7)

  if stop.camp then
    GameTooltip:AddLine(stop.npc.faction, 1, 1, 1)
    GameTooltip:AddLine("Hand in filled Waylaid Crates here.", 0.8, 0.8, 0.8)
    local held = 0
    for _, crate in ipairs(ns.crates) do held = held + ns.Count(crate.item) end
    if held > 0 then
      GameTooltip:AddLine(("%d unfilled crate%s in bags"):format(held, held == 1 and "" or "s"), 1, 0.82, 0)
    end
  else
    if stop.open > 0 then
      GameTooltip:AddLine(("Daily turn-ins available: %d of %d"):format(stop.open, #stop.writs), 0.25, 0.82, 0.25)
    else
      GameTooltip:AddLine("All turn-ins here are done for today", 0.5, 0.5, 0.5)
    end
    GameTooltip:AddLine(" ")
    for _, writ in ipairs(stop.writs) do
      local state = ns.WritState(writ)
      local right, r, g, b = "Available", 0.25, 0.82, 0.25
      if state == "done" then
        right, r, g, b = "Done today", 0.5, 0.5, 0.5
      elseif state == "ready" then
        right, r, g, b = "Ready to hand in", 0.25, 1, 0.25
      elseif state == "holding" then
        right, r, g, b = "Writ in bags", 1, 0.82, 0
      end
      local name = ns.Item(writ.item, writ.name)
      if writ.count > 1 then name = writ.count .. " x " .. name end
      GameTooltip:AddDoubleLine(
        ns.Color(ns.WRIT_COLOR[writ.tier], name) .. ns.Color("ff808080", "  " .. ns.WRIT_TIERS[writ.tier]),
        right, 1, 1, 1, r, g, b)
    end
  end
  GameTooltip:Show()
end

local function makePin(parent)
  local pin = CreateFrame("Frame", nil, parent)
  pin:SetSize(SIZE, SIZE)
  pin:EnableMouse(true)
  pin.disc = pin:CreateTexture(nil, "BACKGROUND")
  pin.disc:SetTexture("Interface/Minimap/UI-Minimap-Background")
  pin.disc:SetPoint("TOPLEFT", -2, 2)
  pin.disc:SetPoint("BOTTOMRIGHT", 2, -2)
  pin.icon = pin:CreateTexture(nil, "ARTWORK")
  pin.icon:SetAllPoints()
  pin.icon:SetTexCoord(0.08, 0.92, 0.08, 0.92)
  -- A ring that lights up when the player is carrying a writ for this place.
  pin.glow = pin:CreateTexture(nil, "OVERLAY")
  pin.glow:SetTexture("Interface/Buttons/UI-ActionButton-Border")
  pin.glow:SetBlendMode("ADD")
  pin.glow:SetPoint("CENTER")
  pin.glow:SetSize(SIZE * 2, SIZE * 2)
  pin.glow:SetVertexColor(0.3, 1, 0.3)
  pin:SetScript("OnEnter", showTooltip)
  pin:SetScript("OnLeave", function() GameTooltip:Hide() end)
  return pin
end

local function refresh()
  local parent = canvas()
  if not parent or not WorldMapFrame:IsShown() then return end
  local used = 0
  local shown = ns.db and ns.db.pins and WorldMapFrame.GetMapID and WorldMapFrame:GetMapID()

  if shown then
    local stops = ns.Stops()
    local camp = ns.Camp()
    if camp then
      stops[#stops + 1] = { npc = camp, camp = true, writs = {}, open = 1, held = 0 }
    end
    -- The canvas grows as the map zooms in; shrink the markers back so they stay one size.
    local zoom = parent:GetScale()
    if not zoom or zoom <= 0 then zoom = 1 end
    local width, height = parent:GetWidth(), parent:GetHeight()

    for _, stop in ipairs(stops) do
      local x, y = place(stop.npc.map, stop.npc.x, stop.npc.y, shown)
      if x then
        used = used + 1
        local pin = pins[used]
        if not pin then
          pin = makePin(parent)
          pins[used] = pin
        end
        pin.stop = stop
        -- Above the map's own pins, in whatever strata the map is in.
        pin:SetFrameLevel(math.min(9000, parent:GetFrameLevel() + 3000))
        pin:SetScale(1 / zoom)
        pin:ClearAllPoints()
        pin:SetPoint("CENTER", parent, "TOPLEFT", x * width * zoom, -y * height * zoom)
        pin.icon:SetTexture(stop.camp and "Interface/Icons/INV_Crate_01" or "Interface/Icons/INV_Misc_Note_01")
        local done = stop.open == 0
        if pin.icon.SetDesaturated then pin.icon:SetDesaturated(done) end
        pin.icon:SetAlpha(done and 0.6 or 1)
        pin.glow:SetShown(stop.held > 0)
        pin:Show()
      end
    end
  end
  for i = used + 1, #pins do pins[i]:Hide() end
end

WorldMapFrame:HookScript("OnShow", refresh)
if WorldMapFrame.OnMapChanged then hooksecurefunc(WorldMapFrame, "OnMapChanged", refresh) end
if WorldMapFrame.OnCanvasScaleChanged then hooksecurefunc(WorldMapFrame, "OnCanvasScaleChanged", refresh) end
ns.OnChange(refresh)
