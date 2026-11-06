local _,F=...
local BOOK="Interface/Icons/INV_Misc_Book_09"
local STAMP="Interface/AddOns/ForeverLedger/Media/monkey-stamp"

function F.MinimapPosition(degrees,radius,square)
    local angle=math.rad(degrees)
    local x,y=math.cos(angle),math.sin(angle)
    if square then
        local scale=1/math.max(math.abs(x),math.abs(y))
        x,y=x*scale,y*scale
    end
    return x*radius,y*radius
end

function F.InstallMinimap()
    if not Minimap or F.minimapButton then return end
    local b=CreateFrame("Button","ForeverLedgerMinimapButton",Minimap)
    F.minimapButton=b
    b:SetSize(31,31); b:SetFrameStrata("MEDIUM"); b:SetFrameLevel(8)
    b:RegisterForClicks("LeftButtonUp"); b:RegisterForDrag("LeftButton")
    b:SetHighlightTexture("Interface/Minimap/UI-Minimap-ZoomButton-Highlight")
    -- The tracking ring's opening sits up and right of the button's centre. The icons
    -- no longer fill it, so it needs its own backing.
    local backing=b:CreateTexture(nil,"BACKGROUND")
    backing:SetTexture("Interface/Minimap/UI-Minimap-Background"); backing:SetSize(20,20); backing:SetPoint("TOPLEFT",7,-5)
    local book=b:CreateTexture(nil,"ARTWORK",nil,0)
    book:SetTexture(BOOK); book:SetTexCoord(0.08,0.92,0.08,0.92); book:SetSize(13,13); book:SetPoint("TOPLEFT",13,-11)
    local stamp=b:CreateTexture(nil,"ARTWORK",nil,1)
    stamp:SetTexture(STAMP); stamp:SetSize(14,14); stamp:SetPoint("TOPLEFT",8,-6)
    local ring=b:CreateTexture(nil,"OVERLAY")
    ring:SetTexture("Interface/Minimap/MiniMap-TrackingBorder"); ring:SetSize(53,53); ring:SetPoint("TOPLEFT")
    local function place()
        local square=GetMinimapShape and GetMinimapShape()=="SQUARE"
        local x,y=F.MinimapPosition(F.db.settings.minimapAngle or 160,Minimap:GetWidth()/2+5,square)
        b:ClearAllPoints(); b:SetPoint("CENTER",Minimap,"CENTER",x,y)
    end
    local function follow()
        local scale=Minimap:GetEffectiveScale()
        local cx,cy=Minimap:GetCenter()
        local mx,my=GetCursorPosition()
        F.db.settings.minimapAngle=math.deg(math.atan2(my/scale-cy,mx/scale-cx))%360
        place()
    end
    b:SetScript("OnDragStart",function(self) self:SetScript("OnUpdate",follow); GameTooltip:Hide() end)
    b:SetScript("OnDragStop",function(self) self:SetScript("OnUpdate",nil) end)
    b:SetScript("OnClick",function()
        if IsShiftKeyDown and IsShiftKeyDown() then F.MarkHighlight(); return end
        if F.window and F.window:IsShown() then F.window:Hide() else F.Show() end
    end)
    b:SetScript("OnEnter",function(self)
        GameTooltip:SetOwner(self,"ANCHOR_LEFT")
        GameTooltip:AddLine("Forever Ledger")
        GameTooltip:AddLine("Click: open or close the ledger",1,1,1)
        GameTooltip:AddLine("Shift-click: mark a highlight",1,1,1)
        GameTooltip:AddLine("Drag: move this button",0.6,0.6,0.6)
        GameTooltip:Show()
    end)
    b:SetScript("OnLeave",function() GameTooltip:Hide() end)
    place()
end
