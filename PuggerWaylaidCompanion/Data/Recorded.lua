-- Recorded in game by Pugger Waylaid Companion and written here by
-- scripts/bake_waylaid.py. Do not edit by hand: run the script again instead.
local _, ns = ...

-- Places writs are handed in that Data/Writs.lua does not have:
-- [NPC id, or "at:map:x:y" for a spot nobody has named yet] = { name, uiMapID, x, y, zone }
ns.RECORDED_NPCS = {
  ["at:1418:424:529"] = { "Writ customer", 1418, 42.41, 52.91, "Badlands" },
  ["at:1426:602:797"] = { "Writ customer", 1426, 60.25, 79.73, "Dun Morogh" },
  ["at:1431:262:361"] = { "Writ customer", 1431, 26.27, 36.19, "Duskwood" },
  ["at:1439:858:71"] = { "Writ customer", 1439, 85.81, 7.18, "Darkshore" },
  ["at:1446:510:273"] = { "Writ customer", 1446, 51.02, 27.37, "Tanaris" },
  ["at:2548:769:540"] = { "Writ customer", 2548, 76.91, 54.07, "Riverglades" },
}

-- [writ quest] = place
ns.RECORDED_WRITS = {
  [94223] = "at:1431:262:361", -- Silver Skeleton Key
  [94261] = "at:1439:858:71", -- Great Rage Potion
  [94298] = "at:2548:769:540", -- Swift Boots
  [94304] = "at:1418:424:529", -- Mageweave Bag
  [94311] = "at:1426:602:797", -- Red Mageweave Pants
  [94313] = "at:1446:510:273", -- White Bandit Mask
}

-- Merchant's Favor paid for a filled crate:
-- [sealed crate item, or "q<quest>" when the crate was not seen] = { [amount] = times seen }
ns.RECORDED_FAVOR = {
}
