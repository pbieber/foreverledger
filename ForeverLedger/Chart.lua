local _,F=...
-- Validated against the #242424 plot for colorblind separation.
local colors={gold={0.165,0.663,0.408},assets={0.290,0.608,0.847},equipped={0.561,0.373,0.863}}
local names={gold="Gold",assets="Other assets",equipped="Equipped Gear",other="Other"}
local TYPES={"gold","assets","equipped"}
local SHORT_NAMES={gold="Gold",assets="Assets",equipped="Gear"}
local BREAKDOWNS={{"type","Type"},{"category","Category"},{"character","Character"}}
-- Categories and characters, validated against the same plot. Gold keeps its own slot.
local BAND_COLORS={{0.224,0.529,0.898},{0.851,0.349,0.149},colors.gold,{0.788,0.522,0},
    {0.835,0.318,0.506},{0.565,0.522,0.914},{0.902,0.404,0.404}}
local GOLD_SLOT=3
local OTHER_COLOR={0.5,0.5,0.5}
-- 2px per segment.
local STEPS=275
local NEUTRAL="|cffc8c8c8"
-- The top axis label reaches 5px above the plot, so the plot starts clear of the controls.
local CONTROLS_TOP,CONTROLS_HEIGHT=-44,24
local PLOT_TOP,PLOT_LEFT,PLOT_WIDTH,PLOT_HEIGHT=-76,56,550,266
-- Highlights get their own strip under the plot, on the same time axis, so they never
-- sit on the gold. Ticks closer than HIGHLIGHT_GROUP pixels share one tooltip.
local TIMELINE_TOP,TIMELINE_HEIGHT=PLOT_TOP-PLOT_HEIGHT-3,12
local HIGHLIGHT_COLOR={0.91,0.88,0.81}
local HIGHLIGHT_GROUP,HIGHLIGHT_ROWS=6,5
local STAT_HEIGHT,STAT_WIDTH,STAT_VALUE_X=14,170,78
local LEGEND_LEFT,LEGEND_COLUMN,LEGEND_ROWS=174,88,3
local HEADROOM=1.05
local MAX_GRID_STEPS=15
local SMOOTHING=6
local LINE_ART="Interface/AddOns/ForeverLedger/Media/line-soft"
local SOLID_ART="Interface/Buttons/WHITE8X8"
-- The art feathers to nothing at its edges, leaving a line about 2px wide.
local LINE_HALF_WIDTH=2
-- Keeps sharp peaks from folding the line over itself.
local MITER_LIMIT=1.4
local SIMPLIFY_TOLERANCE=0.05
local TOOLTIP_ROWS=10
local function label(parent,text,x,y,font)
    local t=parent:CreateFontString(nil,"OVERLAY",font or "GameFontHighlightSmall")
    t:SetPoint("TOPLEFT",x,y); t:SetText(text); return t
end

local function bandName(key)
    if names[key] then return names[key] end
    local c=F.CharacterInfo(key)
    return c and (c.name or key):match("^[^-]+") or key
end

local function colorCode(c)
    if not c then return "|cffffffff" end
    return string.format("|cff%02x%02x%02x",math.floor(c.r*255),math.floor(c.g*255),math.floor(c.b*255))
end

local function characterName(guid)
    local c=F.CharacterInfo(guid) or {}
    return colorCode(RAID_CLASS_COLORS and RAID_CLASS_COLORS[c.class])..(c.name or guid):match("^[^-]+").."|r"
end

-- Line color: the series color lightened, so edges show against the solid fill.
local function edge(color)
    return color[1]+(1-color[1])*0.4,color[2]+(1-color[2])*0.4,color[3]+(1-color[3])*0.4
end

local function gainText(gain,format)
    format=format or F.MoneyShort
    if gain>0 then return "|cff3fd07f+"..format(gain).."|r" end
    if gain<0 then return "|cffff5a5a"..format(gain).."|r" end
    return format(0)
end
F.GainText=gainText

function F.ChartCharacterList()
    local list={}
    for guid,c in pairs(F.db.characters) do
        if F.SameChart(c.marketScope,F.marketScope) then list[#list+1]={guid=guid,name=c.name or guid} end
    end
    for _,entry in ipairs(F.SyncedCharacters(F.marketScope)) do list[#list+1]=entry end
    table.sort(list,function(a,b) if a.name==b.name then return a.guid<b.guid end; return a.name<b.name end)
    return list
end

-- settings.chartCharacters: nil for all, "this" for whoever is logged in, or a set.
function F.SelectedCharacters()
    local choice=F.db.settings.chartCharacters
    local set={}
    for _,entry in ipairs(F.ChartCharacterList()) do
        if choice==nil or (choice=="this" and entry.guid==F.identity.guid)
            or (type(choice)=="table" and choice[entry.guid]) then set[entry.guid]=true end
    end
    return set
end

function F.ToggleChartCharacter(guid)
    local set=F.SelectedCharacters()
    set[guid]=not set[guid] or nil
    F.db.settings.chartCharacters=set
end

-- Tooltip rows for one series at one chart point: each selected character's gold,
-- or the ten most valuable items across the selected characters.
function F.BreakdownRows(point,key,characters)
    local rows={}
    local h=point.raw
    local market=F.db.markets and F.db.markets[h.scope]
    for guid in pairs(characters) do
        if key=="gold" then
            local values=h.chars and h.chars[guid]
            if values then rows[#rows+1]={label=characterName(guid),value=values.gold or 0} end
        else
            for _,e in ipairs(F.TopAt(guid,point.time,key)) do
                local item=market and market.catalog[e.key] or {}
                local name=e.key=="mail" and "Gold in mail" or e.name or item.name or e.key
                local amount=e.quantity and NEUTRAL..e.quantity.."x|r " or ""
                local quality=ITEM_QUALITY_COLORS and ITEM_QUALITY_COLORS[e.quality or item.quality]
                rows[#rows+1]={label=amount..colorCode(quality)..name.."|r "..characterName(guid),value=e.value}
            end
        end
    end
    table.sort(rows,function(a,b) if a.value==b.value then return a.label<b.label end; return a.value>b.value end)
    if key~="gold" then for i=#rows,11,-1 do rows[i]=nil end end
    return rows
end

local function showBreakdown(owner,point,key,characters)
    GameTooltip:SetOwner(owner,"ANCHOR_CURSOR")
    GameTooltip:AddDoubleLine(names[key]..(key=="gold" and "" or " (top 10)"),F.Money(point.totals[key]),1,1,1,1,1,1)
    local rows=F.BreakdownRows(point,key,characters)
    for _,r in ipairs(rows) do GameTooltip:AddDoubleLine(r.label,F.Money(r.value),1,1,1,1,1,1) end
    if #rows==0 then GameTooltip:AddLine("No breakdown recorded for this point.",0.7,0.7,0.7) end
    GameTooltip:Show()
end

-- Total value of one chart point by series, then by selected character.
function F.ValueRows(point,characters)
    local series,people={},{}
    for _,key in ipairs({"gold","assets","equipped"}) do
        series[#series+1]={label=names[key],value=point.totals[key]}
    end
    for guid in pairs(characters) do
        local v=point.raw.chars and point.raw.chars[guid]
        if v then
            people[#people+1]={label=characterName(guid),value=(v.gold or 0)+(v.assets or 0)+(v.equipped or 0)}
        end
    end
    table.sort(people,function(a,b) if a.value==b.value then return a.label<b.label end; return a.value>b.value end)
    return series,people
end

local function addRows(rows)
    for _,r in ipairs(rows) do GameTooltip:AddDoubleLine(r.label,F.Money(r.value),1,1,1,1,1,1) end
end

-- Tooltip rows for one band under a category or character breakdown: a character's
-- types, a category's characters, or what folded into Other.
function F.BandRows(point,key,characters,selected,breakdown)
    local rows={}
    local h=point.raw
    if key==F.OTHER_BAND then
        local sums={}
        for guid in pairs(characters) do
            for band,value in pairs(F.CharacterBands(h,guid,selected,breakdown)) do
                if band==key or point.other[band] then sums[band]=(sums[band] or 0)+value end
            end
        end
        for band,value in pairs(sums) do
            local name=band==key and "Not categorised" or breakdown=="character" and characterName(band) or bandName(band)
            rows[#rows+1]={label=name,value=value}
        end
    elseif breakdown=="character" then
        local bands=h.chars[key] or {}
        for _,kind in ipairs(TYPES) do
            if selected[kind] and (bands[kind] or 0)~=0 then rows[#rows+1]={label=names[kind],value=bands[kind]} end
        end
    else
        for guid in pairs(characters) do
            local value=F.CharacterBands(h,guid,selected,breakdown)[key]
            if value then rows[#rows+1]={label=characterName(guid),value=value} end
        end
    end
    table.sort(rows,function(a,b) if a.value==b.value then return a.label<b.label end; return a.value>b.value end)
    return rows
end

local function showBand(owner,point,key,c)
    if c.breakdown=="type" then return showBreakdown(owner,point,key,c.characters) end
    local rows=F.BandRows(point,key,c.characters,c.selected,c.breakdown)
    local total=0
    for _,r in ipairs(rows) do total=total+r.value end
    GameTooltip:SetOwner(owner,"ANCHOR_CURSOR")
    GameTooltip:AddDoubleLine(bandName(key),F.Money(total),1,1,1,1,1,1)
    for i=1,math.min(#rows,TOOLTIP_ROWS) do GameTooltip:AddDoubleLine(rows[i].label,F.Money(rows[i].value),1,1,1,1,1,1) end
    if #rows>TOOLTIP_ROWS then GameTooltip:AddLine((#rows-TOOLTIP_ROWS).." more",0.7,0.7,0.7) end
    GameTooltip:Show()
end

local function showValue(owner,point,characters)
    GameTooltip:SetOwner(owner,"ANCHOR_CURSOR")
    GameTooltip:AddDoubleLine("Total Value",F.Money(point.totals.total),1,1,1,1,1,1)
    local series,people=F.ValueRows(point,characters)
    addRows(series)
    if #people>1 then GameTooltip:AddLine(" "); addRows(people) end
    local partly=point.raw.unpricedRows or 0
    if partly>0 then GameTooltip:AddLine(partly.." partly valued rows",0.7,0.7,0.7) end
    GameTooltip:Show()
end

local function showGain(owner,characters)
    local gain,rows,start=F.GainBreakdown(characters,F.Now())
    GameTooltip:SetOwner(owner,"ANCHOR_CURSOR")
    GameTooltip:AddDoubleLine("Gain today",gainText(gain,F.Money),1,1,1,1,1,1)
    GameTooltip:AddLine("Since "..date("%d %b %H:%M",start),0.7,0.7,0.7)
    for _,r in ipairs(rows) do GameTooltip:AddDoubleLine(r.label,gainText(r.value,F.Money),1,1,1,1,1,1) end
    if #rows==0 then GameTooltip:AddLine("No gold changes recorded yet.",0.7,0.7,0.7) end
    GameTooltip:Show()
end

local function showOnSale(owner,characters)
    local sale=F.OnSale(characters)
    GameTooltip:SetOwner(owner,"ANCHOR_CURSOR")
    GameTooltip:AddDoubleLine("Total on sale",F.Money(sale.total),1,1,1,1,1,1)
    GameTooltip:AddLine(sale.count..(sale.count==1 and " listing" or " listings")..", as last seen at the auction house.",0.7,0.7,0.7)
    GameTooltip:Show()
end

local function showListingCost(owner,characters)
    local sale=F.OnSale(characters)
    GameTooltip:SetOwner(owner,"ANCHOR_CURSOR")
    GameTooltip:AddDoubleLine("Cost to list",F.Money(sale.deposit),1,1,1,1,1,1)
    GameTooltip:AddDoubleLine("Auction house cut if all sell",F.Money(sale.cut),1,1,1,1,1,1)
    GameTooltip:AddLine("A sale returns its deposit. An expired or cancelled auction keeps it.",0.7,0.7,0.7)
    if sale.estimated>0 then
        GameTooltip:AddLine(sale.estimated.." estimated from vendor price at the 48 hour rate.",0.7,0.7,0.7)
    end
    GameTooltip:Show()
end

local function buildStats(c)
    c.stats={}
    local function latest() return c.points and c.points[#c.points] end
    local function stat(key,name,row,show,right)
        local s=CreateFrame("Frame",nil,c); s:SetPoint(right and "TOPRIGHT" or "TOPLEFT",0,-(row-1)*STAT_HEIGHT); s:SetSize(STAT_WIDTH,STAT_HEIGHT)
        label(s,"|cffa8a8a8"..name.."|r",0,-1,"GameFontHighlight")
        s.value=label(s,"",STAT_VALUE_X,-1,"GameFontHighlight")
        if right then s.value:SetWidth(STAT_WIDTH-STAT_VALUE_X); s.value:SetJustifyH("RIGHT") end
        s:EnableMouse(true)
        s:SetScript("OnEnter",show)
        s:SetScript("OnLeave",function(self) if GameTooltip:IsOwned(self) then GameTooltip:Hide() end end)
        c.stats[key]=s
    end
    stat("value","Total Value",1,function(self) if latest() then showValue(self,latest(),c.characters) end end)
    stat("gold","Total Gold",2,function(self) if latest() then showBreakdown(self,latest(),"gold",c.characters) end end)
    stat("gain","Gain today",3,function(self) showGain(self,c.characters) end)
    stat("sale","Total on sale",1,function(self) showOnSale(self,c.characters) end,true)
    stat("listing","Cost to list",2,function(self) showListingCost(self,c.characters) end,true)
end

-- The list that opens under a dropdown button. One open list closes the other.
local function buildPanel(c,button,width)
    local panel=CreateFrame("Frame",nil,c)
    panel:SetFrameStrata("DIALOG"); panel:SetPoint("TOPLEFT",button,"BOTTOMLEFT",0,-2); panel:SetSize(width,30)
    panel:EnableMouse(true); panel.rows={}
    local bg=panel:CreateTexture(nil,"BACKGROUND"); bg:SetAllPoints(); bg:SetColorTexture(0.06,0.06,0.06,0.97)
    panel:Hide()
    c.panels[#c.panels+1]=panel
    button:SetScript("OnClick",function()
        local open=panel:IsShown()
        for _,other in ipairs(c.panels) do other:Hide() end
        panel:SetShown(not open)
    end)
    return panel
end

local function panelRow(panel,i,onClick)
    local row=CreateFrame("CheckButton",nil,panel,"UICheckButtonTemplate")
    row:SetSize(22,22); row:SetPoint("TOPLEFT",6,-4-(i-1)*22)
    row.name=label(row,"",26,-5)
    row:SetScript("OnClick",onClick)
    panel.rows[i]=row
    panel:SetHeight(i*22+8)
    return row
end

local function refreshCharacterPanel(c,set)
    local panel=c.characterPanel
    local list=F.ChartCharacterList()
    for i,entry in ipairs(list) do
        local row=panel.rows[i] or panelRow(panel,i,function(self) F.ToggleChartCharacter(self.guid); F.RefreshChart() end)
        row.guid=entry.guid; row.name:SetText(characterName(entry.guid)..(entry.account and NEUTRAL.."  "..entry.account.."|r" or "")); row:SetChecked(set[entry.guid]==true)
    end
    panel:SetHeight(#list*22+8)
    local count=0
    for _ in pairs(set) do count=count+1 end
    c.selector:SetText("Characters: "..count.."/"..#list)
end

local function metricText(selected)
    local parts={}
    for _,key in ipairs(TYPES) do
        if selected[key] then parts[#parts+1]=key end
    end
    if #parts==3 then return "All value" end
    if #parts==0 then return "Nothing" end
    if #parts==1 then return names[parts[1]] end
    return SHORT_NAMES[parts[1]].." + "..SHORT_NAMES[parts[2]]
end

local function buildMetricControl(c,x,width)
    local b=CreateFrame("Button",nil,c,"UIPanelButtonTemplate")
    b:SetSize(width,CONTROLS_HEIGHT); b:SetPoint("TOPLEFT",x,CONTROLS_TOP); c.metric=b
    local arrow=b:CreateTexture(nil,"ARTWORK"); arrow:SetTexture("Interface/Buttons/Arrow-Down-Up")
    arrow:SetSize(12,12); arrow:SetPoint("RIGHT",b,"RIGHT",-2,-2)
    local panel=buildPanel(c,b,130)
    for i,key in ipairs(TYPES) do
        local row=panelRow(panel,i,function(self) F.db.settings.chart[key]=self:GetChecked() and true or nil; F.RefreshChart() end)
        row.name:SetText(names[key])
        c.checks[key]=row
    end
end

local function buildSwitch(c,x,width)
    c.switch={}
    for i,entry in ipairs(BREAKDOWNS) do
        local b=CreateFrame("Button",nil,c,"UIPanelButtonTemplate")
        b:SetSize(width,CONTROLS_HEIGHT); b:SetPoint("TOPLEFT",x+(i-1)*width,CONTROLS_TOP); b:SetText(entry[2])
        b:SetScript("OnClick",function() F.db.settings.chartBreakdown=entry[1]; F.RefreshChart() end)
        c.switch[entry[1]]=b
    end
end

-- Reads like the stack: the top band first.
local function refreshLegend(c,bands,bandColor)
    for _,entry in ipairs(c.legend) do entry.swatch:Hide(); entry.name:Hide() end
    if #bands<2 then return end
    for i=1,#bands do
        local entry=c.legend[i]
        if not entry then
            local column,row=math.floor((i-1)/LEGEND_ROWS),(i-1)%LEGEND_ROWS
            local x,y=LEGEND_LEFT+column*LEGEND_COLUMN,-row*STAT_HEIGHT
            entry={swatch=c:CreateTexture(nil,"ARTWORK"),name=label(c,"",x+14,y-2)}
            entry.swatch:SetSize(10,10); entry.swatch:SetPoint("TOPLEFT",x,y-2)
            entry.name:SetWidth(LEGEND_COLUMN-16); entry.name:SetJustifyH("LEFT"); entry.name:SetWordWrap(false)
            c.legend[i]=entry
        end
        local key=bands[#bands-i+1].key
        entry.swatch:SetColorTexture(unpack(bandColor[key])); entry.swatch:Show()
        entry.name:SetText(bandName(key)); entry.name:Show()
    end
end

-- A color for each band. Types, gold and Other always have their own. The rest start
-- from a slot their key picks, so a band keeps its color when others come and go.
local function bandColors(bands,breakdown)
    local result,taken={},{[GOLD_SLOT]=breakdown=="category"}
    for _,band in ipairs(bands) do
        local key=band.key
        if colors[key] then result[key]=colors[key]
        elseif key==F.OTHER_BAND then result[key]=OTHER_COLOR
        else
            local hash=0
            for i=1,#key do hash=hash+key:byte(i) end
            local slot=hash%#BAND_COLORS+1
            while taken[slot] do slot=slot%#BAND_COLORS+1 end
            taken[slot]=true
            result[key]=BAND_COLORS[slot]
        end
    end
    return result
end

local function drawMarkers(c,first,span)
    for _,mark in ipairs(c.markers) do mark.line:Hide(); mark.text:Hide() end
    for i,m in ipairs(F.EpisodeMarkers(first,first+span,span*8/PLOT_WIDTH)) do
        local mark=c.markers[i]
        if not mark then
            mark={line=c.plot:CreateTexture(nil,"ARTWORK",nil,1),text=c.plot:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall")}
            mark.line:SetSize(1,PLOT_HEIGHT)
            c.markers[i]=mark
        end
        local x=(m.time-first)/span*PLOT_WIDTH
        local shade=m.start and 0.95 or 0.6
        mark.line:SetColorTexture(shade,shade,shade,0.8)
        mark.line:ClearAllPoints(); mark.line:SetPoint("BOTTOMLEFT",x,0); mark.line:Show()
        -- Alternate heights so neighbouring names stay readable.
        local y=i%2==0 and 16 or 4
        mark.text:ClearAllPoints()
        if x>PLOT_WIDTH-110 then mark.text:SetPoint("BOTTOMRIGHT",c.plot,"BOTTOMLEFT",x-3,y) else mark.text:SetPoint("BOTTOMLEFT",x+3,y) end
        mark.text:SetText(m.start and (m.name or "Episode") or "End"); mark.text:Show()
    end
end

local function showHighlights(owner,group)
    GameTooltip:SetOwner(owner,"ANCHOR_CURSOR")
    for i,h in ipairs(group) do
        if i>HIGHLIGHT_ROWS then GameTooltip:AddLine((#group-HIGHLIGHT_ROWS).." more nearby",0.7,0.7,0.7); break end
        if i>1 then GameTooltip:AddLine(" ") end
        GameTooltip:AddDoubleLine("Highlight "..h.number,date("%a %d %b %H:%M:%S",h.time),1,1,1,1,1,1)
        if h.note then GameTooltip:AddLine(h.note,1,0.82,0,true) end
        if h.since then GameTooltip:AddLine("+"..F.Duration(h.since).." into "..(h.marker or "the marker"),0.7,0.7,0.7) end
        local where=h.zone and (h.subzone and h.zone..", "..h.subzone or h.zone)
        GameTooltip:AddLine(characterName(h.character)..(where and NEUTRAL.."  "..where.."|r" or ""),1,1,1)
    end
    GameTooltip:Show()
end

local function highlightTick(c,i)
    local tick=c.ticks[i]
    if tick then return tick end
    tick=CreateFrame("Frame",nil,c.timeline); tick:SetSize(9,TIMELINE_HEIGHT); tick:EnableMouse(true)
    tick.mark=tick:CreateTexture(nil,"ARTWORK"); tick.mark:SetPoint("CENTER")
    tick.mark:SetColorTexture(unpack(HIGHLIGHT_COLOR))
    -- The plot's guide line shows where the moment falls on the chart above.
    tick:SetScript("OnEnter",function(self)
        showHighlights(self,self.group)
        c.cross:ClearAllPoints(); c.cross:SetPoint("BOTTOMLEFT",self.x,0); c.cross:Show()
    end)
    tick:SetScript("OnLeave",function(self)
        if GameTooltip:IsOwned(self) then GameTooltip:Hide() end
        c.cross:Hide()
    end)
    c.ticks[i]=tick
    return tick
end

-- Highlights of the selected characters inside the chart's time range.
local function drawHighlights(c,first,span,characters)
    for _,tick in ipairs(c.ticks) do tick:Hide() end
    local groups={}
    if span then
        for _,h in ipairs(F.Highlights(first,first+span,characters)) do
            local x=(h.time-first)/span*PLOT_WIDTH
            local group=groups[#groups]
            if group and x-group.x<HIGHLIGHT_GROUP then group[#group+1]=h
            else groups[#groups+1]={h,x=x} end
        end
    end
    for i,group in ipairs(groups) do
        local tick=highlightTick(c,i)
        tick.group,tick.x=group,group.x
        tick.mark:SetSize(#group>1 and 4 or 2,TIMELINE_HEIGHT)
        tick:ClearAllPoints(); tick:SetPoint("BOTTOMLEFT",group.x-4.5,0); tick:Show()
    end
    c.timelineEmpty:SetShown(#groups==0)
    c.highlightGroups=groups
end

-- The top of the value axis and its grid step, in copper. The step is the smallest
-- power of ten in gold that fits the plot, so every label is a round number.
function F.AxisScale(peak)
    local step=10000
    while math.ceil(peak*HEADROOM/step)>MAX_GRID_STEPS do step=step*10 end
    return math.ceil(peak*HEADROOM/step)*step,step
end

local function drawAxis(c,top,step)
    for i,grid in ipairs(c.grid) do grid:Hide(); c.axis[i]:Hide() end
    for i=1,math.floor(top/step+0.5)+1 do
        if not c.grid[i] then
            c.grid[i]=c.plot:CreateTexture(nil,"ARTWORK",nil,-1)
            c.grid[i]:SetColorTexture(0.6,0.6,0.6,0.16); c.grid[i]:SetSize(PLOT_WIDTH,1)
            c.axis[i]=label(c,"",0,0); c.axis[i]:SetWidth(PLOT_LEFT-6); c.axis[i]:SetJustifyH("RIGHT")
        end
        local value=(i-1)*step
        local y=value/top*PLOT_HEIGHT
        c.grid[i]:ClearAllPoints(); c.grid[i]:SetPoint("BOTTOMLEFT",0,y); c.grid[i]:Show()
        c.axis[i]:ClearAllPoints(); c.axis[i]:SetPoint("TOPLEFT",0,PLOT_TOP-PLOT_HEIGHT+y+5)
        c.axis[i]:SetText(string.format("%d",value/10000)..F.GoldIcon); c.axis[i]:Show()
    end
end

-- The curve without points that a straight run already passes through. Flat stretches
-- of history then take one segment instead of hundreds.
function F.SimplifyCurve(curve,tolerance)
    local kept={curve[1]}
    for i=2,#curve-1 do
        local a,b,z=kept[#kept],curve[i],curve[i+1]
        if math.abs(a.y+(z.y-a.y)*(b.x-a.x)/(z.x-a.x)-b.y)>tolerance then kept[#kept+1]=b end
    end
    if #curve>1 then kept[#kept+1]=curve[#curve] end
    return kept
end

-- Both edges of a line of the given half width. Each point's edges lie on the bisector
-- of its two segments, so neighbouring segments share corners and no notch opens where
-- the curve turns. x must always increase.
function F.CurveEdges(curve,half)
    local upper,lower={},{}
    local function normal(a,b)
        local dx,dy=b.x-a.x,b.y-a.y
        local length=math.sqrt(dx*dx+dy*dy)
        return -dy/length,dx/length
    end
    for i,p in ipairs(curve) do
        local ax,ay,bx,by
        if curve[i-1] then ax,ay=normal(curve[i-1],p) end
        if curve[i+1] then bx,by=normal(p,curve[i+1]) end
        ax,ay,bx,by=ax or bx,ay or by,bx or ax,by or ay
        local mx,my=ax+bx,ay+by
        local length=math.sqrt(mx*mx+my*my)
        mx,my=mx/length,my/length
        local reach=half/math.max(mx*ax+my*ay,1/MITER_LIMIT)
        upper[i]={x=p.x+mx*reach,y=p.y+my*reach}
        lower[i]={x=p.x-mx*reach,y=p.y-my*reach}
    end
    return upper,lower
end

-- A pooled texture with its own four corners. It stays off the pixel grid, because
-- snapping would pull neighbouring corners apart.
local function drawQuad(c,pool,index,art,upperLeft,upperRight,lowerLeft,lowerRight)
    local t=pool[index]
    if not t then
        t=c.plot:CreateTexture(nil,"BORDER"); t:SetTexture(art)
        t:SetSnapToPixelGrid(false); t:SetTexelSnappingBias(0)
        pool[index]=t
    end
    local left=math.min(upperLeft.x,lowerLeft.x,upperRight.x,lowerRight.x)
    local right=math.max(upperLeft.x,lowerLeft.x,upperRight.x,lowerRight.x)
    local bottom=math.min(upperLeft.y,lowerLeft.y,upperRight.y,lowerRight.y)
    local top=math.max(upperLeft.y,lowerLeft.y,upperRight.y,lowerRight.y)
    t:ClearAllPoints()
    t:SetPoint("BOTTOMLEFT",c.plot,"BOTTOMLEFT",left,bottom); t:SetPoint("TOPRIGHT",c.plot,"BOTTOMLEFT",right,top)
    t:SetVertexOffset(UPPER_LEFT_VERTEX,upperLeft.x-left,upperLeft.y-top)
    t:SetVertexOffset(UPPER_RIGHT_VERTEX,upperRight.x-right,upperRight.y-top)
    t:SetVertexOffset(LOWER_LEFT_VERTEX,lowerLeft.x-left,lowerLeft.y-bottom)
    t:SetVertexOffset(LOWER_RIGHT_VERTEX,lowerRight.x-right,lowerRight.y-bottom)
    t:Show()
    return t
end

-- One band: the solid area from the baseline up to its curve, then the line on top.
-- Each band paints from the baseline and the lower bands paint over it, so bands meet
-- exactly on the lines.
local function drawBand(c,counts,curve,color,layer)
    for i=2,#curve do
        local a,b=curve[i-1],curve[i]
        if a.y>0 or b.y>0 then
            counts.fills=counts.fills+1
            local fill=drawQuad(c,c.fills,counts.fills,SOLID_ART,a,b,{x=a.x,y=0},{x=b.x,y=0})
            fill:SetDrawLayer("BORDER",layer); fill:SetVertexColor(unpack(color))
        end
    end
    local upper,lower=F.CurveEdges(curve,LINE_HALF_WIDTH)
    local r,g,b=edge(color)
    for i=2,#curve do
        counts.lines=counts.lines+1
        local line=drawQuad(c,c.lines,counts.lines,LINE_ART,upper[i-1],upper[i],lower[i-1],lower[i])
        line:SetDrawLayer("ARTWORK",0); line:SetVertexColor(r,g,b)
    end
end

function F.BuildChart(parent)
    F.db.settings.chart=F.db.settings.chart or {gold=true,assets=true,equipped=true}
    local c=CreateFrame("Frame",nil,parent); c:SetPoint("TOPLEFT",16,-58); c:SetSize(612,390)
    c.lines={}; c.fills={}; c.checks={}; c.markers={}; c.panels={}; c.legend={}; c.ticks={}; F.chart=c
    buildStats(c)
    local function choose(text,x,choice)
        local b=CreateFrame("Button",nil,c,"UIPanelButtonTemplate")
        b:SetSize(94,CONTROLS_HEIGHT); b:SetPoint("TOPLEFT",x,CONTROLS_TOP); b:SetText(text)
        b:SetScript("OnClick",function() F.db.settings.chartCharacters=choice; F.RefreshChart() end)
    end
    choose("This character",0,"this"); choose("All Characters",98,nil)
    local selector=CreateFrame("Button",nil,c,"UIPanelButtonTemplate")
    selector:SetSize(110,CONTROLS_HEIGHT); selector:SetPoint("TOPLEFT",196,CONTROLS_TOP); c.selector=selector
    c.characterPanel=buildPanel(c,selector,240)
    buildMetricControl(c,310,110)
    buildSwitch(c,424,62)
    local plot=CreateFrame("Frame",nil,c); plot:SetPoint("TOPLEFT",PLOT_LEFT,PLOT_TOP); plot:SetSize(PLOT_WIDTH,PLOT_HEIGHT)
    c.plot=plot
    local bg=plot:CreateTexture(nil,"BACKGROUND"); bg:SetAllPoints(); bg:SetColorTexture(0.14,0.14,0.14,0.95)
    c.axis={}; c.grid={}
    c.empty=label(plot,"Nothing to show. Select a series and a character, or earn or spend gold to add points.",16,-PLOT_HEIGHT/2)
    local timeline=CreateFrame("Frame",nil,c); timeline:SetPoint("TOPLEFT",PLOT_LEFT,TIMELINE_TOP); timeline:SetSize(PLOT_WIDTH,TIMELINE_HEIGHT)
    c.timeline=timeline
    local strip=timeline:CreateTexture(nil,"BACKGROUND"); strip:SetAllPoints(); strip:SetColorTexture(0.09,0.09,0.09,0.95)
    c.timelineEmpty=label(timeline,"|cff8c8c8cNo highlights here. Mark one with a key binding, Shift-click on the minimap button or /fl highlight.|r",6,-1)
    local below=TIMELINE_TOP-TIMELINE_HEIGHT
    c.startTime=label(c,"",PLOT_LEFT,below-4); c.endTime=label(c,"",PLOT_LEFT+PLOT_WIDTH-70,below-4)
    c.hover=label(c,"",0,below-18); c.hover:SetWidth(612); c.hover:SetJustifyH("LEFT")
    c.cross=plot:CreateTexture(nil,"OVERLAY"); c.cross:SetColorTexture(1,1,1,0.6); c.cross:SetSize(1,PLOT_HEIGHT)
    c.total=plot:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall"); c.total:SetDrawLayer("OVERLAY",2)
    c.totalBack=plot:CreateTexture(nil,"OVERLAY",nil,1); c.totalBack:SetColorTexture(0,0,0,0.75)
    c.totalBack:SetPoint("TOPLEFT",c.total,-3,3); c.totalBack:SetPoint("BOTTOMRIGHT",c.total,3,-3)
    local function clearHover()
        c.hover:SetText(""); c.cross:Hide(); c.total:Hide(); c.totalBack:Hide(); c.tip=nil
        if GameTooltip:IsOwned(plot) then GameTooltip:Hide() end
    end
    clearHover()
    plot:EnableMouse(true)
    plot:SetScript("OnLeave",clearHover)
    plot:SetScript("OnHide",clearHover)
    plot:SetScript("OnUpdate",function(self)
        if not self:IsMouseOver() or not c.points or #c.points==0 then return end
        local cx,cy=GetCursorPosition()
        local scale=self:GetEffectiveScale()
        local t=c.first+math.max(0,math.min(1,(cx/scale-self:GetLeft())/PLOT_WIDTH))*c.span
        local point,line=F.HistoryAt(c.points,t,(cy/scale-self:GetBottom())/PLOT_HEIGHT*c.maximum,8/PLOT_HEIGHT*c.maximum)
        local v=point.totals
        local x=(point.time-c.first)/c.span*PLOT_WIDTH
        c.cross:ClearAllPoints(); c.cross:SetPoint("BOTTOMLEFT",x,0); c.cross:Show()
        c.total:ClearAllPoints()
        if x>PLOT_WIDTH-140 then c.total:SetPoint("TOPRIGHT",self,"TOPLEFT",x-6,-6) else c.total:SetPoint("TOPLEFT",x+6,-6) end
        c.total:SetText("Total "..F.Money(v.total)); c.total:Show(); c.totalBack:Show()
        c.hover:SetText(date("%d %b %H:%M",point.time).."   Gold "..F.Money(v.gold).."   Other assets "..F.Money(v.assets).."   Equipped Gear "..F.Money(v.equipped))
        local tip=line and tostring(point.time)..line or ""
        if tip~=c.tip then
            c.tip=tip
            if line then showBand(self,point,line,c) elseif GameTooltip:IsOwned(self) then GameTooltip:Hide() end
        end
    end)
end

function F.RefreshChart()
    local c=F.chart
    if not c then return end
    local selected=F.db.settings.chart
    local breakdown=F.db.settings.chartBreakdown or "type"
    for key,b in pairs(c.checks) do b:SetChecked(selected[key]) end
    c.metric:SetText(metricText(selected))
    for key,b in pairs(c.switch) do
        if key==breakdown then b:LockHighlight() else b:UnlockHighlight() end
    end
    local characters=F.SelectedCharacters()
    refreshCharacterPanel(c,characters)
    local points,maximum,first,span=F.StackHistory(F.ChartHistory(F.marketScope),selected,F.marketScope,characters,STEPS,F.Now(),breakdown)
    F.SmoothHistory(points,SMOOTHING)
    local step
    maximum,step=F.AxisScale(maximum)
    c.points,c.maximum,c.tip,c.characters,c.selected,c.breakdown=points,maximum,nil,characters,selected,breakdown
    for _,line in ipairs(c.lines) do line:Hide() end
    for _,fill in ipairs(c.fills) do fill:Hide() end
    drawAxis(c,maximum,step)
    local counts={fills=0,lines=0}
    local latest=points[#points] and points[#points].totals or {total=0,gold=0}
    c.stats.value.value:SetText(F.MoneyShort(latest.total))
    c.stats.gold.value:SetText(F.MoneyShort(latest.gold))
    c.stats.gain.value:SetText(gainText(F.GoldGain(characters,F.Now())))
    local sale=F.OnSale(characters)
    c.stats.sale.value:SetText(F.MoneyShort(sale.total))
    c.stats.listing.value:SetText(F.MoneyShort(sale.deposit))
    if #points>0 then
        c.first,c.span=first,span
        local bands=points[1].values
        local bandColor=bandColors(bands,breakdown)
        refreshLegend(c,bands,bandColor)
        for j,band in ipairs(bands) do
            local curve={}
            for i,p in ipairs(points) do
                curve[i]={x=(p.time-first)/span*PLOT_WIDTH,y=p.values[j].value/maximum*PLOT_HEIGHT}
            end
            drawBand(c,counts,F.SimplifyCurve(curve,SIMPLIFY_TOLERANCE),bandColor[band.key],#bands-j)
        end
        drawMarkers(c,first,span)
        drawHighlights(c,first,span,characters)
        c.startTime:SetText(date("%d %b %H:%M",first)); c.endTime:SetText(date("%d %b %H:%M",first+span))
    end
    if #points==0 then drawHighlights(c) end
    c.empty:SetShown(#points==0 or not next(selected) or not next(characters))
end
