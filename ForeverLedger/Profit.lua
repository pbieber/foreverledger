local _,F=...
-- Classes and subclasses as the client reports them for recorded items.
local TRADE_GOODS={[1]="Engineering",[2]="Engineering",[3]="Engineering",[4]="Gems",[5]="Cloth",[6]="Leather",
    [7]="Mining",[8]="Cooking",[9]="Herbs",[10]="Elemental",[12]="Enchanting"}
local MISCELLANEOUS={[2]="Pets",[5]="Mounts"}
local CLASSES={[0]="Consumables",[1]="Bags",[2]="Gear",[3]="Gems",[4]="Gear",[5]="Reagents",[6]="Ammo",
    [8]="Enchantments",[9]="Recipes",[11]="Bags",[12]="Quest items"}
local SOLD={auction_sale=true,vendor_sale=true}
local SPENT={auction_purchase=true,auction_purchase_or_bid=true,auction_deposit=true,auction_cancel_fee=true,
    vendor_purchase=true,vendor_buyback=true,mail_cod=true}
local MAX_STOCK=400
local COLUMNS={{"Category",0,126,"LEFT"},{"Held now",130,92},{"Sold",226,92},{"Spent",322,92},{"Stock change",418,92},{"Profit",514,98}}
local ROW_HEIGHT=14
local TABLE_TOP=-34

-- Auction invoices only name their item, so class details come from the catalog.
function F.ItemCategory(item,catalog,names)
    local known=item or {}
    if known.classID==nil and catalog then
        known=catalog[F.PriceKey(known)] or (names and known.name and names[known.name]) or known
    end
    local class=known.classID
    if class==nil then return "Unknown" end
    if class==7 then return TRADE_GOODS[known.subclassID] or "Other materials" end
    if class==15 then return MISCELLANEOUS[known.subclassID] or "Miscellaneous" end
    return CLASSES[class] or "Miscellaneous"
end

-- A character's value per category over time, kept only when it changes. The first
-- entry stays, because all-time profit counts from it. Items in a place seen for the
-- first time, such as a bank, were already owned, so they join the earlier entries
-- instead of counting as a gain.
function F.RememberStock(c,time,values,discovered)
    c.stock=c.stock or {}
    for _,entry in ipairs(c.stock) do
        for category,value in pairs(discovered or {}) do
            entry.values[category]=(entry.values[category] or 0)+value
        end
    end
    local last=c.stock[#c.stock]
    if last and F.JSON(last.values)==F.JSON(values) then return end
    c.stock[#c.stock+1]={time=time,values=values}
    if #c.stock>MAX_STOCK then table.remove(c.stock,2) end
end

-- What a character held at time t. One first seen later starts from its first entry.
function F.StockAt(c,t)
    local stock=c.stock or {}
    for i=#stock,1,-1 do
        if stock[i].time<=t then return stock[i].values end
    end
    return stock[1] and stock[1].values or {}
end

-- What any character held at time t. Linked accounts only send what their characters
-- hold now, so that stands in for every point in time.
function F.HeldAt(guid,t)
    local c=F.db.characters[guid]
    if c then return F.StockAt(c,t) end
    return F.LinkedHeld(guid)
end

-- This account's characters since a time, per item category: sold and spent are
-- recorded gold, and the stock change is estimated.
function F.AccountProfit(since)
    local catalog=F.market and F.market.catalog or {}
    local names={}
    for _,item in pairs(catalog) do
        if item.name then names[item.name]=item end
    end
    local byCharacter={}
    local function row(guid,category)
        local rows=byCharacter[guid] or {}
        byCharacter[guid]=rows
        rows[category]=rows[category] or {held=0,sold=0,spent=0,change=0}
        return rows[category]
    end
    local function book(guid,item,field,amount)
        local r=row(guid,F.ItemCategory(item,catalog,names))
        r[field]=r[field]+amount
    end
    local events=F.db.events
    for i=#events,1,-1 do
        local e=events[i]
        if e.time<since then break end
        local d=e.data
        local field=e.kind=="activity" and (SOLD[d.category] and "sold" or SPENT[d.category] and "spent")
        if field and (d.amount or 0)~=0 and F.EventTime(e)>=since then
            if d.method=="sell_junk" then
                for _,r in ipairs(d.items or {}) do book(e.character,r.item,field,(r.item.vendorPrice or 0)*(r.quantity or 0)) end
            else
                book(e.character,d.item or (d.items and d.items[1] and d.items[1].item),field,d.amount)
            end
        end
    end
    for guid,c in pairs(F.db.characters) do
        local latest=c.stock and c.stock[#c.stock]
        if latest then
            for category,value in pairs(latest.values) do
                local r=row(guid,category)
                r.held=r.held+value; r.change=r.change+value
            end
            for category,value in pairs(F.StockAt(c,since)) do
                local r=row(guid,category)
                r.change=r.change-value
            end
        end
    end
    return byCharacter
end

-- The selected characters per category, with what linked accounts last sent. Also
-- returns how current that linked data is.
function F.CategoryProfit(characters,since)
    local rows={}
    local function add(categories)
        for category,v in pairs(categories) do
            local r=rows[category] or {category=category,held=0,sold=0,spent=0,change=0}
            rows[category]=r
            r.held=r.held+v.held; r.sold=r.sold+v.sold; r.spent=r.spent+v.spent; r.change=r.change+v.change
        end
    end
    for guid,categories in pairs(F.AccountProfit(since)) do
        if characters[guid] then add(categories) end
    end
    local linked=F.LinkedProfit(characters,since,add)
    local list={}
    local total={category="Total",held=0,sold=0,spent=0,change=0,profit=0}
    for _,r in pairs(rows) do
        r.profit=r.sold+r.spent+r.change
        list[#list+1]=r
        for _,key in ipairs({"held","sold","spent","change","profit"}) do total[key]=total[key]+r[key] end
    end
    table.sort(list,function(a,b) if a.profit==b.profit then return a.category<b.category end; return a.profit>b.profit end)
    return list,total,linked
end

local function newRow(p,y,font)
    local cells={}
    for i,column in ipairs(COLUMNS) do
        local t=p:CreateFontString(nil,"OVERLAY",font or "GameFontHighlightSmall")
        t:SetPoint("TOPLEFT",column[2],y); t:SetWidth(column[3]); t:SetJustifyH(column[4] or "RIGHT")
        cells[i]=t
    end
    return cells
end

local function fill(cells,r)
    cells[1]:SetText(r.category)
    cells[2]:SetText(F.MoneyShort(r.held))
    cells[3]:SetText(F.GainText(r.sold))
    cells[4]:SetText(F.GainText(r.spent))
    cells[5]:SetText(F.GainText(r.change))
    cells[6]:SetText(F.GainText(r.profit))
end

function F.BuildProfitPanel(parent)
    local p=CreateFrame("Frame",nil,parent); p:SetPoint("TOPLEFT",16,-58); p:SetSize(612,430); p.rows={}
    F.profitPanel=p
    local function period(text,x,key)
        local b=CreateFrame("Button",nil,p,"UIPanelButtonTemplate")
        b:SetSize(96,24); b:SetPoint("TOPLEFT",x,0); b:SetText(text)
        b:SetScript("OnClick",function() F.db.settings.profitPeriod=key; F.SyncRefreshProfit(); F.RefreshProfit() end)
    end
    period("Today",0,"today"); period("All time",102,"all")
    p.scope=p:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall")
    p.scope:SetPoint("TOPLEFT",210,-1); p.scope:SetWidth(402); p.scope:SetJustifyH("RIGHT")
    p.linked=p:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall")
    p.linked:SetPoint("TOPLEFT",210,-14); p.linked:SetWidth(402); p.linked:SetJustifyH("RIGHT")
    local header=newRow(p,TABLE_TOP)
    for i,column in ipairs(COLUMNS) do header[i]:SetText("|cffa8a8a8"..column[1].."|r") end
    p.total=newRow(p,0)
    p.empty=p:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall")
    p.empty:SetPoint("TOPLEFT",0,TABLE_TOP-ROW_HEIGHT); p.empty:SetText("No item activity recorded yet.")
    p.note=p:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall")
    p.note:SetPoint("TOPLEFT",0,-370); p.note:SetWidth(612); p.note:SetJustifyH("LEFT")
    p.note:SetText("Profit = sold - spent + change in stock value. Stock uses estimated prices, so unsold items and price changes count; collect your mail for sales to show. "
        .."Loot gold, quests and repairs have no item: see Gain today. Items mailed to a character you have not selected count as a drop. Stock is tracked from this version on.")
    p:Hide()
end

function F.RefreshProfit()
    local p=F.profitPanel
    if not p then return end
    local allTime=F.db.settings.profitPeriod=="all"
    local characters=F.SelectedCharacters()
    local count,onLinked=0,0
    for guid in pairs(characters) do
        count=count+1
        if not F.db.characters[guid] then onLinked=onLinked+1 end
    end
    local since=allTime and 0 or F.GainStart(F.Now())
    local list,total,linked=F.CategoryProfit(characters,since)
    p.scope:SetText((allTime and "All time" or "Since "..date("%d %b %H:%M",since)).."  |  "..count..(count==1 and " character" or " characters")
        ..(onLinked>0 and ", "..onLinked.." on linked accounts" or ""))
    if linked.missing then p.linked:SetText("|cffffd100Linked account figures for this period arrive once it is online.|r")
    elseif linked.at then p.linked:SetText("Linked account figures from "..date("%d %b %H:%M",linked.at))
    else p.linked:SetText("") end
    for _,cells in ipairs(p.rows) do
        for _,t in ipairs(cells) do t:Hide() end
    end
    for i,r in ipairs(list) do
        local cells=p.rows[i]
        if not cells then cells=newRow(p,TABLE_TOP-i*ROW_HEIGHT); p.rows[i]=cells end
        fill(cells,r)
        for _,t in ipairs(cells) do t:Show() end
    end
    fill(p.total,total)
    for i,t in ipairs(p.total) do
        t:ClearAllPoints(); t:SetPoint("TOPLEFT",COLUMNS[i][2],TABLE_TOP-(#list+1)*ROW_HEIGHT-4)
        t:SetShown(#list>0)
    end
    p.empty:SetShown(#list==0)
end
