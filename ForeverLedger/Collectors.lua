local _, F = ...
F.context = {}
F.pendingPosts, F.mailLeaving, F.cancelling = {}, {}, {}

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
    F.Snapshot("bags",rows,complete,nil,force)
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
                quantity=v[3],status=v[16],totalBuyout=v[10],bid=v[11],minBid=v[8],legacy=true}
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

-- Taking mail is only proven by the mail changing. Clients differ in what they confirm:
-- TBC sends no MAIL_SUCCESS with an item, and mail addons retry takes that already paid.
local function mailKey(m) return F.JSON({m.sender or "",m.subject or ""}) end
F.MailKey=mailKey

-- What left one mail between two reads, or nil if nothing did.
local function taken(before,after)
    local left={}
    local function attachment(r) return tostring(r.item.link)..":"..tostring(r.quantity) end
    for _,r in ipairs(after and after.items or {}) do
        left[attachment(r)]=(left[attachment(r)] or 0)+1
    end
    local items={}
    for _,r in ipairs(before.items) do
        local key=attachment(r)
        if (left[key] or 0)>0 then left[key]=left[key]-1 else items[#items+1]=r end
    end
    local money=before.money-(after and after.money or 0)
    if money<=0 and #items==0 then return nil end
    local mail=F.Copy(before)
    mail.money,mail.items=math.max(money,0),items
    mail.cod=math.max(before.cod-(after and after.cod or 0),0)
    mail.mode=money<=0 and "item" or #items>0 and "all" or "money"
    return mail
end

-- What left the mailbox between two complete reads. Mails with the same sender and
-- subject are interchangeable, and unchanged ones cancel out first.
function F.MailTaken(before,after)
    local now,result={},{}
    for _,m in ipairs(after) do
        local key=mailKey(m)
        now[key]=now[key] or {}
        table.insert(now[key],m)
    end
    local changed={}
    for _,b in ipairs(before) do
        local rows,same=now[mailKey(b)] or {},nil
        for i,a in ipairs(rows) do
            if a.money==b.money and #a.items==#b.items then same=i; break end
        end
        if same then table.remove(rows,same) else changed[#changed+1]=b end
    end
    for _,b in ipairs(changed) do
        local key=mailKey(b)
        local a=now[key] and table.remove(now[key],1)
        if not a and (F.mailLeaving[key] or 0)>0 then
            F.mailLeaving[key]=F.mailLeaving[key]-1
        else
            local mail=taken(b,a)
            if mail then result[#result+1]=mail end
        end
    end
    return result
end

function F.CollectMail(before,after)
    for _,mail in ipairs(F.MailTaken(before,after)) do
        F.Emit("mail_collected",mail)
        if mail.cod>0 then F.Claim("mail_cod",-mail.cod,{sender=mail.sender,items=mail.items}) end
        F.Invoice(mail)
    end
end

function F.ScanMail()
    if not F.context.mail then return end
    local count,total=F.Call(GetInboxNumItems)
    if not count then return end
    local rows={}
    for index=1,count do
        local mail=F.ReadMail(index)
        if mail then rows[#rows+1]=mail end
    end
    -- A row still loading would look collected, so compare full reads only.
    if #rows==count then
        if F.mailSeen then F.CollectMail(F.mailSeen,rows) end
        F.mailSeen=rows
    end
    F.Snapshot("mail",rows,#rows==count and (not total or count>=total),{visible=count,total=total})
end

-- A returned or deleted mail also leaves the mailbox, but nobody received its contents.
function F.MailLeaving(index)
    local mail=F.ReadMail(index)
    if mail and (mail.money>0 or #mail.items>0) then
        local key=mailKey(mail)
        F.mailLeaving[key]=(F.mailLeaving[key] or 0)+1
    end
end

-- Earlier versions lost mail collected while a take went unconfirmed, and could record a
-- retried take twice. Past mailbox reads show what really left the inbox. A correction
-- is only made when it equals, to the copper, the gold nothing explained at the time.
local BACKFILL_GAP,BACKFILL_LEAD,BACKFILL_SETTLE=60,5,10

local function backfillRecord(kind,data,source,time)
    data.occurredAt,data.backfilled=time,true
    local e=F.Emit(kind,data)
    e.character,e.characterName,e.realm=source.character,source.characterName,source.realm
    e.session,e.episode=source.session,source.episode
    return e
end

local function backfillAdd(mail,source,time)
    backfillRecord("mail_collected",F.Copy(mail),source,time)
    if mail.invoiceType=="seller" then
        local sale=F.Copy(mail)
        sale.matchConfidence="unmatched"
        local e=backfillRecord("auction_sale",sale,source,time)
        backfillRecord("activity",{category="auction_sale",amount=mail.money,confidence="backfilled_snapshot",saleID=e.id,
            item=mail.item,gross=mail.gross,commission=mail.commission,depositRefund=mail.depositRefund,quantity=mail.quantity},source,time)
    else
        local d=F.Copy(mail)
        d.category,d.amount,d.confidence="mail_received",mail.money,"backfilled_snapshot"
        backfillRecord("activity",d,source,time)
    end
end

-- Cancels a recorded take that paid nothing, keeping the record itself.
local function backfillVoid(entry,source,time)
    local a=entry.activity
    backfillRecord("activity",{category=a.data.category,amount=-a.data.amount,confidence="backfilled_snapshot",
        item=a.data.item,correctsActivityID=a.id,correctsSaleID=a.data.saleID},source,time)
end

-- One burst of corrections and the unexplained gold around it.
local function backfillCluster(cluster,session,result)
    local first,last=cluster[1].time,cluster[#cluster].time
    local net,residual,ids,added,removed=0,0,{},0,0
    for _,c in ipairs(cluster) do
        net=net+c.amount
        if c.amount>0 then added=added+1 else removed=removed+1 end
    end
    for _,r in ipairs(session.unresolved) do
        if r.time>=first-BACKFILL_LEAD and r.time<=last+BACKFILL_SETTLE then
            residual=residual+r.data.residual; ids[#ids+1]=r.id
        end
    end
    local applied=net==residual
    if applied then
        for _,c in ipairs(cluster) do
            if c.amount>0 then backfillAdd(c.mail,session.source,c.time) else backfillVoid(c,session.source,c.time) end
        end
        result.added,result.removed,result.amount=result.added+added,result.removed+removed,result.amount+net
    else result.skipped=result.skipped+1 end
    backfillRecord("mail_backfill",{status=applied and "applied" or "skipped",added=added,removed=removed,amount=net,
        residual=residual,reconciliationIDs=ids},session.source,first)
end

function F.BackfillMail()
    local db=F.db
    if db.mailBackfilled then return end
    db.mailBackfilled=true
    local sessions,order,sales={},{},{}
    local function sessionOf(e)
        local key=e.character..":"..tostring(e.session)
        if not sessions[key] then
            sessions[key]={source=e,found={},recorded={},unresolved={}}
            order[#order+1]=sessions[key]
        end
        return sessions[key]
    end
    for _,e in ipairs(db.events) do
        local d=e.data
        if e.kind=="snapshot" and d.location=="mail" then
            local s=sessionOf(e)
            if #d.rows==((d.metadata or {}).visible or #d.rows) then
                if s.seen then
                    for _,mail in ipairs(F.MailTaken(s.seen,d.rows)) do
                        if mail.money>0 then s.found[#s.found+1]={mail=mail,time=e.time,amount=mail.money} end
                    end
                end
                s.seen=d.rows
            end
        elseif e.kind=="auction_sale" then sales[e.id]=e
        elseif e.kind=="reconciliation" and d.status=="unresolved" then
            local s=sessionOf(e)
            s.unresolved[#s.unresolved+1]=e
        elseif e.kind=="activity" and (d.amount or 0)>0 then
            local mail=d.saleID and sales[d.saleID] and sales[d.saleID].data or d.category=="mail_received" and d
            if mail then
                local s=sessionOf(e)
                s.recorded[#s.recorded+1]={key=F.MailKey(mail),money=d.amount,activity=e}
            end
        end
    end
    local result={added=0,removed=0,amount=0,skipped=0}
    for _,s in ipairs(order) do
        local changes={}
        for _,f in ipairs(s.found) do
            local key,matched=F.MailKey(f.mail),false
            for i,r in ipairs(s.recorded) do
                if r.key==key and r.money==f.mail.money then table.remove(s.recorded,i); matched=true; break end
            end
            if not matched then changes[#changes+1]=f end
        end
        for _,r in ipairs(s.recorded) do
            changes[#changes+1]={activity=r.activity,time=r.activity.time,amount=-r.money}
        end
        table.sort(changes,function(a,b) return a.time<b.time end)
        local cluster={}
        for _,c in ipairs(changes) do
            if cluster[1] and c.time-cluster[#cluster].time>BACKFILL_GAP then
                backfillCluster(cluster,s,result); cluster={}
            end
            cluster[#cluster+1]=c
        end
        if cluster[1] then backfillCluster(cluster,s,result) end
    end
    if result.added+result.removed>0 and F.Print then
        F.Print("Recovered "..result.added.." missed mail collections from earlier records.")
    end
    return result
end

-- GetSendMailPrice includes the money being sent on some clients and not on others. Every
-- send pays at least 30 copper an attachment, so what is left after the money tells which.
local POSTAGE_PER_ATTACHMENT=30

function F.MailPostage(price,money,attachments)
    if price and price-money>=POSTAGE_PER_ATTACHMENT*math.max(attachments,1) then return price-money end
    return price
end

local function repairPostage(entries,residual,ids,result)
    local over,first=0,entries[1].activity
    for _,w in ipairs(entries) do over=over+w.over end
    local applied=over==residual
    if applied then
        for _,w in ipairs(entries) do
            local a=w.activity
            backfillVoid(w,a,a.time)
            backfillRecord("activity",{category="postage",amount=-w.postage,confidence="backfilled_snapshot",
                recipient=a.data.recipient},a,a.time)
        end
        result.fixed,result.amount=result.fixed+#entries,result.amount+over
    else result.skipped=result.skipped+#entries end
    backfillRecord("mail_backfill",{repair="postage",status=applied and "applied" or "skipped",added=0,removed=0,
        amount=over,residual=residual,reconciliationIDs=ids},first,first.time)
end

-- Earlier versions also booked the money sent as postage. Sent mail records show how much,
-- and as with BackfillMail a correction must equal, to the copper, the gold left unexplained.
function F.RepairPostage()
    local db=F.db
    if db.postageRepaired then return end
    db.postageRepaired=true
    local sent,wrong,groups={},{},{}
    for _,e in ipairs(db.events) do
        local d=e.data
        if e.kind=="mail_sent" then sent[e.character]=e
        elseif e.kind=="activity" and d.category=="postage" then
            local mail=sent[e.character]
            sent[e.character]=nil
            if mail and -d.amount==mail.data.postage then
                local postage=F.MailPostage(mail.data.postage,mail.data.money or 0,#(mail.data.items or {}))
                if postage~=mail.data.postage then
                    local w={activity=e,postage=postage,over=mail.data.postage-postage}
                    wrong[#wrong+1]=w; wrong[e.id]=w
                end
            end
        elseif e.kind=="reconciliation" and d.status=="unresolved" then
            local entries={}
            for _,id in ipairs(d.activityIDs or {}) do
                local w=wrong[id]
                if w then entries[#entries+1]=w; w.settled=true end
            end
            if entries[1] then groups[#groups+1]={entries=entries,residual=d.residual,ids={e.id}} end
        end
    end
    for _,w in ipairs(wrong) do
        if not w.settled then groups[#groups+1]={entries={w},residual=0,ids={}} end
    end
    local result={fixed=0,amount=0,skipped=0}
    for _,g in ipairs(groups) do repairPostage(g.entries,g.residual,g.ids,result) end
    if result.fixed>0 and F.Print then
        F.Print("Corrected postage on "..result.fixed.." sent mails from earlier records.")
    end
    return result
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

function F.CapturePost(location,duration,quantity,bid,buyout,commodity,confirm)
    local link=F.Call(C_Item and C_Item.GetItemLink,location)
    local item=F.Item(link)
    local api=C_AuctionHouse
    local deposit
    if commodity then deposit=F.Call(api.CalculateCommodityDeposit,item.id,duration,quantity)
    else deposit=F.Call(api.CalculateItemDeposit,location,duration,quantity) end
    local d={item=item,duration=duration,quantity=F.Number(quantity),deposit=F.Number(deposit),
        totalPrice=commodity and (F.Number(buyout) or 0)*(F.Number(quantity) or 0) or F.Number(buyout),
        bid=F.Number(bid),commodity=commodity,clock=F.Clock()}
    local function same(p) return p.item.link==d.item.link and p.quantity==d.quantity and p.totalPrice==d.totalPrice end
    -- A Confirm* call completes a warned post; it is the same auction, not another one.
    if confirm then
        for i=#F.pendingPosts,1,-1 do
            local p=F.pendingPosts[i]
            if same(p) then p.awaitingConfirm=nil; p.clock=d.clock; return end
        end
    end
    local last=F.pendingPosts[#F.pendingPosts]
    if last and d.clock-last.clock<0.2 and same(last) then return end
    F.pendingPosts[#F.pendingPosts+1]=d
    F.Emit("auction_post_intent",d)
end

-- One multisell call creates `multisell` separate auctions sharing the quantity
-- and deposit; rounding remainders fall to the later auctions.
local function nextAuction(d)
    local n=d.multisell
    d.multisell=nil
    if not n or n<2 then return d,true end
    local one=F.Copy(d)
    one.quantity=d.quantity and math.floor(d.quantity/n)
    one.deposit=d.deposit and math.floor(d.deposit/n)
    d.quantity=d.quantity and d.quantity-one.quantity
    d.deposit=d.deposit and d.deposit-one.deposit
    d.multisell=n-1; d.clock=F.Clock()
    return one,false
end

function F.Created(id)
    if F.db.auctions[F.AuctionKey(id)] then return end
    local keep,d={},nil
    for _, p in ipairs(F.pendingPosts) do
        if F.Clock()-p.clock<30 then
            -- A post waiting on its warning dialog has not created anything yet.
            if not d and not p.awaitingConfirm then d=p else keep[#keep+1]=p end
        end
    end
    if d then
        local post,last=nextAuction(d)
        if not last then table.insert(keep,1,d) end
        d=post; d.clock=nil; d.matchConfidence="ordered_confirmation"
    end
    F.pendingPosts=keep
    F.Posted(id,d)
end

-- A merchant item's price, stack size and name. Newer clients, Forever among them,
-- moved these into C_MerchantFrame.GetItemInfo, which returns a table, and dropped
-- GetMerchantItemInfo, so a buy there used to leave no record of what was bought.
function F.MerchantItem(index)
    local info=C_MerchantFrame and F.Call(C_MerchantFrame.GetItemInfo,index)
    if type(info)=="table" then return F.Number(info.price),F.Number(info.stackCount),info.name end
    local v={F.Call(GetMerchantItemInfo,index)}
    return F.Number(v[3]),F.Number(v[4]),v[1]
end

function F.InstallHooks()
    local api=C_AuctionHouse
    for _, def in ipairs({{"PostItem",false},{"ConfirmPostItem",true}}) do
        Hook(api,def[1],function(loc,d,q,b,p) F.CapturePost(loc,d,q,b,p,false,def[2]) end)
    end
    for _, def in ipairs({{"PostCommodity",false},{"ConfirmPostCommodity",true}}) do
        Hook(api,def[1],function(loc,d,q,p) F.CapturePost(loc,d,q,nil,p,true,def[2]) end)
    end
    Hook(api,"PlaceBid",function(id,amount)
        F.Intent("auction_purchase_or_bid",-amount,{auctionID=id})
    end)
    -- A legacy post charges each stack as it is created. The item is still in the sell
    -- slot when this runs. A post the client refuses simply leaves its intents unmatched.
    Hook("PostAuction",function(bid,buyout,runTime,stackSize,numStacks)
        if not F.LegacyAH() then return end
        local deposit=F.Number(F.Call(GetAuctionDeposit,runTime,bid,buyout,stackSize,1))
        if not deposit then return end
        local v={F.Call(GetAuctionSellItemInfo)}
        local item=F.Item(nil,v[10],v[1])
        numStacks=F.Number(numStacks) or 1
        for _=1,numStacks do
            F.Intent("auction_deposit",-deposit,{item=item,quantity=stackSize},15+numStacks*2)
        end
    end)
    Hook("PlaceAuctionBid",function(list,index,bid)
        bid=F.Number(bid)
        local quantity=F.Number(select(3,F.Call(GetAuctionItemInfo,list,index)))
        if bid then F.Intent("auction_purchase_or_bid",-bid,{item=F.Item(F.Call(GetAuctionItemLink,list,index)),quantity=quantity}) end
    end)
    Hook(api,"CancelAuction",function(id)
        F.cancelling[F.AuctionKey(id)]=F.Clock()
        local cost=F.Number(F.Call(api.GetCancelCost,id))
        if cost and cost>0 then F.Intent("auction_cancel_fee",-cost,{auctionID=id,auctionKey=F.AuctionKey(id)}) end
    end)
    Hook(api,"ConfirmCommoditiesPurchase",function(id,quantity)
        if F.commodityQuote then
            F.Intent("auction_purchase",-F.commodityQuote.total,{item=F.Item(nil,id),quantity=quantity})
        end
    end)
    Hook("ReturnInboxItem",F.MailLeaving)
    Hook("DeleteInboxItem",F.MailLeaving)
    Hook("SendMail",function(recipient)
        if F.pendingSend then return end
        local money=F.Number(F.Call(GetSendMailMoney)) or 0
        local d={recipient=F.FullName(recipient),money=money,cod=F.Number(F.Call(GetSendMailCOD)),items={}}
        for i=1,(ATTACHMENTS_MAX_SEND or 12) do
            local link=F.Call(GetSendMailItemLink,i)
            if link then
                local v={F.Call(GetSendMailItem,i)}
                d.items[#d.items+1]={item=F.Item(link),quantity=F.Number(v[4]) or 1}
            end
        end
        d.postage=F.MailPostage(F.Number(F.Call(GetSendMailPrice)),money,#d.items)
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
        local price,stack,name=F.MerchantItem(index)
        local link=F.Call(GetMerchantItemLink,index) or (C_MerchantFrame and F.Call(C_MerchantFrame.GetItemLink,index))
        if price and stack and stack>0 then F.Intent("vendor_purchase",-math.floor(price*(quantity or 1)/stack),
            {item=F.Item(link,F.Call(GetMerchantItemID,index),name),quantity=quantity or 1}) end
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
    -- Whether the trainer teaches a profession tells class spells from recipes; a
    -- client without the function leaves it unknown rather than guessing.
    Hook("BuyTrainerService",function(index)
        local cost=F.Number(F.Call(GetTrainerServiceCost,index))
        if not cost then return end
        local d={service=F.Call(GetTrainerServiceInfo,index),skillLine=F.Call(GetTrainerServiceSkillLine,index)}
        if type(IsTradeskillTrainer)=="function" then d.trainer=F.Call(IsTradeskillTrainer) and "profession" or "class" end
        F.Intent("training",-cost,d)
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
    AUCTION_MULTISELL_START=function(count)
        local d=F.pendingPosts[#F.pendingPosts]
        count=F.Number(count)
        if d and count and count>1 then d.multisell=count end
    end,
    AUCTION_HOUSE_POST_WARNING=function()
        local d=F.pendingPosts[#F.pendingPosts]
        if d then d.awaitingConfirm=true end
    end,
    AUCTION_CANCELED=function(id) F.AuctionLeft(id) end,
    AUCTION_HOUSE_AUCTIONS_EXPIRED=function(id) F.AuctionOutcome(F.AuctionKey(id),"expired","server_id") end,
    COMMODITY_PRICE_UPDATED=function(unit,total) F.commodityQuote={unit=F.Number(unit),total=F.Number(total)} end,
    COMMODITY_PURCHASE_FAILED=function() F.commodityQuote=nil end,
    AUCTION_HOUSE_PURCHASE_COMPLETED=function(id) F.Emit("auction_purchase_confirmed",{auctionID=id}) end,
    MAIL_SHOW=function() F.context.mail=true; F.ScanMail() end,
    MAIL_INBOX_UPDATE=function() F.mailDirty=true end,
    MAIL_CLOSED=function() F.context.mail=nil; F.mailSeen=nil; F.mailLeaving={} end,
    MAIL_SUCCESS=function() F.mailDirty=true end,
    MAIL_FAILED=function() F.pendingSend=nil end,
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
