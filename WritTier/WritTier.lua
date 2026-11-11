local _, ns = ...

local PREFIX = "^Craftsman's Writ: (.+)$"

local COLORS = {
  Journeyman = { 0.12, 1.00, 0.00 },
  Expert     = { 0.00, 0.44, 0.87 },
  Artisan    = { 0.64, 0.21, 0.93 },
}

-- Returns the lines to add for an item name, or nil if it isn't a Craftsman's Writ.
function ns.Describe(name)
  local item = name and name:match(PREFIX)
  if not item then return nil end
  local w = ns.writs[item:lower()]
  if not w then
    return { left = "Writ tier: unknown", color = { 0.6, 0.6, 0.6 } }
  end
  return {
    left = w.tier .. " writ",
    right = "+" .. ns.reputation[w.tier] .. " reputation",
    color = COLORS[w.tier],
    detail = w.profession .. " " .. w.skill,
  }
end

local function Annotate(tooltip)
  if not tooltip or tooltip.writTierShown or not tooltip.GetItem then return end
  local name = tooltip:GetItem()
  local d = ns.Describe(name)
  if not d then return end
  tooltip.writTierShown = true
  local r, g, b = unpack(d.color)
  if d.right then
    tooltip:AddDoubleLine(d.left, d.right, r, g, b, 1, 0.82, 0)
  else
    tooltip:AddLine(d.left, r, g, b)
  end
  if d.detail then
    tooltip:AddLine("Made with " .. d.detail, 0.8, 0.8, 0.8)
  end
  tooltip:Show()
end

local function Cleared(tooltip)
  tooltip.writTierShown = nil
end

local hooked = {}
local function WatchClear(tooltip)
  if tooltip and not hooked[tooltip] and tooltip.HookScript then
    hooked[tooltip] = true
    tooltip:HookScript("OnTooltipCleared", Cleared)
  end
end

if TooltipDataProcessor and TooltipDataProcessor.AddTooltipPostCall and Enum and Enum.TooltipDataType then
  TooltipDataProcessor.AddTooltipPostCall(Enum.TooltipDataType.Item, function(tooltip)
    WatchClear(tooltip)
    Annotate(tooltip)
  end)
else
  for _, tooltip in ipairs({ GameTooltip, ItemRefTooltip, ShoppingTooltip1, ShoppingTooltip2 }) do
    WatchClear(tooltip)
    tooltip:HookScript("OnTooltipSetItem", Annotate)
  end
end
