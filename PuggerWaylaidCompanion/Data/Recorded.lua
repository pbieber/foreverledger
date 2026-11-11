-- Recorded in game by Pugger Waylaid Companion and written here by
-- scripts/bake_waylaid.py. Do not edit by hand: run the script again instead.
local _, ns = ...

-- Places writs are handed in that Data/Writs.lua does not have:
-- [NPC id, or "at:map:x:y" for a spot nobody has named yet] = { name, uiMapID, x, y, zone }
ns.RECORDED_NPCS = {
  [2817] = { "Rigglefuzz", 1418, 42.41, 52.91, "Badlands" },
  [6176] = { "Bath'rah the Windwatcher", 1416, 80.51, 66.91, "Alterac Mountains" },
  [6548] = { "Magus Tirth", 1441, 78.29, 75.69, "Thousand Needles" },
  [6568] = { "Vizzklick", 1446, 51.02, 27.37, "Tanaris" },
  [9272] = { "Spark Nilminer", 1449, 43.5, 7.43, "Un'Goro Crater" },
  [11802] = { "Dendrite Starblaze", 1450, 56.22, 30.65, "Moonglade" },
  [13717] = { "Centaur Pariah", 1443, 50.5, 86.67, "Desolace" },
  [14634] = { "Lookout Captain Lolo Longstriker", 1427, 37.75, 26.55, "Searing Gorge" },
  [14743] = { "Jhordy Lapforge", 1446, 52.29, 26.89, "Tanaris" },
  [262072] = { "The Ravenous", 1445, 53.99, 56.48, "Dustwallow Marsh" },
  [262284] = { "Spek", 2548, 76.91, 54.07, "Riverglades" },
  [262306] = { "Mukomonji", 1435, 62.39, 52.85, "Swamp of Sorrows" },
  [642320] = { "Battered Trunk", 1431, 26.27, 36.19, "Duskwood" },
  ["at:1425:801:553"] = { "Writ customer", 1425, 80.13, 55.39, "The Hinterlands" },
}

-- [writ quest] = place
ns.RECORDED_WRITS = {
  [94223] = 642320, -- Silver Skeleton Key
  [94236] = 6626, -- Big Bronze Bomb
  [94238] = 257281, -- Heavy Leather Ball
  [94251] = 6176, -- Phoenix Pants
  [94252] = 4201, -- Red Woolen Boots
  [94254] = 6548, -- Greater Adept's Robe
  [94257] = 13717, -- Lesser Invisibility Potion
  [94261] = 11802, -- Great Rage Potion
  [94264] = 262306, -- Shadow Oil
  [94266] = "at:1425:801:553", -- Elixir of Agility
  [94267] = 9272, -- Wildvine Potion
  [94286] = 262284, -- Flash Bomb
  [94289] = 14743, -- Gyromatic Micro-Adjuster
  [94294] = 262072, -- Dusky Bracers
  [94298] = 262284, -- Swift Boots
  [94303] = 9272, -- Thick Leather Ammo Pouch
  [94304] = 2817, -- Mageweave Bag
  [94310] = 262284, -- Black Mageweave Vest
  [94311] = 14634, -- Red Mageweave Pants
  [94313] = 6568, -- White Bandit Mask
}

-- Merchant's Favor paid for a filled crate:
-- [sealed crate item, or "q<quest>" when the crate was not seen] = { [amount] = times seen }
ns.RECORDED_FAVOR = {
}
