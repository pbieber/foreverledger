--[[
The button on the minimap: left-click opens the window, right-click shows or hides the
world map markers, dragging moves it round the minimap. /pwc minimap hides it.

Drawn the way minimap buttons are drawn: the game's tracking ring over a dark disc, with
the Pugger icon in the ring's opening.
]]

local _, ns = ...
if not CreateFrame or not Minimap then return end

--- Where the button's centre goes, relative to the minimap's centre, for an angle in
--- degrees: on the circle for a round minimap, pushed out to the edge for a square one.
local function position(degrees, radius, square)
  local a = math.rad(degrees)
  local x, y = math.cos(a), math.sin(a)
  if square then
    local longest = math.max(math.abs(x), math.abs(y))
    x, y = x / longest, y / longest
  end
  return x * radius, y * radius
end

local button = CreateFrame("Button", "PuggerWaylaidCompanionMinimapButton", Minimap)
button:SetSize(31, 31)
button:SetFrameStrata("MEDIUM")
button:SetFrameLevel(8)
button:RegisterForClicks("LeftButtonUp", "RightButtonUp")
button:RegisterForDrag("LeftButton")
button:SetHighlightTexture("Interface/Minimap/UI-Minimap-ZoomButton-Highlight")

-- The ring's opening is not the button's centre: it sits up and to the left of it. The
-- icon covers the dark disc exactly, and the ring hides the icon's corners.
local background = button:CreateTexture(nil, "BACKGROUND")
background:SetTexture("Interface/Minimap/UI-Minimap-Background")
background:SetSize(20, 20)
background:SetPoint("TOPLEFT", 7, -5)

local icon = button:CreateTexture(nil, "ARTWORK")
icon:SetTexture(ns.ICON)
icon:SetSize(20, 20)
icon:SetPoint("TOPLEFT", 7, -5)

local ring = button:CreateTexture(nil, "OVERLAY")
ring:SetTexture("Interface/Minimap/MiniMap-TrackingBorder")
ring:SetSize(53, 53)
ring:SetPoint("TOPLEFT")

local function place()
  local degrees = ns.db and ns.db.minimap.angle or 215
  local square = GetMinimapShape and GetMinimapShape() == "SQUARE"
  -- Just outside the map's edge, where minimap buttons sit.
  local x, y = position(degrees, Minimap:GetWidth() / 2 + 5, square)
  button:ClearAllPoints()
  button:SetPoint("CENTER", Minimap, "CENTER", x, y)
end

local function follow()
  local scale = Minimap:GetEffectiveScale()
  local cx, cy = Minimap:GetCenter()
  local mx, my = GetCursorPosition()
  ns.db.minimap.angle = math.deg(math.atan2(my / scale - cy, mx / scale - cx)) % 360
  place()
end

button:SetScript("OnDragStart", function(self)
  self:SetScript("OnUpdate", follow)
  GameTooltip:Hide()
end)
button:SetScript("OnDragStop", function(self) self:SetScript("OnUpdate", nil) end)

button:SetScript("OnClick", function(_, mouse)
  if mouse == "RightButton" then
    SlashCmdList.PUGGERWAYLAID("map")
  elseif ns.Toggle then
    ns.Toggle()
  end
end)

button:SetScript("OnEnter", function(self)
  GameTooltip:SetOwner(self, "ANCHOR_LEFT")
  GameTooltip:AddLine("|cffffc94aPugger|r Waylaid Companion")
  local today = ns.Today()
  GameTooltip:AddLine(("%d daily turn-ins available, %d reputation"):format(today.open, today.rep), 0.25, 0.82, 0.25)
  GameTooltip:AddLine("Left-click: open", 1, 1, 1)
  GameTooltip:AddLine("Right-click: map markers on or off", 1, 1, 1)
  GameTooltip:AddLine("Drag: move this button", 0.6, 0.6, 0.6)
  GameTooltip:Show()
end)
button:SetScript("OnLeave", function() GameTooltip:Hide() end)

function ns.MinimapRefresh()
  if ns.db.minimap.hide then button:Hide() else button:Show() end
  place()
end

ns.WhenLoaded(ns.MinimapRefresh)
