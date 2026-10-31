local _, F = ...

function F.InitValuation()
    local version=F.Call(GetBuildInfo) or ""
    F.isTBC=version:match("^2%.")~=nil
    F.marketScope=(F.isTBC and "tbc" or "forever")..":"..F.identity.realm..":"..(F.Call(UnitFactionGroup,"player") or "unknown")
    F.db.markets=F.db.markets or {}
    F.db.markets[F.marketScope]=F.db.markets[F.marketScope] or {catalog={},prices={}}
    F.market=F.db.markets[F.marketScope]
    F.character.marketScope=F.marketScope
    F.db.history=F.db.history or {}
    F.historyDirty=true
    F.ScanProfession()
end

function F.ScanProfession()
    local skill,known=0,false
    if GetProfessions and GetProfessionInfo then
        known=true
        local professions={GetProfessions()}
        for _, index in pairs(professions) do
            local v={F.Call(GetProfessionInfo,index)}
            if v[7]==333 then skill=F.Number(v[3]) or 1 end
        end
    elseif GetNumSkillLines and GetSkillLineInfo then
        known=true
        local enchanting=F.Call(GetSpellInfo,7411)
        if not enchanting and C_Spell then local s=F.Call(C_Spell.GetSpellInfo,7411); enchanting=s and s.name end
        for i=1,(F.Call(GetNumSkillLines) or 0) do
            local v={F.Call(GetSkillLineInfo,i)}
            if enchanting and v[1]==enchanting then skill=F.Number(v[4]) or 1 end
        end
    end
    local state={enchanting=skill>0,skill=skill,known=known}
    if F.JSON(state)~=F.JSON(F.character.professions or {}) then
        F.character.professions=state; F.Emit("professions",state); F.historyDirty=true
    end
end

function F.PriceKey(item)
    if not item or not item.id then return nil end
    local fields={}
    local link=type(item.link)=="string" and item.link or ""
    for field in ((link:match("item:([^|]+)") or "")..":"):gmatch("(.-):") do fields[#fields+1]=field end
    local suffix=item.auctionItemKey and item.auctionItemKey.itemSuffix or tonumber(fields[7]) or 0
    return tostring(item.id)..":"..tostring(suffix)
end

function F.TrackItem(item)
    if not F.market then return end
    local key=F.PriceKey(item)
    if not key then return end
    local old=F.market.catalog[key] or {}
    for k,v in pairs(item) do old[k]=v end
    old.priceKey=key
    F.market.catalog[key]=old
    local api=Auctionator and Auctionator.API and Auctionator.API.v1
    if api and not F.market.prices[key] then
        local price=F.Number(F.Call(api.GetAuctionPriceByItemLink,"ForeverLedger",item.link))
        local age=F.Call(api.GetAuctionAgeByItemLink,"ForeverLedger",item.link)
        if price and price>0 then
            F.market.prices[key]={price=price,source="Auctionator",retrievedAt=F.Now(),
                updatedAt=type(age)=="number" and F.Now()-math.ceil(age*86400) or nil}
            F.Emit("price",{scope=F.marketScope,key=key,item=item,quote=F.market.prices[key]})
        end
    end
end

function F.Price(item,scope)
    local market=F.db.markets and F.db.markets[scope or F.marketScope]
    local p=market and market.prices[F.PriceKey(item)]
    return p and p.price,p
end

function F.DEOutcomes(item)
    -- These era tables are intentionally not applied to Outland gear. Those
    -- item-level bands overlap vanilla gear and require a separate loot model.
    if F.isTBC and ((item.expansionID or 0)>0 or (item.level or 0)>60) then return nil end
    if item.equipLoc=="INVTYPE_BAG" then return nil end
    return F.Disenchant.Outcomes(item)
end

function F.RequiredEnchanting(item)
    if not F.isTBC then return 1 end
    local level=item.level or 0
    return math.max(1,(math.ceil(level/5)-4)*25)
end

function F.ValueRow(row,owner,scope)
    local item=row.item or {}
    local vendor=item.vendorPrice or 0
    local bound=row.equipped or row.bound
    -- Unknown binding is conservative: no auction value or transferable DE.
    local tradable=row.bound==false and not row.equipped
    local result={vendor=vendor,value=vendor,method="vendor",bindingKnown=row.bound~=nil or row.equipped==true}
    local outcomes=F.DEOutcomes(item)
    local profession=owner and owner.professions
    local canDE=tradable or (bound and profession and profession.enchanting and
        (profession.skill or 0)>=F.RequiredEnchanting(item))
    if outcomes and canDE then
        local gross=F.Disenchant.ExpectedValue(outcomes,function(id) return F.Price({id=id},scope) end)
        if gross then
            result.disenchantGross=gross
            result.disenchantNet=math.floor(gross*(1-F.db.settings.commissionBps/10000))
            if result.disenchantNet>result.value then result.value=result.disenchantNet; result.method="disenchant" end
        else result.disenchantUnpriced=true end
    elseif canDE and (item.quality or 0)>=2 and (item.quality or 0)<=4 and (item.classID==2 or item.classID==4) and item.equipLoc~="INVTYPE_BAG" then
        result.disenchantUnsupported=true
    end
    if tradable then
        local price,p=F.Price(item,scope)
        if price then
            result.marketGross=price; result.marketNet=math.floor(price*(1-F.db.settings.commissionBps/10000))
            result.priceUpdatedAt=p.updatedAt
            if result.marketNet>result.value then result.value=result.marketNet; result.method="auction" end
        else result.marketUnpriced=true end
    end
    result.partial=item.vendorPrice==nil or not result.bindingKnown or result.marketUnpriced or result.disenchantUnpriced or result.disenchantUnsupported or nil
    return result
end

function F.RecordValue(force)
    if not F.db.history or (not force and not F.historyDirty) then return end
    -- Wait until bags and equipped slots describe the same settled inventory.
    if F.bagDirty or F.equipmentDirty then return end
    F.historyDirty=nil
    local d={gold=0,assets=0,equipped=0,unpricedRows=0,scope=F.marketScope,characters={},estimate=true,
        model=F.VERSION,commissionBps=F.db.settings.commissionBps}
    for guid,c in pairs(F.db.characters) do
        if c.marketScope==F.marketScope then
            local cd={gold=c.balance or 0,assets=0,equipped=0,snapshots={},professions=F.Copy(c.professions)}
            local seen={}
            for _,location in ipairs({"equipment","bags","bank","auctions","mail"}) do
                local s=c.snapshots[location]
                cd.snapshots[location]=s and {time=s.time,complete=s.data.complete} or {missing=true}
                if s then
                    local function add(row,equipped)
                        if row.guid and seen[row.guid] then return end
                        if row.guid then seen[row.guid]=true end
                        local v=F.ValueRow(row,c,c.marketScope)
                        local target=equipped and "equipped" or "assets"
                        cd[target]=cd[target]+v.value*(row.quantity or 1)
                        if v.partial then d.unpricedRows=d.unpricedRows+1 end
                    end
                    for _,row in ipairs(s.data.rows) do
                        if location=="mail" then
                            cd.assets=cd.assets+(row.money or 0)
                            -- COD contents are not owned until paid; do not count.
                            if (row.cod or 0)==0 then
                                for _,r in ipairs(row.items or {}) do local r=F.Copy(r); r.bound=false; add(r) end
                            end
                        elseif location=="auctions" then
                            if row.status==0 then local r=F.Copy(row); r.bound=false; add(r) end
                        else add(row,location=="equipment") end
                    end
                end
            end
            d.gold=d.gold+cd.gold; d.assets=d.assets+cd.assets; d.equipped=d.equipped+cd.equipped
            d.characters[guid]=cd
        end
    end
    d.total=d.gold+d.assets+d.equipped
    local signature=F.JSON(d)
    if not force and signature==F.lastValue then return end
    F.lastValue=signature
    local e=F.Emit("valuation",d)
    F.db.history[#F.db.history+1]={time=e.time,eventID=e.id,scope=d.scope,gold=d.gold,assets=d.assets,
        equipped=d.equipped,total=d.total,unpricedRows=d.unpricedRows,episode=F.db.episode}
    if F.RefreshChart and F.window and F.window:IsShown() then F.RefreshChart() end
end

function F.StackHistory(history,selected,scope)
    local points,maxValue={},1
    for _,h in ipairs(history) do
        if h.scope==scope then
            local point={time=h.time,values={},raw=h}; local sum=0
            for _,key in ipairs({"gold","assets","equipped"}) do
                if selected[key] then sum=sum+(h[key] or 0); point.values[#point.values+1]={key=key,value=sum} end
            end
            points[#points+1]=point; maxValue=math.max(maxValue,sum)
        end
    end
    return points,maxValue
end
