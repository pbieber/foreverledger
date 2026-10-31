-- Expected disenchant value of green, blue and purple gear on Forever, the way
-- Disenchantry shows it ("Expected disenchant value" in its tooltip): the era
-- disenchanting tables (dust / essence / shard per item level band, with their
-- chances and quantity ranges) priced with Auctionator's material prices,
-- expected value = sum of chance x average quantity x price. Disenchantry keeps
-- that code in its private namespace (no API for other addons, checked in its
-- 1.1.5 source, 2026-10-26), so Mailworthy computes the same number itself and
-- the two agree item for item.
--
-- Tables ported from Disenchantry 1.1.5 (DisenchantResults.lua, MIT: Copyright
-- (c) 2026 x_Raven_x and Rakuga, after warcraft.wiki.gg "Disenchanting tables"),
-- original-era rows only: Forever has no later expansions. Rows: { min ilvl,
-- max ilvl, dust ID, essence ID, shard ID, armor dust %, armor essence %,
-- weapon dust %, weapon essence %, dust min, dust max, essence min, essence max }.
-- Shards take the rest of the chance and always come one at a time.
local _, ns = ...

local Disenchant = {}
ns.Disenchant = Disenchant

Disenchant.UNCOMMON = {
    { 5, 15, 10940, 10938, nil, 80, 20, 20, 80, 1, 2, 1, 2 },
    { 16, 20, 10940, 10939, 10978, 75, 20, 20, 75, 2, 3, 1, 2 },
    { 21, 25, 10940, 10998, 10978, 75, 15, 15, 75, 4, 6, 1, 2 },
    { 26, 30, 11083, 11082, 11084, 75, 20, 20, 75, 1, 2, 1, 2 },
    { 31, 35, 11083, 11134, 11138, 75, 20, 20, 75, 2, 5, 1, 2 },
    { 36, 40, 11137, 11135, 11139, 75, 20, 20, 75, 1, 2, 1, 2 },
    { 41, 45, 11137, 11174, 11177, 75, 20, 20, 75, 2, 5, 1, 2 },
    { 46, 50, 11176, 11175, 11178, 75, 20, 20, 75, 1, 2, 1, 2 },
    { 51, 55, 11176, 16202, 14343, 75, 20, 22, 75, 2, 5, 1, 2 },
    { 56, 60, 16204, 16203, 14344, 75, 20, 22, 75, 1, 2, 1, 2 },
    { 61, 65, 16204, 16203, 14344, 75, 20, 22, 75, 2, 5, 2, 3 },
}
-- Rare: { min ilvl, max ilvl, shard ID, second shard ID (0.5%) }
Disenchant.RARE = {
    { 1, 25, 10978 }, { 26, 30, 11084 }, { 31, 35, 11138 }, { 36, 40, 11139 },
    { 41, 45, 11177 }, { 46, 50, 11178 }, { 51, 55, 14343 }, { 56, 80, 14344, 20725 },
}
-- Epic: { min ilvl, max ilvl, material ID, min quantity, max quantity }
Disenchant.EPIC = {
    { 40, 45, 11177, 2, 4 }, { 46, 50, 11178, 2, 4 }, { 51, 55, 14343, 2, 4 }, { 56, 60, 20725, 1, 1 }, { 61, 88, 20725, 1, 2 },
}
Disenchant.GREATER_MAGIC_ESSENCE = 10939 -- Forever: uncommon weapons ilvl 21-30 yield it (Wowhead Forever data, per Disenchantry)
Disenchant.WEAPON, Disenchant.ARMOR = 2, 4

local function outcome(id, chance, minQuantity, maxQuantity)
    return { itemID = id, chance = chance, minQuantity = minQuantity or 1, maxQuantity = maxQuantity or minQuantity or 1 }
end

local function find(rows, level)
    for _, row in ipairs(rows) do
        if level >= row[1] and level <= row[2] then return row end
    end
    return nil
end

--- Pure: the materials disenchanting an item can give: { { itemID, chance (%), minQuantity,
--- maxQuantity }, ... }, or nil when the item can't be disenchanted or the tables don't
--- cover it. item = { quality, level (item level), classID }.
function Disenchant.Outcomes(item)
    local level, quality, class = tonumber(item and item.level), tonumber(item and item.quality), tonumber(item and item.classID)
    if not level or level <= 0 or (class ~= Disenchant.WEAPON and class ~= Disenchant.ARMOR) then return nil end
    if quality == 2 then
        local row = find(Disenchant.UNCOMMON, level)
        if not row then return nil end
        local weapon = class == Disenchant.WEAPON
        local dust, essence = row[weapon and 8 or 6], row[weapon and 9 or 7]
        local essenceID = row[4]
        if not ns.isTBC and weapon and level >= 21 and level <= 30 then essenceID = Disenchant.GREATER_MAGIC_ESSENCE end
        local results = { outcome(row[3], dust, row[10], row[11]), outcome(essenceID, essence, row[12], row[13]) }
        if row[5] then results[#results + 1] = outcome(row[5], 100 - dust - essence) end
        return results
    elseif quality == 3 then
        local row = find(Disenchant.RARE, level)
        if not row then return nil end
        if row[4] then return { outcome(row[3], 99.5), outcome(row[4], 0.5) } end
        return { outcome(row[3], 100) }
    elseif quality == 4 then
        local row = find(Disenchant.EPIC, level)
        if row then return { outcome(row[3], 100, row[4], row[5]) } end
    end
    return nil
end

--- Pure: the expected value (copper) of `outcomes` with `priceOf(itemID)` = copper per
--- material or nil; nil when any material that can drop has no price (as Disenchantry:
--- a partial sum would undervalue the item). Quantity ranges count their midpoint.
function Disenchant.ExpectedValue(outcomes, priceOf)
    if type(outcomes) ~= "table" or #outcomes == 0 then return nil end
    local total = 0
    for _, result in ipairs(outcomes) do
        if result.chance > 0 then
            local copper = tonumber((priceOf(result.itemID)))
            if not copper or copper <= 0 then return nil end
            total = total + result.chance / 100 * (result.minQuantity + result.maxQuantity) / 2 * copper
        end
    end
    return math.floor(total)
end


