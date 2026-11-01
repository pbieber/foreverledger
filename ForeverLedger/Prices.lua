local _,F=...

function F.LegacyAH()
    return F.isTBC or not (C_AuctionHouse and C_AuctionHouse.SendSearchQuery)
end

-- Bind types that can never be listed: on pickup, quest, account and warband.
-- Unknown (not yet loaded) bind types stay in the queue.
local UNLISTABLE={[1]=true,[4]=true,[7]=true,[8]=true,[9]=true}

function F.PriceQueue(mode)
    local catalog=F.market.catalog
    local materials={}
    for _,item in pairs(catalog) do
        for _,outcome in ipairs(F.DEOutcomes(item) or {}) do materials[outcome.itemID]=true end
    end
    for id in pairs(materials) do F.TrackItem(F.Item(nil,id)) end
    local missing,priced={},{}
    for key,item in pairs(catalog) do
        if not UNLISTABLE[item.bindType] then
            local p=F.market.prices[key]
            local entry={key=key,item=F.Copy(item),updatedAt=p and p.updatedAt or 0}
            if not p or not p.price then missing[#missing+1]=entry else priced[#priced+1]=entry end
        end
    end
    table.sort(missing,function(a,b) return a.key<b.key end)
    table.sort(priced,function(a,b) if a.updatedAt==b.updatedAt then return a.key<b.key end; return a.updatedAt<b.updatedAt end)
    for i=1,math.min(#priced,mode=="all" and #priced or 50) do missing[#missing+1]=priced[i] end
    return missing
end

function F.StopPrices(reason)
    local s=F.priceScan
    if not s then return end
    F.Emit("price_scan_end",{mode=s.mode,completed=s.index-1,total=#s.queue,reason=reason})
    F.priceStatus=reason.." ("..(s.index-1).." / "..#s.queue..")"
    F.priceScan=nil
    F.Print(F.priceStatus)
end

function F.StartPrices(mode)
    if not F.context.auction then F.Print("Open the auction house before scanning prices."); return false end
    if F.priceScan then F.StopPrices("Replaced") end
    F.ScanBags(true); F.ScanEquipment()
    F.priceScan={queue=F.PriceQueue(mode),index=1,mode=mode,legacy=F.LegacyAH()}
    F.Emit("price_scan_start",{mode=mode,total=#F.priceScan.queue,scope=F.marketScope})
    F.priceStatus="Scanning "..#F.priceScan.queue.." tracked items. Leave the AH open; avoid other searches."
    F.Print(F.priceStatus)
    return true
end

local function finish(price,status)
    local s=F.priceScan
    local entry=s.queue[s.index]
    local p={price=price,updatedAt=F.Now(),source=s.legacy and "legacy_ah" or "modern_ah",status=status}
    -- A complete zero-result query clears a stale quote. A failure never does.
    F.market.prices[entry.key]=p
    F.Emit("price",{scope=F.marketScope,key=entry.key,item=entry.item,quote=p})
    s.index=s.index+1; s.pending=nil; s.current=nil; s.page=nil; s.minimum=nil; s.more=nil
    F.priceStatus="Prices: "..(s.index-1).." / "..#s.queue.." checked"
    F.historyDirty=true
end

local function fail(reason)
    local s=F.priceScan
    F.Emit("price_scan_error",{key=s.queue[s.index] and s.queue[s.index].key,reason=reason})
    F.StopPrices(reason)
end

function F.PriceTick()
    local s=F.priceScan
    if not s then return end
    if not F.context.auction then F.StopPrices("AH closed"); return end
    if s.index>#s.queue then F.StopPrices("Scan complete"); return end
    if s.pending then
        if F.Clock()-s.pending>30 then fail("Query timed out; existing prices kept") end
        return
    end
    if F.Clock()-(s.sentAt or -2)<1 then return end
    local entry=s.queue[s.index]
    local item=F.Item(entry.item.link,entry.item.id,entry.item.name)
    s.current=item
    local fn,args
    if s.legacy then
        if F.Call(CanSendAuctionQuery,"list")~=true then return end
        if not item.name then
            s.waitingInfo=s.waitingInfo or F.Clock()
            if F.Clock()-s.waitingInfo>15 then fail("Item information unavailable; retry after it loads") end
            return
        end
        s.waitingInfo=nil
        fn=QueryAuctionItems
        args={n=9,item.name,nil,nil,s.page or 0,false,nil,false,true,nil}
    else
        local api=C_AuctionHouse
        if api.IsThrottledMessageSystemReady and not F.Call(api.IsThrottledMessageSystemReady) then return end
        local key=entry.item.auctionItemKey or {itemID=item.id,itemLevel=(item.classID==2 or item.classID==4) and item.level or 0,
            itemSuffix=tonumber(entry.key:match(":(-?%d+)$")) or 0,battlePetSpeciesID=0}
        s.itemKey=key
        if s.more then
            fn=s.commodity and api.RequestMoreCommoditySearchResults or api.RequestMoreItemSearchResults
            args={n=1,s.commodity and item.id or key}
        else fn=api.SendSearchQuery; args={n=3,key,{},false} end
    end
    if not fn then fail("Auction search API unavailable"); return end
    s.pending=F.Clock(); s.sentAt=F.Clock()
    F.sendingPriceQuery=true
    local ok,err=pcall(fn,unpack(args,1,args.n))
    F.sendingPriceQuery=nil
    if not ok then fail("Auction query rejected: "..tostring(err)) end
end

function F.PriceResults(kind,key)
    local s=F.priceScan
    if not s or not s.pending then return end
    local item=s.current
    if s.legacy then
        if kind~="legacy" then return end
        local count,total=F.Call(GetNumAuctionItems,"list")
        if not count or not total then return end
        for i=1,count do
            local v={F.Call(GetAuctionItemInfo,"list",i)}
            -- Wait for item cache data; do not accept an incomplete page.
            if v[18]==false or not v[1] or not v[17] then return end
            local link=F.Call(GetAuctionItemLink,"list",i)
            if not link then return end
            if F.PriceKey({id=v[17],link=link})==s.queue[s.index].key and (v[10] or 0)>0 and (v[3] or 0)>0 then
                local unit=math.floor(v[10]/v[3]); s.minimum=math.min(s.minimum or unit,unit)
            end
        end
        if ((s.page or 0)+1)*50<total then s.page=(s.page or 0)+1; s.pending=nil; return end
        finish(s.minimum,s.minimum and "priced" or "no_buyout")
    else
        local api=C_AuctionHouse
        if kind=="commodity" then
            if key~=item.id then return end
            s.commodity=true
        elseif kind=="item" then
            if type(key)~="table" or F.JSON(key)~=F.JSON(s.itemKey) then return end
            s.commodity=false
        else return end
        local arg=s.commodity and item.id or s.itemKey
        local full=F.Call(s.commodity and api.HasFullCommoditySearchResults or api.HasFullItemSearchResults,arg)==true
        local count=F.Call(s.commodity and api.GetNumCommoditySearchResults or api.GetNumItemSearchResults,arg)
        -- Commodity results arrive cheapest first, so the loaded rows already hold
        -- the minimum. Unsorted item results need every page.
        if not full and (not s.commodity or (count or 0)==0) then s.more=true; s.pending=nil; return end
        if not count then return end
        local minimum
        for i=1,count do
            local r=F.Call(s.commodity and api.GetCommoditySearchResultInfo or api.GetItemSearchResultInfo,arg,i)
            if not r then return end
            local unit=s.commodity and r.unitPrice or (r.buyoutAmount and (r.quantity or 0)>0 and math.floor(r.buyoutAmount/r.quantity))
            if unit and unit>0 then minimum=math.min(minimum or unit,unit) end
        end
        finish(minimum,minimum and "priced" or "no_buyout")
    end
end

function F.InstallPriceHooks()
    -- Other addons / the browse UI share the same result buffers. Stop rather
    -- than attaching their results to our outstanding query.
    local function interrupted() if F.priceScan and not F.sendingPriceQuery then F.StopPrices("Another AH search started") end end
    if QueryAuctionItems then hooksecurefunc("QueryAuctionItems",interrupted) end
    if C_AuctionHouse then
        for _,name in ipairs({"SendSearchQuery","SendSellSearchQuery","RequestMoreItemSearchResults","RequestMoreCommoditySearchResults","SendBrowseQuery"}) do
            if C_AuctionHouse[name] then hooksecurefunc(C_AuctionHouse,name,interrupted) end
        end
    end
end

F.events.AUCTION_ITEM_LIST_UPDATE=function() F.PriceResults("legacy") end
F.events.ITEM_SEARCH_RESULTS_UPDATED=function(key) F.PriceResults("item",key) end
F.events.ITEM_SEARCH_RESULTS_ADDED=function(key) F.PriceResults("item",key) end
F.events.COMMODITY_SEARCH_RESULTS_UPDATED=function(id) F.PriceResults("commodity",id) end
F.events.COMMODITY_SEARCH_RESULTS_ADDED=function(id) F.PriceResults("commodity",id) end
F.events.SKILL_LINES_CHANGED=function() F.ScanProfession() end
-- Keep the first dirty time: a stream of item-cache replies must not keep
-- postponing the bag rescan. Unchanged rescans record nothing.
F.events.GET_ITEM_INFO_RECEIVED=function() F.bagDirty=F.bagDirty or F.Clock(); F.equipmentDirty=true end
