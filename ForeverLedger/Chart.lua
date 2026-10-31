local _,F=...
local colors={gold={0.84,0.71,0.43},assets={0.40,0.72,0.87},equipped={0.72,0.60,0.87}}
local names={gold="Gold",assets="Other assets",equipped="Equipped salvage"}
local function label(parent,text,x,y,font)
    local t=parent:CreateFontString(nil,"OVERLAY",font or "GameFontHighlightSmall")
    t:SetPoint("TOPLEFT",x,y); t:SetText(text); return t
end

function F.BuildChart(parent)
    F.db.settings.chart=F.db.settings.chart or {gold=true,assets=true,equipped=true}
    local c=CreateFrame("Frame",nil,parent); c:SetPoint("TOPLEFT",16,-65); c:SetSize(888,350)
    c.lines={}; c.checks={}; F.chart=c
    local function preset(text,x,selection)
        local b=CreateFrame("Button",nil,c,"UIPanelButtonTemplate")
        b:SetSize(120,24); b:SetPoint("TOPLEFT",x,0); b:SetText(text)
        b:SetScript("OnClick",function() F.db.settings.chart=F.Copy(selection); F.RefreshChart() end)
    end
    preset("Gold only",0,{gold=true}); preset("Total value",128,{gold=true,assets=true,equipped=true})
    preset("Equipped gear",256,{equipped=true})
    local x=400
    for _,key in ipairs({"gold","assets","equipped"}) do
        local b=CreateFrame("CheckButton",nil,c,"UICheckButtonTemplate")
        b:SetSize(24,24); b:SetPoint("TOPLEFT",x,0)
        local text=label(b,names[key],26,-5); text:SetTextColor(unpack(colors[key]))
        b:SetScript("OnClick",function(self) F.db.settings.chart[key]=self:GetChecked() and true or nil; F.RefreshChart() end)
        c.checks[key]=b; x=x+(key=="gold" and 90 or 145)
    end
    local plot=CreateFrame("Frame",nil,c); plot:SetPoint("TOPLEFT",74,-42); plot:SetSize(790,230)
    c.plot=plot
    local bg=plot:CreateTexture(nil,"BACKGROUND"); bg:SetAllPoints(); bg:SetColorTexture(0.14,0.14,0.14,0.95)
    c.axis={}
    for i=0,4 do
        local grid=plot:CreateTexture(nil,"BACKGROUND")
        grid:SetColorTexture(0.6,0.6,0.6,0.16); grid:SetPoint("BOTTOMLEFT",0,i*57.5); grid:SetSize(790,1)
        c.axis[i]=label(c,"",0,-42-230+i*57.5+5); c.axis[i]:SetWidth(68); c.axis[i]:SetJustifyH("RIGHT")
    end
    c.empty=label(plot,"History begins with your first observation. Earn or spend gold to add points.",16,-100)
    c.startTime=label(c,"",74,-280); c.endTime=label(c,"",650,-280)
    c.note=label(c,"",0,-305); c.note:SetWidth(880); c.note:SetJustifyH("LEFT")
    c.hover=label(c,"",0,-326); c.hover:SetWidth(880); c.hover:SetJustifyH("LEFT")
    plot:EnableMouse(true)
    plot:SetScript("OnLeave",function() c.hover:SetText("") end)
    plot:SetScript("OnUpdate",function(self)
        if not self:IsMouseOver() or not c.points or #c.points==0 then return end
        local cursor=GetCursorPosition()/self:GetEffectiveScale()-self:GetLeft()
        local t=c.first+math.max(0,math.min(1,cursor/790))*c.span
        local closest=c.points[1]
        for _,p in ipairs(c.points) do if math.abs(p.time-t)<math.abs(closest.time-t) then closest=p end end
        local h=closest.raw
        c.hover:SetText(date("%d %b %H:%M:%S",h.time).."   Gold "..F.Money(h.gold).."   Assets "..F.Money(h.assets).."   Gear "..F.Money(h.equipped))
    end)
end

function F.RefreshChart()
    local c=F.chart
    if not c then return end
    local selected=F.db.settings.chart
    for key,b in pairs(c.checks) do b:SetChecked(selected[key]) end
    local history={}
    for i=#F.db.history,1,-1 do
        local h=F.db.history[i]
        if h.scope==F.marketScope then table.insert(history,1,h); if #history==300 then break end end
    end
    local points,maximum=F.StackHistory(history,selected,F.marketScope)
    c.points=points
    for _,line in ipairs(c.lines) do line:Hide() end
    for i=0,4 do c.axis[i]:SetText(string.format("%.1fg",maximum*i/40000)) end
    local n=0
    if #points>0 then
        local first,last=points[1].time,points[#points].time
        local span=math.max(1,last-first); c.first,c.span=first,span
        for i=2,#points do
            local a,b=points[i-1],points[i]
            for j,v in ipairs(b.values) do
                n=n+1
                local line=c.lines[n] or c.plot:CreateLine(nil,"ARTWORK"); c.lines[n]=line
                line:SetColorTexture(unpack(colors[v.key])); line:SetThickness(2)
                line:SetStartPoint("BOTTOMLEFT",c.plot,(a.time-first)/span*790,a.values[j].value/maximum*230)
                line:SetEndPoint("BOTTOMLEFT",c.plot,(b.time-first)/span*790,v.value/maximum*230)
                line:Show()
            end
        end
        c.startTime:SetText(date("%d %b %H:%M",first)); c.endTime:SetText(date("%d %b %H:%M",last))
        local h=points[#points].raw
        c.note:SetText("Latest 300 observations | Stacked components | This account / realm / faction | "..(h.unpricedRows or 0).." partly valued rows")
    end
    c.empty:SetShown(#points<2 or not next(selected))
end
