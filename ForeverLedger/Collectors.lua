local _, F = ...
F.context = {}
F.pendingPosts, F.mailCache = {}, {}

function F.Call(fn, ...)
    if type(fn) ~= "function" then return nil end
    local function pack(...) return {n=select("#",...),...} end
    local r = pack(pcall(fn, ...))
    if not r[1] then return nil end
    return unpack(r, 2, r.n)
end

function F.Item(link, id, name)
    if issecretvalue and issecretvalue(link) then return {unavailable=true} end
    id = F.Number(id) or (type(link)=="string" and tonumber(link:match("item:(%d+)")))
    local get = C_Item and C_Item.GetItemInfo or GetItemInfo
    local values = {F.Call(get, link or id)}
    local item = {id=id, link=link or values[2], name=name or values[1], vendorPrice=F.Number(values[11]),
        quality=values[3],level=values[4],equipLoc=values[9],classID=values[12],subclassID=values[13],
        bindType=values[14],expansionID=values[15]}
    if F.TrackItem then F.TrackItem(item) end
    return item
end

function F.Location()
    return {zone=F.Call(GetZoneText), subzone=F.Call(GetSubZoneText),
        mapID=C_Map and F.Call(C_Map.GetBestMapForUnit,"player")}
end

function F.BagRows(ids)
    local rows = {}
    for _, bag in ipairs(ids) do
        local slots = F.Call(C_Container and C_Container.GetContainerNumSlots,bag)
        if slots == nil then return rows,false end
        for slot=1,slots do
            local info = F.Call(C_Container.GetContainerItemInfo,bag,slot)
            if info then
                local quantity = F.Number(info.stackCount)
                if not quantity then return rows,false end
                local item=F.Item(info.hyperlink,info.itemID)
                local loc=ItemLocation and ItemLocation:CreateFromBagAndSlot(bag,slot)
                local bound=info.isBound
                if bound==nil and loc and C_Item then bound=F.Call(C_Item.IsBound,loc) end
                if bound==nil and item.bindType==0 then bound=false end
                local key=loc and C_AuctionHouse and F.Call(C_AuctionHouse.GetItemKeyFromItem,loc)
                if key then item.auctionItemKey=key; if F.TrackItem then F.TrackItem(item) end end
                rows[#rows+1] = {bag=bag,slot=slot,quantity=quantity,item=item,bound=bound,
                    guid=loc and C_Item and F.Call(C_Item.GetItemGUID,loc)}
            end
        end
    end
    return rows,true
end

function F.ScanBags(force)
    local ids = {}
    for id=0,(NUM_TOTAL_EQUIPPED_BAG_SLOTS or NUM_BAG_SLOTS or 4) do ids[#ids+1]=id end
    local rows,complete = F.BagRows(ids)
    -- Only persistent item facts participate in this signature.
    local signature = F.JSON(rows)
    if force or signature ~= F.lastBags then
        F.lastBags=signature
        F.Snapshot("bags",rows,complete)
    end
end

function F.ScanBank()
    if not F.context.bank then return end
    local ids = {}
    local tabs = C_Bank and Enum and Enum.BankType and
        F.Call(C_Bank.FetchPurchasedBankTabIDs,Enum.BankType.Character)
    if tabs and #tabs>0 then
        ids=tabs
    else
        ids={BANK_CONTAINER or -1}
        local first=(NUM_TOTAL_EQUIPPED_BAG_SLOTS or NUM_BAG_SLOTS or 4)+1
        for id=first,first+(NUM_BANKBAGSLOTS or 7)-1 do ids[#ids+1]=id end
    end
    local rows,complete=F.BagRows(ids)
    F.Snapshot("bank",rows,complete,{containerIDs=ids})
end

function F.ScanEquipment()
    local rows={}
    for slot=1,19 do
        local link=F.Call(GetInventoryItemLink,"player",slot)
        if link then
            local loc=ItemLocation and ItemLocation:CreateFromEquipmentSlot(slot)
            rows[#rows+1]={slot=slot,quantity=1,item=F.Item(link),bound=true,equipped=true,
                guid=loc and C_Item and F.Call(C_Item.GetItemGUID,loc)}
        end
    end
    F.Snapshot("equipment",rows,true)
end

function F.ScanAuctions()
    if not F.context.auction then return end
    if F.LegacyAH and F.LegacyAH() and GetNumAuctionItems then
        local count,total=F.Call(GetNumAuctionItems,"owner")
        if not count then return end
        local rows={}
        for i=1,count do
            local v={F.Call(GetAuctionItemInfo,"owner",i)}
            rows[#rows+1]={item=F.Item(F.Call(GetAuctionItemLink,"owner",i),v[17],v[1]),
                quantity=v[3],status=v[16],totalBuyout=v[10],bid=v[11],legacy=true}
        end
        F.Snapshot("auctions",rows,count==total,{legacy=true}); return
    end
    local api=C_AuctionHouse
    local auctions=api and F.Call(api.GetOwnedAuctions)
    if not auctions then return end
    local rows={}
    for _, a in ipairs(auctions) do
        local id=F.Number(a.auctionID)
        if id then
            local item=F.Item(a.itemLink,a.itemKey and a.itemKey.itemID)
            item.auctionItemKey=F.Copy(a.itemKey)
            if F.TrackItem then F.TrackItem(item) end
            rows[#rows+1]={auctionID=id,auctionKey=F.AuctionKey(id),
                item=item,
                quantity=F.Number(a.quantity),status=F.Number(a.status),
                totalBuyout=F.Number(a.buyoutAmount),bid=F.Number(a.bidAmount),
                secondsLeft=F.Number(a.timeLeftSeconds)}
        end
    end
    local complete=F.Call(api.HasFullOwnedAuctionResults)==true
    F.Snapshot("auctions",rows,complete)
    -- Disappearance alone is never interpreted as an expiration or sale.
end

local function matchesSubject(subject, format)
    if not format or not subject then return false end
    local p=format:gsub("([%^%$%(%)%%%.%[%]%*%+%-%?])","%%%1")
    p=p:gsub("%%%%s",".+"):gsub("%%%%d","%%d+")
    return subject:match("^"..p.."$")~=nil
end

function F.ReadMail(index)
    local h={F.Call(GetInboxHeaderInfo,index)}
    if not h[4] or h[4]==RETRIEVING_DATA then return nil end
    local v={F.Call(GetInboxInvoiceInfo,index)}
    local items={}
    for slot=1,(ATTACHMENTS_MAX_RECEIVE or ATTACHMENTS_MAX or 16) do
        local link=F.Call(GetInboxItemLink,index,slot)
        if link then
            local item={F.Call(GetInboxItem,index,slot)}
            items[#items+1]={slot=slot,item=F.Item(link,item[2],item[1]),quantity=F.Number(item[4]) or 1}
        end
    end
    local item=items[1] and items[1].item or F.Item(nil,nil,v[2])
    local failure
    if matchesSubject(h[4],AUCTION_EXPIRED_MAIL_SUBJECT) then failure="expired" end
    if matchesSubject(h[4],AUCTION_REMOVED_MAIL_SUBJECT) then failure="cancelled" end
    local quantity=F.Number(v[11]) or (items[1] and items[1].quantity) or 1
    return {index=index,sender=F.FullName(h[3]),subject=h[4],money=F.Number(h[5]) or 0,
        cod=F.Number(h[6]) or 0,items=items,item=item,quantity=quantity,
        invoiceType=v[1],gross=F.Number(v[4]),depositRefund=F.Number(v[6]),
        commission=F.Number(v[7]),counterparty=v[3],failure=failure}
end

function F.ScanMail()
    if not F.context.mail then return end
    local count,total=F.Call(GetInboxNumItems)
    if not count then return end
    local rows,cache={},{}
    for index=1,count do
        local mail=F.ReadMail(index)
        if mail then cache[index]=mail; rows[#rows+1]=mail end
    end
    F.mailCache=cache
    F.Snapshot("mail",rows,#rows==count and (not total or count>=total),{visible=count,total=total})
end

function F.TakeMail(index, mode, slot)
    -- Only one mail command is accepted at once by the client. Do not replace
    -- the first command's cached identity on repeated clicks.
    if F.pendingMail then return end
    local mail=F.mailCache[index] or F.ReadMail(index)
    if not mail then return end
    mail=F.Copy(mail)
    mail.mode,mail.slot,mail.started=mode,slot,F.Clock()
    if mode=="item" then mail.money=0 end
    if mode=="money" then mail.items={}; mail.cod=0 end
    F.pendingMail=mail
end

function F.MailSuccess(itemID)
    local mail=F.pendingMail
    if not mail then return end
    if mail.mode=="money" and itemID~=nil then return end
    if mail.mode=="item" and itemID==nil then return end
    if mail.mode=="all" and mail.money>0 and itemID~=nil then return end
    F.pendingMail=nil
    if F.Clock()-mail.started>30 then
        F.Emit("diagnostic",{message="Stale mail confirmation",mail=mail}); return
    end
    if mail.mode=="item" then
        local selected={}
        for _, item in ipairs(mail.items) do if item.slot==mail.slot then selected[1]=item end end
        mail.items=selected
    end
    F.Emit("mail_collected",mail)
    if mail.cod>0 then F.Claim("mail_cod",-mail.cod,{sender=mail.sender,items=mail.items}) end
    F.Invoice(mail)
end

function F.UpdateTrade()
    if not F.trade then return end
    local d=F.trade
    d.counterparty=F.FullName(F.Call(GetUnitName,"NPC",true) or d.counterparty)
    d.moneyIn=F.Number(F.Call(GetTargetTradeMoney)) or d.moneyIn or 0
    d.moneyOut=F.Number(F.Call(GetPlayerTradeMoney)) or d.moneyOut or 0
    for _, side in ipairs({"Player","Target"}) do
        local items={}
        for i=1,(MAX_TRADABLE_ITEMS or 6) do
            local link=F.Call(_G["GetTrade"..side.."ItemLink"],i)
            if link then
                local v={F.Call(_G["GetTrade"..side.."ItemInfo"],i)}
                items[#items+1]={item=F.Item(link),quantity=F.Number(v[3]) or 1}
            end
        end
        d[side=="Player" and "itemsOut" or "itemsIn"]=items
    end
end

local function Hook(tableOrName, nameOrFn, fn)
    local function guarded(callback)
        return function(...)
            local ok,err=pcall(callback,...)
            if not ok and F.db then F.Emit("diagnostic",{message=tostring(err),hook=tostring(nameOrFn)}) end
        end
    end
    if type(tableOrName)=="string" then
        if type(_G[tableOrName])=="function" then hooksecurefunc(tableOrName,guarded(nameOrFn)) end
    elseif tableOrName and type(tableOrName[nameOrFn])=="function" then
        hooksecurefunc(tableOrName,nameOrFn,guarded(fn))
    end
end

function F.CapturePost(location,duration,quantity,bid,buyout,commodity)
    local link=F.Call(C_Item and C_Item.GetItemLink,location)
    local item=F.Item(link)
    local api=C_AuctionHouse
    local deposit
    if commodity then deposit=F.Call(api.CalculateCommodityDeposit,item.id,duration,quantity)
    else deposit=F.Call(api.CalculateItemDeposit,location,duration,quantity) end
    local d={item=item,duration=duration,quantity=F.Number(quantity),deposit=F.Number(deposit),
        totalPrice=commodity and (F.Number(buyout) or 0)*(F.Number(quantity) or 0) or F.Number(buyout),
        bid=F.Number(bid),commodity=commodity,clock=F.Clock()}
    local last=F.pendingPosts[#F.pendingPosts]
    if last and d.clock-last.clock<0.2 and last.item.link==d.item.link and
        last.quantity==d.quantity and last.totalPrice==d.totalPrice then return end
    F.pendingPosts[#F.pendingPosts+1]=d
    F.Emit("auction_post_intent",d)
end

function F.Created(id)
    if F.db.auctions[F.AuctionKey(id)] then return end
    local candidates={}
    for _, d in ipairs(F.pendingPosts) do
        if F.Clock()-d.clock<30 then candidates[#candidates+1]=d end
    end
    local d=table.remove(candidates,1)
    F.pendingPosts=candidates
    if d then d.clock=nil; d.matchConfidence="ordered_confirmation" end
    F.Posted(id,d)
end

function F.InstallHooks()
    local api=C_AuctionHouse
    for _, name in ipairs({"PostItem","ConfirmPostItem"}) do
        Hook(api,name,function(loc,d,q,b,p) F.CapturePost(loc,d,q,b,p,false) end)
    end
    for _, name in ipairs({"PostCommodity","ConfirmPostCommodity"}) do
        Hook(api,name,function(loc,d,q,p) F.CapturePost(loc,d,q,nil,p,true) end)
    end
    Hook(api,"PlaceBid",function(id,amount)
        F.Intent("auction_purchase_or_bid",-amount,{auctionID=id})
    end)
    Hook(api,"CancelAuction",function(id)
        local cost=F.Number(F.Call(api.GetCancelCost,id))
        if cost and cost>0 then F.Intent("auction_cancel_fee",-cost,{auctionID=id,auctionKey=F.AuctionKey(id)}) end
    end)
    Hook(api,"ConfirmCommoditiesPurchase",function(id,quantity)
        if F.commodityQuote then
            F.Intent("auction_purchase",-F.commodityQuote.total,{item=F.Item(nil,id),quantity=quantity})
        end
    end)
    Hook("TakeInboxMoney",function(i) F.TakeMail(i,"money") end)
    Hook("AutoLootMailItem",function(i) F.TakeMail(i,"all") end)
    Hook("TakeInboxItem",function(i,s) F.TakeMail(i,"item",s or 1) end)
    Hook("SendMail",function(recipient)
        if F.pendingSend then return end
        local money=F.Number(F.Call(GetSendMailMoney)) or 0
        local price=F.Number(F.Call(GetSendMailPrice))
        local d={recipient=F.FullName(recipient),money=money,cod=F.Number(F.Call(GetSendMailCOD)),
            postage=price and price-money or nil,items={}}
        for i=1,(ATTACHMENTS_MAX_SEND or 12) do
            local link=F.Call(GetSendMailItemLink,i)
            if link then
                local v={F.Call(GetSendMailItem,i)}
                d.items[#d.items+1]={item=F.Item(link),quantity=F.Number(v[4]) or 1}
            end
        end
        F.pendingSend=d
    end)
    local function tradeMoney(amount) if F.trade then F.trade.moneyOut=F.Number(amount) end end
    Hook("SetTradeMoney",tradeMoney); Hook(C_TradeInfo,"SetTradeMoney",tradeMoney)
    Hook(C_Container,"UseContainerItem",function(bag,slot)
        if not F.context.merchant then return end
        local info=F.Call(C_Container.GetContainerItemInfo,bag,slot)
        if info then
            local item=F.Item(info.hyperlink,info.itemID)
            if item.vendorPrice then F.Intent("vendor_sale",item.vendorPrice*info.stackCount,
                {item=item,quantity=info.stackCount}) end
        end
    end)
    Hook(C_MerchantFrame,"SellAllJunkItems",function()
        if not F.context.merchant then return end
        local ids={}
        for i=0,(NUM_TOTAL_EQUIPPED_BAG_SLOTS or NUM_BAG_SLOTS or 4) do ids[#ids+1]=i end
        local rows=F.BagRows(ids)
        local total,items=0,{}
        for _, r in ipairs(rows) do
            local info=F.Call(C_Container.GetContainerItemInfo,r.bag,r.slot)
            if info and info.quality==0 and r.item.vendorPrice and not info.hasNoValue then
                total=total+r.item.vendorPrice*r.quantity; items[#items+1]=r
            end
        end
        F.Intent("vendor_sale",total,{items=items,method="sell_junk"})
    end)
    Hook("BuyMerchantItem",function(index,quantity)
        local v={F.Call(GetMerchantItemInfo,index)}
        local price,stack=F.Number(v[3]),F.Number(v[4])
        if price and stack and stack>0 then F.Intent("vendor_purchase",-math.floor(price*(quantity or 1)/stack),
            {item=F.Item(F.Call(GetMerchantItemLink,index)),quantity=quantity or 1}) end
    end)
    Hook("BuybackItem",function(index)
        local v={F.Call(GetBuybackItemInfo,index)}
        if F.Number(v[3]) then F.Intent("vendor_buyback",-v[3],
            {item=F.Item(F.Call(GetBuybackItemLink,index)),quantity=v[4]}) end
    end)
    Hook("RepairAllItems",function(guild)
        if not guild and F.repairCost then F.Intent("repair",-F.repairCost,{}) end
    end)
    Hook("TakeTaxiNode",function(index)
        local price=F.Number(F.Call(TaxiNodeCost,index))
        if price then F.Intent("flight",-price,{destination=F.Call(TaxiNodeName,index)}) end
    end)
    Hook("BuyTrainerService",function(index)
        local cost=F.Number(F.Call(GetTrainerServiceCost,index))
        if cost then F.Intent("training",-cost,{service=F.Call(GetTrainerServiceInfo,index)}) end
    end)
    for _, def in ipairs({{"DepositMoney","bank_deposit",-1},{"WithdrawMoney","bank_withdrawal",1}}) do
        local name,category,sign=def[1],def[2],def[3]
        Hook(C_Bank,name,function(bankType,amount) F.Intent(category,sign*amount,{bankType=bankType}) end)
    end
end

function F.ParseMoney(text)
    if type(text)~="string" then return nil end
    local sum,found=0,false
    for _, d in ipairs({{GOLD_AMOUNT,10000},{SILVER_AMOUNT,100},{COPPER_AMOUNT,1}}) do
        if d[1] then
            local p=d[1]:gsub("([%^%$%(%)%%%.%[%]%*%+%-%?])","%%%1"):gsub("%%%%d","([%%d,%.]+)")
            local n=text:match(p)
            if n then n=tonumber((n:gsub("[,%.]",""))); if n then sum=sum+n*d[2]; found=true end end
        end
    end
    return found and sum or nil
end

F.events={
    PLAYER_MONEY=function() F.ObserveBalance(GetMoney(),F.context) end,
    QUEST_TURNED_IN=function(id,xp,money) F.Claim("quest",money,{questID=id,xp=xp,location=F.Location()}) end,
    QUEST_LOOT_RECEIVED=function(id,link,q) F.Emit("quest_item",{questID=id,item=F.Item(link),quantity=q}) end,
    CHAT_MSG_MONEY=function(text)
        local n=F.ParseMoney(text)
        F.Emit("loot_money_message",{text=text,amount=n,location=F.Location()})
        if n then F.Claim("loot",n,{location=F.Location()},"parsed_message") end
    end,
    CHAT_MSG_LOOT=function(text) F.Emit("loot_message",{text=text,location=F.Location()}) end,
    BAG_UPDATE_DELAYED=function() F.bagDirty=F.Clock() end,
    PLAYER_EQUIPMENT_CHANGED=function() F.equipmentDirty=true; F.bagDirty=F.Clock() end,
    BANKFRAME_OPENED=function() F.context.bank=true; F.ScanBank() end,
    BANKFRAME_CLOSED=function() F.context.bank=nil end,
    PLAYERBANKSLOTS_CHANGED=function() F.bankDirty=true end,
    MERCHANT_SHOW=function() F.context.merchant=true; F.repairCost=F.Number(F.Call(GetRepairAllCost)) end,
    MERCHANT_UPDATE=function() F.repairCost=F.Number(F.Call(GetRepairAllCost)) end,
    MERCHANT_CLOSED=function() F.context.merchant=nil end,
    AUCTION_HOUSE_SHOW=function()
        F.context.auction=true
        if C_AuctionHouse then F.Call(C_AuctionHouse.QueryOwnedAuctions,{}) end
    end,
    AUCTION_HOUSE_CLOSED=function() F.context.auction=nil; if F.StopPrices then F.StopPrices("AH closed") end end,
    AUCTION_OWNED_LIST_UPDATE=function() F.ScanAuctions() end,
    OWNED_AUCTIONS_UPDATED=function() F.ScanAuctions() end,
    AUCTION_HOUSE_AUCTION_CREATED=function(id) F.Created(id) end,
    AUCTION_HOUSE_POST_ERROR=function(...) F.pendingPosts={}; F.Emit("auction_post_failed",{}) end,
    AUCTION_MULTISELL_FAILURE=function() F.pendingPosts={} end,
    AUCTION_CANCELED=function(id) F.AuctionOutcome(F.AuctionKey(id),"cancelled","server_id") end,
    AUCTION_HOUSE_AUCTIONS_EXPIRED=function(id) F.AuctionOutcome(F.AuctionKey(id),"expired","server_id") end,
    COMMODITY_PRICE_UPDATED=function(unit,total) F.commodityQuote={unit=F.Number(unit),total=F.Number(total)} end,
    COMMODITY_PURCHASE_FAILED=function() F.commodityQuote=nil end,
    AUCTION_HOUSE_PURCHASE_COMPLETED=function(id) F.Emit("auction_purchase_confirmed",{auctionID=id}) end,
    MAIL_SHOW=function() F.context.mail=true; F.ScanMail() end,
    MAIL_INBOX_UPDATE=function() F.mailDirty=true end,
    MAIL_CLOSED=function() F.context.mail=nil; F.mailCache={} end,
    MAIL_SUCCESS=function(id) F.MailSuccess(id) end,
    MAIL_FAILED=function() F.pendingMail=nil; F.pendingSend=nil end,
    MAIL_SEND_SUCCESS=function()
        local d=F.pendingSend; F.pendingSend=nil
        if not d then return end
        F.Emit("mail_sent",d)
        F.Claim("mail_sent",-d.money,{recipient=d.recipient,items=d.items})
        if d.postage then F.Claim("postage",-d.postage,{recipient=d.recipient}) end
    end,
    TRADE_SHOW=function() F.trade={moneyIn=0,moneyOut=0}; F.context.trade=true; F.UpdateTrade() end,
    TRADE_UPDATE=function() F.UpdateTrade() end,
    TRADE_MONEY_CHANGED=function() F.UpdateTrade() end,
    TRADE_PLAYER_ITEM_CHANGED=function() F.UpdateTrade() end,
    TRADE_TARGET_ITEM_CHANGED=function() F.UpdateTrade() end,
    TRADE_REQUEST_CANCEL=function() F.trade=nil end,
    TRADE_CLOSED=function() F.context.trade=nil end,
    UI_INFO_MESSAGE=function(_,text)
        if text==ERR_TRADE_COMPLETE and F.trade then
            local d=F.trade; F.trade=nil
            F.Claim("trade",(d.moneyIn or 0)-(d.moneyOut or 0),d)
        elseif text==ERR_TRADE_CANCELLED then F.trade=nil end
    end,
}
