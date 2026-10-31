local _, F = ...
local function money(n)
    n=n or 0
    local sign=n<0 and "-" or ""
    n=math.abs(n)
    return string.format("%s%dg %02ds %02dc",sign,math.floor(n/10000),math.floor(n/100)%100,n%100)
end
F.Money=money

function F.Summary()
    local lines={"FOREVER LEDGER  "..F.VERSION, "Account: "..(F.db.accountLabel or "unlabelled"),
        "Episode: "..(F.db.episode or "none"),"", "Recorded characters (last observed balances):"}
    local total=0
    for _, c in pairs(F.db.characters) do
        total=total+(c.balance or 0)
        lines[#lines+1]=(c.name or "?").."  "..money(c.balance)
    end
    lines[#lines+1]="Account total: "..money(total)
    local observed,residual,gaps=0,0,0
    for _, e in ipairs(F.db.events) do
        if e.kind=="balance" then observed=observed+e.data.delta end
        if e.kind=="reconciliation" and e.data.residual~=0 then residual=residual+1 end
        if e.kind=="baseline" and e.data.gap~=0 then gaps=gaps+1 end
    end
    lines[#lines+1]="Observed net gold change: "..money(observed)
    lines[#lines+1]="Unresolved reconciliation windows: "..residual.." | Login gaps: "..gaps
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
    lines[#lines+1]="Total value = gold + other assets + equipped salvage. Estimates are not income."
    lines[#lines+1]="Bank/mail/AH and offline alts are last observed; stale snapshots may overlap."
    lines[#lines+1]="DE is expected net material value, available for bound gear only to its enchanter owner."
    lines[#lines+1]="AH commission assumption: "..(F.db.settings.commissionBps/100).."% (/fl fee 5 or /fl fee 15)."
    if F.isTBC then lines[#lines+1]="TBC preview: Outland DE tables and exact posting-to-return matching are not covered." end
    lines[#lines+1]="Database reporting combines both accounts; this window shows this account only."
    lines[#lines+1]=""
    lines[#lines+1]="Commands: /fl account Main | /fl own Name-Realm | /fl episode Episode 1"
    lines[#lines+1]="/fl end | /fl scan | /fl prices all | /fl prices oldest | /fl prices stop"
    return table.concat(lines,"\n")
end

function F.Journal()
    local lines={"Recent records (amounts are copper in the export):",""}
    for i=#F.db.events,math.max(1,#F.db.events-49),-1 do
        local e=F.db.events[i]
        lines[#lines+1]=e.sequence.."  "..e.kind.."  "..e.characterName.."  "..F.JSON(e.data)
    end
    return table.concat(lines,"\n")
end

function F.Show(mode,page)
    if not F.db then return end
    if not F.window then
        local w=CreateFrame("Frame","ForeverLedgerWindow",UIParent,"BasicFrameTemplateWithInset")
        w:SetSize(920,760); w:SetPoint("CENTER"); w:SetMovable(true); w:EnableMouse(true)
        w:SetClampedToScreen(true)
        if GetScreenWidth and GetScreenHeight then w:SetScale(math.min(1,(GetScreenWidth()-40)/920,(GetScreenHeight()-40)/760)) end
        w:RegisterForDrag("LeftButton")
        w:SetScript("OnDragStart",w.StartMoving); w:SetScript("OnDragStop",w.StopMovingOrSizing)
        w.TitleText:SetText("Forever Ledger")
        local scroll=CreateFrame("ScrollFrame",nil,w,"UIPanelScrollFrameTemplate")
        scroll:SetPoint("TOPLEFT",16,-70); scroll:SetPoint("BOTTOMRIGHT",-35,45)
        local edit=CreateFrame("EditBox",nil,scroll)
        edit:SetMultiLine(true); edit:SetAutoFocus(false); edit:SetFontObject(ChatFontNormal)
        edit:SetWidth(855); edit:SetMaxLetters(0)
        edit:SetScript("OnEscapePressed",function(self) self:ClearFocus(); w:Hide() end)
        edit:SetScript("OnTextChanged",function(self)
            local _,size=self:GetFont()
            self:SetHeight(math.max(430,(self:GetNumLines() or 1)*((size or 12)+3)+20))
        end)
        scroll:SetScrollChild(edit)
        local footer=w:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall")
        footer:SetPoint("BOTTOMLEFT",16,17); footer:SetWidth(875); footer:SetJustifyH("LEFT")
        local function button(label,x,action)
            local b=CreateFrame("Button",nil,w,"UIPanelButtonTemplate")
            b:SetSize(115,24); b:SetPoint("TOPLEFT",x,-35); b:SetText(label); b:SetScript("OnClick",action)
        end
        button("Summary",16,function() F.Show("summary") end)
        button("Recent records",139,function() F.Show("journal") end)
        button("Export JSON",262,function() F.Show("export",1) end)
        button("Previous",385,function() F.Show("export",math.max(1,(F.page or 1)-1)) end)
        button("Next",508,function() F.Show("export",(F.page or 1)+1) end)
        button("Refresh bags",631,function() F.ScanBags(true); F.ScanEquipment(); F.ScanBank(); F.ScanMail(); F.ScanAuctions(); F.RecordValue(); F.Show("summary") end)
        button("Set marker",754,function() F.PromptMarker(true) end)
        F.window,F.edit,F.footer,F.scroll=w,edit,footer,scroll
        F.BuildChart(w)
        local scans=CreateFrame("Frame",nil,w); scans:SetPoint("TOPLEFT",16,-420); scans:SetSize(888,52)
        for i,def in ipairs({{"Scan all prices","all",140},{"Oldest 50 + unpriced","oldest",185},{"Stop scan","stop",100}}) do
            local b=CreateFrame("Button",nil,scans,"UIPanelButtonTemplate")
            b:SetSize(def[3],24); b:SetPoint("TOPLEFT",i==1 and 0 or i==2 and 148 or 341,0); b:SetText(def[1])
            local mode=def[2]
            b:SetScript("OnClick",function() if mode=="stop" then F.StopPrices("Stopped") else F.StartPrices(mode) end; F.RefreshScanStatus() end)
        end
        local status=scans:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall")
        status:SetPoint("TOPLEFT",0,-30); status:SetWidth(880); status:SetJustifyH("LEFT")
        F.scanControls,F.scanStatus=scans,status
        UISpecialFrames[#UISpecialFrames+1]="ForeverLedgerWindow"
    end
    F.mode,F.page=mode or "summary",page or 1
    local summary=F.mode=="summary"
    F.chart:SetShown(summary); F.scanControls:SetShown(summary)
    F.scroll:ClearAllPoints(); F.scroll:SetPoint("TOPLEFT",16,summary and -480 or -70); F.scroll:SetPoint("BOTTOMRIGHT",-35,45)
    if summary then F.RefreshChart(); F.RefreshScanStatus() end
    local value
    if F.mode=="export" then
        F.Flush()
        F.page=math.min(F.page,math.max(1,math.ceil(#F.db.events/50)))
        value=F.Export((F.page-1)*50+1,50)
        F.footer:SetText("JSON page "..F.page.." / "..math.ceil(#F.db.events/50)..". Ctrl+A, Ctrl+C; save as UTF-8 .json. Prefer SavedVariables for full imports.")
    else
        value=F.mode=="journal" and F.Journal() or F.Summary()
        F.footer:SetText("/reload saves all records. Import ForeverLedger.lua from BOTH accounts into the same SQLite database.")
    end
    F.edit:SetText(value); F.edit:SetCursorPosition(0); F.scroll:SetVerticalScroll(0)
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

function F.PromptMarker(force)
    if not force and F.db.episode and F.db.episode:match("%S") then return false end
    if not StaticPopupDialogs or not StaticPopup_Show then F.Print("Set a recording marker with /fl episode <name>."); return false end
    local function edit(dialog) return dialog.GetEditBox and dialog:GetEditBox() or dialog.editBox or dialog.EditBox end
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
    elseif command=="end" then F.Flush(); F.Emit("episode_end",{}); F.db.episode=nil
    elseif command=="export" then F.Show("export",tonumber(rest) or 1)
    elseif command=="journal" then F.Show("journal")
    elseif command=="scan" then F.ScanBags(true); F.ScanEquipment(); F.ScanBank(); F.ScanMail(); F.ScanAuctions(); F.RecordValue(); F.Show()
    elseif command=="prices" then
        if rest=="stop" then F.StopPrices("Stopped") elseif rest=="all" or rest=="oldest" then F.StartPrices(rest)
        else F.Print("Use /fl prices all, /fl prices oldest or /fl prices stop.") end
    elseif command=="fee" then
        local percent=tonumber(rest)
        if percent and percent>=0 and percent<=100 then
            F.db.settings.commissionBps=math.floor(percent*100); F.Emit("valuation_settings",{commissionBps=F.db.settings.commissionBps})
            F.historyDirty=true; F.RecordValue(); F.Print("Valuation commission: "..percent.."%")
        else F.Print("Use /fl fee <percent>, for example /fl fee 5.") end
    else F.Show() end
end
