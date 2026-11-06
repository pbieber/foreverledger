local _, F = ...
-- TBC charges 60% of vendor value for a 48 hour listing, its longest.
local LONGEST_LISTING_RATE=0.6
local CHART_TYPES={"gold","assets","equipped"}
local MAX_CHART_BANDS=8
F.OTHER_BAND="other"

-- Chart samples hold each character's values. Older samples get them from their
-- valuation event, keeping any gold the logout repair restored.
local function migrateHistory(db)
    local valuations
    for _,h in ipairs(db.history) do
        if h.goldBy or not h.chars then
            if not valuations then
                valuations={}
                for _,e in ipairs(db.events) do if e.kind=="valuation" then valuations[e.id]=e end end
            end
            local e=valuations[h.eventID]
            if e then
                h.chars={}
                for guid,c in pairs(e.data.characters or {}) do
                    h.chars[guid]={gold=h.goldBy and h.goldBy[guid] or c.gold,assets=c.assets,equipped=c.equipped}
                end
            end
            h.goldBy=nil
        end
        h.top=nil
    end
end

-- Prices and samples keep their own market scope. The chart groups scopes the player
-- sees as one realm: Forever puts accounts on numbered hidden realms of one cluster
-- (CAMWOWEU5Realm2PvP, CAMWOWEU5Realm6PvP) that mail and trade with each other.
function F.ChartScope(scope)
    if type(scope)~="string" then return nil end
    local flavor,realm,faction=scope:match("^(forever):(.*):([^:]*)$")
    if not flavor then return scope end
    return flavor..":"..realm:gsub("Realm%d+","Realm")..":"..faction
end

function F.SameChart(a,b)
    return a~=nil and b~=nil and F.ChartScope(a)==F.ChartScope(b)
end

function F.InitValuation()
    local version=F.Call(GetBuildInfo) or ""
    F.isTBC=version:match("^2%.")~=nil
    F.marketScope=(F.isTBC and "tbc" or "forever")..":"..F.identity.realm..":"..(F.Call(UnitFactionGroup,"player") or "unknown")
    F.db.markets=F.db.markets or {}
    F.db.markets[F.marketScope]=F.db.markets[F.marketScope] or {catalog={},prices={}}
    F.market=F.db.markets[F.marketScope]
    F.character.marketScope=F.marketScope
    local _,class=F.Call(UnitClass,"player")
    if class then F.character.class=class end
    F.db.history=F.db.history or {}
    F.depositsRead,F.unitDeposits=0,{}
    migrateHistory(F.db)
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
    scope=scope or F.marketScope
    local key,markets=F.PriceKey(item),F.db.markets
    local market=markets and markets[scope]
    local p=market and key and market.prices[key]
    if not p and markets and key then
        -- A Forever character can come back on another numbered hidden realm. The
        -- latest price seen on one of the others still beats none.
        for other,m in pairs(markets) do
            local q=other~=scope and F.SameChart(other,scope) and m.prices and m.prices[key]
            if q and (not p or (q.retrievedAt or 0)>(p.retrievedAt or 0)) then p=q end
        end
    end
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

local function topTen(byKey)
    local list={}
    for key,e in pairs(byKey) do e.key=key; list[#list+1]=e end
    table.sort(list,function(a,b) if a.value==b.value then return a.key<b.key end; return a.value>b.value end)
    for i=#list,11,-1 do list[i]=nil end
    return list
end

-- Each character's most valuable items over time, kept only when they change.
local function rememberTop(c,time,assets,equipped)
    c.tops=c.tops or {}
    local last=c.tops[#c.tops]
    if last and F.JSON({last.assets,last.equipped})==F.JSON({assets,equipped}) then return end
    c.tops[#c.tops+1]={time=time,assets=assets,equipped=equipped}
    if #c.tops>100 then table.remove(c.tops,1) end
end

function F.TopAt(guid,t,key)
    local c=F.CharacterInfo(guid)
    local tops=c and c.tops or {}
    for i=#tops,1,-1 do
        if tops[i].time<=t then return tops[i][key] end
    end
    return {}
end

function F.RecordValue(force)
    if not F.db.history or (not force and not F.historyDirty) then return end
    -- Every price reply changes the value; one sample when the scan ends is enough.
    if F.priceScan and not force then return end
    -- Wait until bags and equipped slots describe the same settled inventory.
    if F.bagDirty or F.equipmentDirty then return end
    F.historyDirty=nil
    local d={gold=0,assets=0,equipped=0,unpricedRows=0,scope=F.marketScope,characters={},estimate=true,
        model=F.VERSION,commissionBps=F.db.settings.commissionBps}
    local tops,chars,stocks,found,observed={},{},{},{},{}
    for guid,c in pairs(F.db.characters) do
        if F.SameChart(c.marketScope,F.marketScope) then
            local cd={gold=c.balance or 0,assets=0,equipped=0,snapshots={},professions=F.Copy(c.professions)}
            local top={assets={},equipped={}}
            local seen,stock,discovered,locations={},{},{},{}
            for _,location in ipairs({"equipment","bags","bank","auctions","mail"}) do
                local s=c.snapshots[location]
                cd.snapshots[location]=s and {time=s.time,complete=s.data.complete} or {missing=true}
                if s then
                    locations[location]=true
                    local isNew=c.stock and c.stockSeen and not c.stockSeen[location]
                    local function add(row,equipped)
                        if row.guid and seen[row.guid] then return end
                        if row.guid then seen[row.guid]=true end
                        local v=F.ValueRow(row,c,c.marketScope)
                        local target=equipped and "equipped" or "assets"
                        cd[target]=cd[target]+v.value*(row.quantity or 1)
                        if v.value>0 then
                            local category=F.ItemCategory(row.item,F.market.catalog)
                            stock[category]=(stock[category] or 0)+v.value*(row.quantity or 1)
                            if isNew then discovered[category]=(discovered[category] or 0)+v.value*(row.quantity or 1) end
                        end
                        local key=F.PriceKey(row.item)
                        if key and v.value>0 then
                            local e=top[target][key] or {value=0,quantity=0}
                            top[target][key]=e
                            e.value=e.value+v.value*(row.quantity or 1); e.quantity=e.quantity+(row.quantity or 1)
                        end
                        if v.partial then d.unpricedRows=d.unpricedRows+1 end
                    end
                    for _,row in ipairs(s.data.rows) do
                        if location=="mail" then
                            cd.assets=cd.assets+(row.money or 0)
                            if (row.money or 0)>0 then
                                top.assets.mail=top.assets.mail or {value=0}
                                top.assets.mail.value=top.assets.mail.value+row.money
                            end
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
            d.characters[guid]=cd; tops[guid]=top; stocks[guid]=stock; found[guid]=discovered; observed[guid]=locations
            chars[guid]={gold=cd.gold,assets=cd.assets,equipped=cd.equipped}
        end
    end
    d.total=d.gold+d.assets+d.equipped
    -- Snapshot times change on every rescan; only values make a new sample.
    local unstamped=F.Copy(d)
    for _,cd in pairs(unstamped.characters) do
        for _,s in pairs(cd.snapshots) do s.time=nil end
    end
    local signature=F.JSON(unstamped)
    if not force and signature==F.lastValue then return end
    F.lastValue=signature
    local e=F.Emit("valuation",d)
    F.db.history[#F.db.history+1]={time=e.time,eventID=e.id,scope=d.scope,gold=d.gold,assets=d.assets,
        equipped=d.equipped,total=d.total,unpricedRows=d.unpricedRows,episode=F.db.episode,
        chars=chars}
    for guid,top in pairs(tops) do
        rememberTop(F.db.characters[guid],e.time,topTen(top.assets),topTen(top.equipped))
        F.RememberStock(F.db.characters[guid],e.time,stocks[guid],found[guid])
        F.db.characters[guid].stockSeen=observed[guid]
    end
    if F.RefreshChart and F.window and F.window:IsShown() then
        F.RefreshChart()
        if F.mode=="profit" then F.RefreshProfit() end
    end
end

-- Legacy listings have no auction ID, so the last deposit recorded for an item is the
-- closest record of what one cost. Read once, then only what was added since.
local function recordedDeposits()
    local events=F.db.events
    for i=F.depositsRead+1,#events do
        local d=events[i].kind=="activity" and events[i].data
        if d and d.category=="auction_deposit" and d.item and d.item.id and (d.quantity or 0)>0 then
            F.unitDeposits[d.item.id]=-d.amount/d.quantity
        end
    end
    F.depositsRead=#events
end

-- What a listing cost to post, and whether that is an estimate.
local function listingDeposit(row)
    local posted=row.auctionKey and F.db.auctions[row.auctionKey]
    if posted and posted.deposit then return posted.deposit,false end
    local item,quantity=row.item or {},row.quantity or 1
    local unit=item.id and F.unitDeposits[item.id]
    if unit then return math.floor(unit*quantity+0.5),false end
    return math.floor((item.vendorPrice or 0)*quantity*LONGEST_LISTING_RATE),true
end

-- A character's active auctions as last seen at the auction house.
function F.CharacterListings(c)
    recordedDeposits()
    local s=c.snapshots and c.snapshots.auctions
    local result={count=0,total=0,deposit=0,estimated=0}
    for _,row in ipairs(s and s.data.rows or {}) do
        if row.status==0 then
            local buyout=row.totalBuyout or 0
            local deposit,estimated=listingDeposit(row)
            result.count=result.count+1
            result.total=result.total+(buyout>0 and buyout or math.max(row.bid or 0,row.minBid or 0))
            result.deposit=result.deposit+deposit
            if estimated then result.estimated=result.estimated+1 end
        end
    end
    return result
end

-- The selected characters' listings, with what linked accounts last sent, and the
-- auction house cut if they all sold at that price.
function F.OnSale(characters)
    local sum={count=0,total=0,deposit=0,estimated=0}
    for guid in pairs(characters) do
        local c=F.db.characters[guid]
        local listings=c and F.CharacterListings(c) or (F.CharacterInfo(guid) or {}).listings
        for key,value in pairs(listings or {}) do sum[key]=sum[key]+value end
    end
    sum.cut=math.floor(sum.total*F.db.settings.commissionBps/10000)
    return sum
end

-- The sample nearest time t, and the series whose drawn line passes within
-- tolerance of value v at t.
function F.HistoryAt(points,t,v,tolerance)
    local closest,before,after=points[1]
    for _,p in ipairs(points) do
        if math.abs(p.time-t)<math.abs(closest.time-t) then closest=p end
        if p.time<=t then before=p end
        if p.time>=t and not after then after=p end
    end
    before,after=before or after,after or before
    local f=after.time>before.time and (t-before.time)/(after.time-before.time) or 0
    local hit,best
    for j,a in ipairs(after.values) do
        local b=before.values[j].value
        local distance=math.abs(b+(a.value-b)*f-v)
        if distance<=tolerance and (not best or distance<best) then best=distance; hit=a.key end
    end
    return closest,hit
end

-- One character's value per band of a chart sample: its selected types, one band for
-- the character, or item categories. Equipped Gear counts as Gear. Other assets follow
-- the last recorded item mix, fitted to the sample's exact value, because stock is
-- recorded less often than value.
function F.CharacterBands(h,guid,selected,breakdown)
    local v=h.chars[guid]
    local bands={}
    if not v then return bands end
    local function add(key,value)
        if value and value~=0 then bands[key]=(bands[key] or 0)+value end
    end
    if breakdown=="category" then
        if selected.gold then add("gold",v.gold) end
        if selected.equipped then add("Gear",v.equipped) end
        if selected.assets and (v.assets or 0)~=0 then
            local mix,sum={},0
            for category,value in pairs(F.HeldAt(guid,h.time)) do
                if category=="Gear" then value=math.max(0,value-(v.equipped or 0)) end
                mix[category]=value; sum=sum+value
            end
            if sum>0 then
                for category,value in pairs(mix) do add(category,value/sum*v.assets) end
            else add(F.OTHER_BAND,v.assets) end
        end
    else
        for _,key in ipairs(CHART_TYPES) do
            if selected[key] then add(breakdown=="character" and guid or key,v[key]) end
        end
    end
    return bands
end

-- The bands to draw, bottom to top, and which ones fold into the last. Types keep their
-- order. Otherwise the biggest sits lowest, with gold below every category.
local function chartBands(peaks,selected,breakdown)
    local list,other={},{}
    if breakdown~="category" and breakdown~="character" then
        for _,key in ipairs(CHART_TYPES) do
            if selected[key] then list[#list+1]=key end
        end
        return list,other
    end
    for key in pairs(peaks) do
        if key~=F.OTHER_BAND then list[#list+1]=key end
    end
    table.sort(list,function(a,b)
        if (a=="gold")~=(b=="gold") then return a=="gold" end
        if peaks[a]==peaks[b] then return a<b end
        return peaks[a]>peaks[b]
    end)
    local keep=#list
    if keep>MAX_CHART_BANDS or (peaks[F.OTHER_BAND] and keep==MAX_CHART_BANDS) then keep=MAX_CHART_BANDS-1 end
    for i=#list,keep+1,-1 do
        other[list[i]]=true; list[i]=nil
    end
    if next(other) or peaks[F.OTHER_BAND] then list[#list+1]=F.OTHER_BAND end
    return list,other
end

-- Each sample's exact totals and its bands over the selected characters.
local function sampleValues(h,selected,characters,breakdown)
    local totals,bands={gold=0,assets=0,equipped=0},{}
    for guid in pairs(characters) do
        local v=h.chars[guid]
        if v then
            totals.gold=totals.gold+(v.gold or 0)
            totals.assets=totals.assets+(v.assets or 0)
            totals.equipped=totals.equipped+(v.equipped or 0)
        end
        for key,value in pairs(F.CharacterBands(h,guid,selected,breakdown)) do
            bands[key]=(bands[key] or 0)+value
        end
    end
    totals.total=totals.gold+totals.assets+totals.equipped
    return totals,bands
end

-- Chart points at equal time steps from the first sample to now. Each step shows
-- the latest sample at or before it, summed over the selected characters and stacked
-- by band. Without a breakdown the bands are the selected types.
function F.StackHistory(history,selected,scope,characters,steps,now,breakdown)
    local samples={}
    for _,h in ipairs(history) do
        if F.SameChart(h.scope,scope) and h.chars then samples[#samples+1]=h end
    end
    if #samples==0 then return {},1 end
    local first=samples[1].time
    local span=math.max(1,math.max(now,samples[#samples].time)-first)
    local points,peaks,index={},{},1
    local current,totals,bands
    for step=0,steps do
        local t=first+span*step/steps
        while samples[index+1] and samples[index+1].time<=t do index=index+1 end
        if samples[index]~=current then
            current=samples[index]
            totals,bands=sampleValues(current,selected,characters,breakdown)
            for key,value in pairs(bands) do peaks[key]=math.max(peaks[key] or 0,value) end
        end
        points[#points+1]={time=t,raw=current,totals=totals,bands=bands}
    end
    local list,other=chartBands(peaks,selected,breakdown)
    local maxValue=1
    for _,point in ipairs(points) do
        local folded=point.bands[F.OTHER_BAND] or 0
        for key in pairs(other) do folded=folded+(point.bands[key] or 0) end
        local sum=0
        point.values,point.other={},other
        for _,key in ipairs(list) do
            sum=sum+(key==F.OTHER_BAND and folded or point.bands[key] or 0)
            point.values[#point.values+1]={key=key,value=sum}
        end
        maxValue=math.max(maxValue,sum)
    end
    return points,maxValue,first,span
end

-- Softens the drawn values over a few steps. Totals stay exact, and both ends keep
-- their true value.
function F.SmoothHistory(points,radius)
    local raw={}
    for i,p in ipairs(points) do
        raw[i]={}
        for j,v in ipairs(p.values) do raw[i][j]=v.value end
    end
    for i,p in ipairs(points) do
        local reach=math.min(radius,i-1,#points-i)
        for j,v in ipairs(p.values) do
            local sum,weight=0,0
            for k=-reach,reach do
                local w=reach+1-math.abs(k)
                sum=sum+raw[i+k][j]*w; weight=weight+w
            end
            v.value=sum/weight
        end
    end
end

-- When today's gain starts counting: the active marker's start, otherwise the
-- day's first login, or midnight for a session that began yesterday.
function F.GainStart(now)
    local events=F.db.events
    if F.db.episode then
        for i=#events,1,-1 do
            if events[i].kind=="episode_start" then return events[i].time end
        end
    end
    local t=date("*t",now)
    local midnight=now-(t.hour*3600+t.min*60+t.sec)
    local first=midnight
    for i=#events,1,-1 do
        if events[i].time<midnight then break end
        if events[i].kind=="session" then first=events[i].time end
    end
    return first
end

-- Gold change of each selected character since GainStart. Each character counts
-- from its own first sample in that time, so one first seen later starts from
-- the balance it arrived with.
local function goldChanges(characters,now)
    local start=F.GainStart(now)
    local baseline,latest,since={},{},{}
    for _,h in ipairs(F.ChartHistory(F.marketScope)) do
        if F.SameChart(h.scope,F.marketScope) and h.chars and h.time>=start then
            for guid in pairs(characters) do
                local v=h.chars[guid]
                if v then
                    if not baseline[guid] then baseline[guid]=v.gold or 0; since[guid]=h.time end
                    latest[guid]=v.gold or 0
                end
            end
        end
    end
    local changes={}
    for guid,gold in pairs(latest) do changes[guid]=gold-baseline[guid] end
    return changes,since,start
end

function F.GoldGain(characters,now)
    local gain=0
    for _,change in pairs(goldChanges(characters,now)) do gain=gain+change end
    return gain
end

local GAIN_LABELS={repair="Repair costs",loot="Loot",quest="Quest rewards",
    auction_sale="Auction house sales",auction_purchase="Auction house purchases",
    auction_purchase_or_bid="Auction house purchases",auction_deposit="Auction house fees",
    auction_cancel_fee="Auction house fees",vendor_sale="Vendor sales",vendor_purchase="Vendor purchases",
    vendor_buyback="Vendor purchases",flight="Flights",training="Training",mail_received="Mail received",
    mail_sent="Mail sent",mail_cod="Cash on delivery",postage="Postage",trade="Trades",
    bank_deposit="Bank",bank_withdrawal="Bank"}

-- GoldGain split by what caused it: the gain, rows that add up to it exactly, and
-- when it starts counting. Linked accounts share balances but not their records, so
-- their change is one row. Whatever no record explains is a row of its own.
function F.GainBreakdown(characters,now)
    local changes,since,start=goldChanges(characters,now)
    local gain,linked,explained,byLabel=0,0,0,{}
    for guid,change in pairs(changes) do
        gain=gain+change
        if not F.db.characters[guid] then linked=linked+change end
    end
    local events=F.db.events
    for i=#events,1,-1 do
        local e=events[i]
        if e.time<start then break end
        if e.kind=="activity" and since[e.character] and F.EventTime(e)>=since[e.character] and (e.data.amount or 0)~=0 then
            local name=GAIN_LABELS[e.data.category] or e.data.category
            byLabel[name]=(byLabel[name] or 0)+e.data.amount
            explained=explained+e.data.amount
        end
    end
    byLabel["Linked accounts"]=linked
    byLabel["Not identified"]=gain-linked-explained
    local rows={}
    for name,value in pairs(byLabel) do
        if value~=0 then rows[#rows+1]={label=name,value=value} end
    end
    table.sort(rows,function(a,b) if a.value==b.value then return a.label<b.label end; return a.value>b.value end)
    return gain,rows,start
end

-- Episode starts and ends inside a time range. An end that overlaps the next
-- start is dropped, so only that start shows.
function F.EpisodeMarkers(first,last,overlap)
    local markers={}
    for _,e in ipairs(F.db.events) do
        if (e.kind=="episode_start" or e.kind=="episode_end") and e.time>=first and e.time<=last then
            local m={time=e.time,start=e.kind=="episode_start",name=e.data.name}
            local previous=markers[#markers]
            if m.start and previous and not previous.start and m.time-previous.time<=overlap then
                markers[#markers]=m
            else markers[#markers+1]=m end
        end
    end
    return markers
end
