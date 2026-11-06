local _, F = ...
local WIDTH,HEIGHT=644,532
F.GoldIcon="|TInterface\\MoneyFrame\\UI-GoldIcon:0:0:2:0|t"
local SILVER,COPPER="|TInterface\\MoneyFrame\\UI-SilverIcon:0:0:2:0|t","|TInterface\\MoneyFrame\\UI-CopperIcon:0:0:2:0|t"
local function money(n)
    n=n or 0
    local sign=n<0 and "-" or ""
    n=math.abs(n)
    return string.format("%s%d%s %02d%s %02d%s",sign,math.floor(n/10000),F.GoldIcon,math.floor(n/100)%100,SILVER,n%100,COPPER)
end
F.Money=money

function F.MoneyShort(n)
    local sign=n<0 and "-" or ""
    n=math.abs(n)
    return string.format("%s%d%s %02d%s",sign,math.floor(n/10000),F.GoldIcon,math.floor(n/100)%100,SILVER)
end

function F.Summary()
    local lines={"FOREVER LEDGER  "..F.VERSION, "Account: "..(F.db.accountLabel or "unlabelled"),
        "Episode: "..(F.db.episode or "none"),"", "Recorded characters (last observed balances):"}
    local total=0
    for _, c in pairs(F.db.characters) do
        total=total+(c.balance or 0)
        lines[#lines+1]=(c.name or "?").."  "..money(c.balance)
    end
    lines[#lines+1]="Account total: "..money(total)
    F.SyncSummary(lines,total)
    lines[#lines+1]="Records: "..#F.db.events.." (saved by WoW on reload/logout)"
    lines[#lines+1]=""
    lines[#lines+1]="Current character snapshots (last observed; not live across alts):"
    for _, location in ipairs({"bags","bank","equipment","mail","auctions"}) do
        local s=F.character.snapshots[location]
        if not s then lines[#lines+1]=location..": not observed"
        else
            local vendor,market,missing,asking,pending=0,0,0,0,0
            for _, r in ipairs(s.data.rows) do
                if location=="auctions" then
                    if r.status==0 then asking=asking+(r.totalBuyout or 0) end
                elseif location=="mail" then pending=pending+(r.money or 0)
                elseif r.item then
                    vendor=vendor+(r.item.vendorPrice or 0)*(r.quantity or 0)
                    local value=F.ValueRow(r,F.character,F.marketScope)
                    market=market+value.value*(r.quantity or 0)
                    if value.partial then missing=missing+1 end
                end
            end
            local values=location=="auctions" and ("asking "..money(asking)) or
                location=="mail" and ("uncollected money "..money(pending)) or
                ("vendor "..money(vendor).." | estimated net "..money(market).." | partial rows "..missing)
            lines[#lines+1]=location..": "..values.." ["..(s.data.complete and "complete" or "partial")..
                ", "..math.max(0,F.Now()-s.time).."s old]"
        end
    end
    lines[#lines+1]=""
    lines[#lines+1]="Total value = gold + other assets + Equipped Gear. Estimates are not income."
    lines[#lines+1]="Bank/mail/AH and offline alts are last observed; stale snapshots may overlap."
    lines[#lines+1]="DE is expected net material value, available for bound gear only to its enchanter owner."
    lines[#lines+1]="AH commission assumption: "..(F.db.settings.commissionBps/100).."% (/fl fee 5 or /fl fee 15)."
    if F.isTBC then lines[#lines+1]="TBC preview: Outland DE tables and exact posting-to-return matching are not covered." end
    lines[#lines+1]="Linked accounts show their last synced values. Their raw records stay on that account; the database combines both."
    lines[#lines+1]=""
    lines[#lines+1]="Commands: /fl account Main | /fl own Name-Realm | /fl episode Episode 1"
    lines[#lines+1]="/fl end | /fl scan | /fl sync | /fl profit | /fl prices all | /fl prices oldest | /fl prices stop"
    lines[#lines+1]="/fl highlight [note] marks a moment to find in the recording; /fl highlight undo takes the last one back."
    return table.concat(lines,"\n")
end

function F.Journal(page)
    local lines={"Recent records (amounts are copper in the export):",""}
    local newest=#F.db.events-((page or 1)-1)*50
    for i=newest,math.max(1,newest-49),-1 do
        local e=F.db.events[i]
        lines[#lines+1]=e.sequence.."  "..e.kind.."  "..e.characterName.."  "..F.JSON(e.data)
    end
    return table.concat(lines,"\n")
end

function F.Show(mode,page)
    if not F.db then return end
    if not F.window then
        local w=CreateFrame("Frame","ForeverLedgerWindow",UIParent,"BasicFrameTemplateWithInset")
        w:SetSize(WIDTH,HEIGHT); w:SetPoint("CENTER"); w:SetMovable(true); w:EnableMouse(true)
        w:SetClampedToScreen(true)
        if GetScreenWidth and GetScreenHeight then w:SetScale(math.min(1,(GetScreenWidth()-40)/WIDTH,(GetScreenHeight()-40)/HEIGHT)) end
        w:RegisterForDrag("LeftButton")
        w:SetScript("OnDragStart",w.StartMoving); w:SetScript("OnDragStop",w.StopMovingOrSizing)
        w.TitleText:SetText("Forever Ledger")
        local scroll=CreateFrame("ScrollFrame",nil,w,"UIPanelScrollFrameTemplate")
        scroll:SetPoint("TOPLEFT",16,-90); scroll:SetPoint("BOTTOMRIGHT",-35,45)
        local edit=CreateFrame("EditBox",nil,scroll)
        edit:SetMultiLine(true); edit:SetAutoFocus(false); edit:SetFontObject(ChatFontNormal)
        edit:SetWidth(580); edit:SetMaxLetters(0)
        edit:SetScript("OnEscapePressed",function(self) self:ClearFocus(); w:Hide() end)
        edit:SetScript("OnTextChanged",function(self)
            local _,size=self:GetFont()
            self:SetHeight(math.max(380,(self:GetNumLines() or 1)*((size or 12)+3)+20))
        end)
        scroll:SetScrollChild(edit)
        -- A font string, because the summary shows coin icons an edit box cannot.
        local summaryScroll=CreateFrame("ScrollFrame",nil,w,"UIPanelScrollFrameTemplate")
        summaryScroll:SetPoint("TOPLEFT",16,-58); summaryScroll:SetPoint("BOTTOMRIGHT",-35,45)
        local summaryPage=CreateFrame("Frame",nil,summaryScroll); summaryPage:SetSize(580,380)
        local summaryText=summaryPage:CreateFontString(nil,"OVERLAY","GameFontHighlight")
        summaryText:SetPoint("TOPLEFT"); summaryText:SetWidth(580); summaryText:SetJustifyH("LEFT")
        summaryScroll:SetScrollChild(summaryPage)
        F.summaryScroll,F.summaryPage,F.summaryText=summaryScroll,summaryPage,summaryText
        local footer=w:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall")
        footer:SetPoint("BOTTOMLEFT",16,17); footer:SetWidth(612); footer:SetJustifyH("LEFT")
        local function button(parent,label,x,y,action,width)
            local b=CreateFrame("Button",nil,parent,"UIPanelButtonTemplate")
            b:SetSize(width or 96,24); b:SetPoint("TOPLEFT",x,y); b:SetText(label); b:SetScript("OnClick",action)
        end
        button(w,"Chart",16,-28,function() F.Show("overview") end,84)
        button(w,"Summary",104,-28,function() F.Show("summary") end,84)
        button(w,"Profit",192,-28,function() F.Show("profit") end,84)
        button(w,"Records",280,-28,function() F.Show("journal") end,84)
        button(w,"Refresh bags",368,-28,function() F.ScanBags(true); F.ScanEquipment(); F.ScanBank(); F.ScanMail(); F.ScanAuctions(); F.RecordValue(); F.Show(F.mode,F.page) end,84)
        button(w,"Set marker",456,-28,function() F.PromptMarker(true) end,84)
        button(w,"Sync",544,-28,function() F.Show("sync") end,84)
        local records=CreateFrame("Frame",nil,w); records:SetPoint("TOPLEFT",16,-58); records:SetSize(612,28)
        button(records,"Recent records",0,0,function() F.Show("journal") end)
        button(records,"Export JSON",102,0,function() F.Show("export",1) end)
        button(records,"Previous",204,0,function() F.Show(F.mode,math.max(1,(F.page or 1)-1)) end)
        button(records,"Next",306,0,function() F.Show(F.mode,(F.page or 1)+1) end)
        F.recordsBar=records
        F.window,F.edit,F.footer,F.scroll=w,edit,footer,scroll
        F.BuildChart(w)
        F.BuildSyncPanel(w)
        F.BuildProfitPanel(w)
        local scans=CreateFrame("Frame",nil,w); scans:SetPoint("TOPLEFT",16,-450); scans:SetSize(612,48)
        for i,def in ipairs({{"Scan all prices","all",140},{"Oldest 50 + unpriced","oldest",185},{"Stop scan","stop",100}}) do
            local b=CreateFrame("Button",nil,scans,"UIPanelButtonTemplate")
            b:SetSize(def[3],24); b:SetPoint("TOPLEFT",i==1 and 0 or i==2 and 148 or 341,0); b:SetText(def[1])
            local mode=def[2]
            b:SetScript("OnClick",function() if mode=="stop" then F.StopPrices("Stopped") else F.StartPrices(mode) end; F.RefreshScanStatus() end)
        end
        local mark=CreateFrame("Button",nil,scans,"UIPanelButtonTemplate")
        mark:SetSize(120,24); mark:SetPoint("TOPLEFT",492,0); mark:SetText("Mark highlight")
        mark:SetScript("OnClick",function() F.MarkHighlight() end)
        local status=scans:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall")
        status:SetPoint("TOPLEFT",0,-30); status:SetWidth(612); status:SetJustifyH("LEFT")
        F.scanControls,F.scanStatus=scans,status
        UISpecialFrames[#UISpecialFrames+1]="ForeverLedgerWindow"
    end
    F.mode,F.page=mode or "overview",page or 1
    local overview,summary,sync,profit=F.mode=="overview",F.mode=="summary",F.mode=="sync",F.mode=="profit"
    local records=not overview and not summary and not sync and not profit
    F.chart:SetShown(overview); F.scanControls:SetShown(overview); F.recordsBar:SetShown(records)
    F.scroll:SetShown(records); F.summaryScroll:SetShown(summary); F.syncPanel:SetShown(sync); F.profitPanel:SetShown(profit)
    if overview then F.RefreshChart(); F.RefreshScanStatus() end
    if sync then F.RefreshSyncPanel() end
    if profit then F.SyncRefreshProfit(); F.RefreshProfit() end
    if summary then
        F.summaryText:SetText(F.Summary())
        F.summaryPage:SetHeight(math.max(380,F.summaryText:GetStringHeight()+20)); F.summaryScroll:SetVerticalScroll(0)
    end
    local value
    if F.mode=="export" then F.Flush() end
    local pages=math.max(1,math.ceil(#F.db.events/50))
    F.page=math.min(F.page,pages)
    if F.mode=="export" then
        value=F.Export((F.page-1)*50+1,50)
        F.footer:SetText("JSON page "..F.page.." / "..pages..". Ctrl+A, Ctrl+C; save as UTF-8 .json. Prefer SavedVariables for full imports.")
    elseif F.mode=="journal" then
        value=F.Journal(F.page)
        F.footer:SetText("Records page "..F.page.." / "..pages..", newest first.")
    else
        F.footer:SetText("/reload saves all records. Import ForeverLedger.lua from BOTH accounts into the same SQLite database.")
    end
    if records then F.edit:SetText(value); F.edit:SetCursorPosition(0); F.scroll:SetVerticalScroll(0) end
    F.window:Show()
    if F.mode=="export" then F.edit:SetFocus(); F.edit:HighlightText() else F.edit:ClearFocus() end
end

function F.RefreshScanStatus()
    if F.scanStatus then F.scanStatus:SetText(F.priceStatus or "Open the AH to refresh tracked item prices. Scans never buy or list items.") end
end

function F.SetMarker(text)
    local name=(text or ""):match("^%s*(.-)%s*$")
    if name=="" then return false end
    F.Flush(); F.db.episode=name; F.Emit("episode_start",{name=name}); F.RecordValue(true)
    F.Print("Marker: "..name); return true
end

function F.PopupEditBox(dialog) return dialog.GetEditBox and dialog:GetEditBox() or dialog.editBox or dialog.EditBox end

function F.PromptMarker(force)
    if not force and F.db.episode and F.db.episode:match("%S") then return false end
    if not StaticPopupDialogs or not StaticPopup_Show then F.Print("Set a recording marker with /fl episode <name>."); return false end
    local edit=F.PopupEditBox
    StaticPopupDialogs.FOREVERLEDGER_MARKER={
        text="Set a recording marker? Enter an episode name to group the gold and item records that follow.",
        button1="Set marker",button2="Not now",hasEditBox=true,maxLetters=100,
        timeout=0,whileDead=true,hideOnEscape=true,preferredIndex=3,
        OnShow=function(dialog) local box=edit(dialog); box:SetText(F.db.episode or ""); box:SetFocus() end,
        OnAccept=function(dialog) if not F.SetMarker(edit(dialog):GetText()) then F.Print("No marker set. Recording continues.") end end,
        EditBoxOnEnterPressed=function(box) if F.SetMarker(box:GetText()) then StaticPopup_Hide("FOREVERLEDGER_MARKER") end end,
    }
    StaticPopup_Show("FOREVERLEDGER_MARKER"); return true
end

function F.Print(text) print("|cffd7b56dForever Ledger:|r "..text) end
function F.Command(input)
    local command,rest=(input or ""):match("^(%S*)%s*(.-)%s*$")
    command=command:lower()
    if command=="account" and rest~="" then
        F.db.accountLabel=rest; F.Emit("account_label",{label=rest}); F.Print("Account label: "..rest)
    elseif command=="own" and rest~="" then
        local name=F.FullName(rest); F.db.owners[name]=true; F.Emit("owner",{name=name}); F.Print("Owned character: "..name)
    elseif (command=="episode" or command=="marker") and rest~="" then F.SetMarker(rest)
    elseif command=="highlight" or command=="hl" then F.HighlightCommand(rest)
    elseif command=="end" then F.Flush(); F.Emit("episode_end",{}); F.db.episode=nil
    elseif command=="export" then F.Show("export",tonumber(rest) or 1)
    elseif command=="journal" then F.Show("journal")
    elseif command=="scan" then F.ScanBags(true); F.ScanEquipment(); F.ScanBank(); F.ScanMail(); F.ScanAuctions(); F.RecordValue(); F.Show()
    elseif command=="prices" then
        if rest=="stop" then F.StopPrices("Stopped") elseif rest=="all" or rest=="oldest" then F.StartPrices(rest)
        else F.Print("Use /fl prices all, /fl prices oldest or /fl prices stop.") end
    elseif command=="sync" then F.SyncCommand(rest)
    elseif command=="profit" then F.Show("profit")
    elseif command=="fee" then
        local percent=tonumber(rest)
        if percent and percent>=0 and percent<=100 then
            F.db.settings.commissionBps=math.floor(percent*100); F.Emit("valuation_settings",{commissionBps=F.db.settings.commissionBps})
            F.historyDirty=true; F.RecordValue(); F.Print("Valuation commission: "..percent.."%")
        else F.Print("Use /fl fee <percent>, for example /fl fee 5.") end
    else F.Show() end
end
