-- Waylaid Crates on WoW Forever. Crate item ids and levels are from the QuestieDB Forever
-- database; what fills each crate is from wow.gg/guides/merchants-favor and
-- theforeverera.com/en/merchants-favor (checked 2026-11-11). A crate takes ONE of its
-- bundles, not all of them.
local _, ns = ...

-- Where filled crates go: [side] = { npc id, name, uiMapID, x, y, zone, faction }
ns.CAMPS = {
  H = { 256386, "Dokimi", 1413, 50.0, 29.2, "The Barrens", "Durotar Supply and Logistics" },
  A = { 256390, "Marcy Baker", 1433, 9.5, 71.0, "Redridge Mountains", "Azeroth Commerce Authority" },
}

-- The gathering or crafting skill each kind of crate draws on.
ns.CRATE_SKILL = {
  Herbs = "Herbalism",
  Ore = "Mining",
  Ingots = "Mining (smelting)",
  Textiles = "Cloth and Skinning",
  Fabrics = "Tailoring and Leatherworking",
  Curiosities = "Enchanting",
  Parts = "Engineering",
}
ns.CRATE_KINDS = { "Herbs", "Ore", "Ingots", "Textiles", "Fabrics", "Curiosities", "Parts" }

-- { crate item, tier (1 Apprentice, 2 Journeyman, 3 Expert, 4 Artisan), kind, name,
--   { { item, count, name }, ... } }
ns.CRATES = {
  { 248682, 1, "Herbs", "Apprentice Herbs", {
    { 2447, 20, "Peacebloom" }, { 765, 20, "Silverleaf" }, { 2449, 10, "Earthroot" },
    { 785, 10, "Mageroyal" }, { 2450, 10, "Briarthorn" } } },
  { 248683, 1, "Ore", "Apprentice Ore", {
    { 2770, 20, "Copper Ore" }, { 2771, 20, "Tin Ore" } } },
  { 248703, 1, "Ingots", "Apprentice Ingots", {
    { 2840, 20, "Copper Bar" }, { 3576, 20, "Tin Bar" }, { 2841, 10, "Bronze Bar" } } },
  { 248684, 1, "Textiles", "Apprentice Textiles", {
    { 2589, 40, "Linen Cloth" }, { 2318, 20, "Light Leather" } } },
  { 248702, 1, "Fabrics", "Apprentice Fabrics", {
    { 4231, 2, "Cured Light Hide" }, { 2996, 20, "Bolt of Linen Cloth" } } },
  { 248685, 1, "Curiosities", "Apprentice Curiosities", {
    { 10940, 20, "Strange Dust" }, { 10939, 4, "Greater Magic Essence" },
    { 10978, 6, "Small Glimmering Shard" }, { 11084, 2, "Large Glimmering Shard" } } },
  { 248704, 1, "Parts", "Apprentice Parts", {
    { 4359, 16, "Handful of Copper Bolts" }, { 4361, 16, "Copper Tube" },
    { 4363, 4, "Copper Modulator" } } },

  { 248686, 2, "Herbs", "Journeyman Herbs", {
    { 3820, 10, "Stranglekelp" }, { 2453, 10, "Bruiseweed" }, { 3355, 10, "Wild Steelbloom" },
    { 3369, 10, "Grave Moss" }, { 3356, 10, "Kingsblood" } } },
  { 248687, 2, "Ore", "Journeyman Ore", {
    { 2775, 10, "Silver Ore" }, { 2772, 20, "Iron Ore" } } },
  { 248706, 2, "Ingots", "Journeyman Ingots", {
    { 2842, 10, "Silver Bar" }, { 3575, 20, "Iron Bar" } } },
  { 248688, 2, "Textiles", "Journeyman Textiles", {
    { 2592, 20, "Wool Cloth" }, { 4306, 40, "Silk Cloth" }, { 2319, 20, "Medium Leather" } } },
  { 248705, 2, "Fabrics", "Journeyman Fabrics", {
    { 2997, 6, "Bolt of Woolen Cloth" }, { 4305, 10, "Bolt of Silk Cloth" },
    { 4233, 2, "Cured Medium Hide" } } },
  { 248689, 2, "Curiosities", "Journeyman Curiosities", {
    { 11083, 20, "Soul Dust" }, { 11082, 4, "Greater Astral Essence" },
    { 11138, 6, "Small Glowing Shard" }, { 11139, 2, "Large Glowing Shard" } } },
  { 248707, 2, "Parts", "Journeyman Parts", {
    { 4371, 8, "Bronze Tube" }, { 4375, 7, "Whirring Bronze Gizmo" },
    { 4382, 4, "Bronze Framework" }, { 10558, 45, "Gold Power Core" } } },

  { 248690, 3, "Herbs", "Earthly Expert Herbs", {
    { 3357, 20, "Liferoot" }, { 3818, 10, "Fadeleaf" }, { 3821, 10, "Goldthorn" },
    { 3358, 10, "Khadgar's Whisker" } } },
  { 248691, 3, "Herbs", "Flowering Expert Herbs", {
    { 3819, 10, "Wintersbite" }, { 4625, 10, "Firebloom" }, { 8831, 20, "Purple Lotus" },
    { 8836, 10, "Arthas' Tears" } } },
  { 248692, 3, "Ore", "Expert Ore", {
    { 2776, 10, "Gold Ore" }, { 3858, 20, "Mithril Ore" } } },
  { 248709, 3, "Ingots", "Expert Ingots", {
    { 3860, 20, "Mithril Bar" }, { 3859, 15, "Steel Bar" }, { 3577, 10, "Gold Bar" } } },
  { 248693, 3, "Textiles", "Expert Textiles", {
    { 4338, 40, "Mageweave Cloth" }, { 4234, 20, "Heavy Leather" } } },
  { 248708, 3, "Fabrics", "Expert Fabrics", {
    { 4339, 8, "Bolt of Mageweave" }, { 4236, 2, "Cured Heavy Hide" } } },
  { 248694, 3, "Curiosities", "Expert Curiosities", {
    { 11137, 20, "Vision Dust" }, { 11135, 4, "Greater Mystic Essence" },
    { 11177, 6, "Small Radiant Shard" }, { 11178, 2, "Large Radiant Shard" } } },
  { 248710, 3, "Parts", "Expert Parts", {
    { 4387, 8, "Iron Strut" }, { 10559, 5, "Mithril Tube" }, { 10560, 12, "Unstable Trigger" },
    { 10561, 5, "Mithril Casing" } } },

  { 248695, 4, "Herbs", "Earthly Artisan Herbs", {
    { 13464, 10, "Golden Sansam" }, { 8838, 20, "Sungrass" }, { 8839, 10, "Blindweed" },
    { 8845, 10, "Ghost Mushroom" }, { 8846, 10, "Gromsblood" } } },
  { 248696, 4, "Herbs", "Flowering Artisan Herbs", {
    { 13463, 20, "Dreamfoil" }, { 13465, 20, "Mountain Silversage" },
    { 13466, 20, "Plaguebloom" }, { 13467, 20, "Icecap" } } },
  { 248697, 4, "Ore", "Artisan Ore", {
    { 7911, 10, "Truesilver Ore" }, { 10620, 20, "Thorium Ore" }, { 11099, 20, "Dark Iron Ore" } } },
  { 248712, 4, "Ingots", "Artisan Ingots", {
    { 11371, 2, "Dark Iron Bar" }, { 6037, 10, "Truesilver Bar" }, { 12359, 20, "Thorium Bar" } } },
  { 248698, 4, "Textiles", "Artisan Textiles", {
    { 14047, 40, "Runecloth" }, { 4304, 20, "Thick Leather" }, { 8170, 20, "Rugged Leather" } } },
  { 248711, 4, "Fabrics", "Artisan Fabrics", {
    { 14048, 8, "Bolt of Runecloth" }, { 8172, 2, "Cured Thick Hide" } } },
  { 248699, 4, "Curiosities", "Artisan Curiosities", {
    { 11176, 20, "Dream Dust" }, { 11175, 4, "Greater Nether Essence" },
    { 14343, 6, "Small Brilliant Shard" }, { 14344, 2, "Large Brilliant Shard" } } },
  { 248713, 4, "Parts", "Artisan Parts", {
    { 15994, 5, "Thorium Widget" }, { 18631, 5, "Truesilver Transformer" },
    { 16000, 2, "Thorium Tube" } } },
}

-- Merchant's Favor a filled crate pays, by tier: { common (white) crate, uncommon (green)
-- crate }. From wow.gg, which has the first two tiers only; the rest is recorded in game
-- (Learn.lua) and baked into Data/Recorded.lua.
ns.CRATE_FAVOR = { { 5, 10 }, { 10, 20 } }

-- A filled crate is one of fifteen "Sealed <tier> Crate" items: three runs of five tiers
-- (Apprentice, Journeyman, Expert, Artisan, Elite).
ns.SEALED_FIRST, ns.SEALED_LAST = 248765, 248779

--- The tier (1-5) of a sealed crate item, nil for anything else.
function ns.SealedTier(item)
  if type(item) ~= "number" or item < ns.SEALED_FIRST or item > ns.SEALED_LAST then return nil end
  return (item - ns.SEALED_FIRST) % 5 + 1
end

-- Player level a crate of each tier asks for.
ns.CRATE_LEVEL = { 10, 10, 20, 35 }
