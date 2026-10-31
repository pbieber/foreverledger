local addon,F=...
local frame=CreateFrame("Frame")
local function errorHandler(err)
    if F.db then
        F.errors=F.errors or {}
        local text=tostring(err)
        if not F.errors[text] then
            F.errors[text]=true
            F.Emit("diagnostic",{message=text})
            if F.Print then F.Print("Collector error recorded: "..text) end
        end
    else print("Forever Ledger: "..tostring(err)) end
end
local function safe(fn,...)
    local args,n={...},select("#",...)
    xpcall(function() fn(unpack(args,1,n)) end,errorHandler)
end
frame:RegisterEvent("ADDON_LOADED")
frame:RegisterEvent("PLAYER_LOGIN")
frame:RegisterEvent("PLAYER_LOGOUT")
frame:SetScript("OnEvent",function(_,event,...)
    if event=="ADDON_LOADED" then
        local name=...
        if name==addon then ForeverLedgerDB=ForeverLedgerDB or {} end
    elseif event=="PLAYER_LOGIN" then
        safe(function()
            local name,realm=UnitFullName("player")
            realm=GetNormalizedRealmName() or realm
            local version,build=GetBuildInfo()
            F.Init(ForeverLedgerDB,{guid=UnitGUID("player"),name=name.."-"..realm,
                realm=realm,build=tostring(version).."/"..tostring(build)})
            F.ObserveBalance(GetMoney())
            F.InstallHooks()
            F.InstallPriceHooks()
            for e in pairs(F.events) do
                local ok=pcall(frame.RegisterEvent,frame,e)
                if not ok then F.Emit("capability_missing",{event=e}) end
            end
            F.ScanBags(true); F.ScanEquipment()
            F.RecordValue(true)
            SLASH_FOREVERLEDGER1="/fl"; SLASH_FOREVERLEDGER2="/foreverledger"
            SlashCmdList.FOREVERLEDGER=function(msg) safe(F.Command,msg) end
            F.Print("Recording. /fl opens the ledger. /fl account Main labels this account.")
            F.PromptMarker()
        end)
    elseif F.db then
        if event=="PLAYER_LOGOUT" then
            safe(function() F.ObserveBalance(GetMoney(),F.context); F.Flush(); F.RecordValue(); F.Emit("logout",{}) end)
        elseif F.events[event] then safe(F.events[event],...) end
    end
end)
local elapsed=0
frame:SetScript("OnUpdate",function(_,dt)
    elapsed=elapsed+dt
    if elapsed<0.25 or not F.db then return end
    elapsed=0
    safe(function()
        if F.bagDirty and F.Clock()-F.bagDirty>0.5 then F.bagDirty=nil; F.ScanBags(); if F.context.bank then F.ScanBank() end end
        if F.bankDirty then F.bankDirty=nil; F.ScanBank() end
        if F.equipmentDirty then F.equipmentDirty=nil; F.ScanEquipment() end
        if F.mailDirty then F.mailDirty=nil; F.ScanMail() end
        if F.pendingMail and F.Clock()-F.pendingMail.started>30 then
            F.Emit("diagnostic",{message="Mail action timed out",mail=F.pendingMail}); F.pendingMail=nil
        end
        if F.lastActivity and F.Clock()-F.lastActivity>2 then F.Flush(); F.lastActivity=nil end
        F.PriceTick()
        F.RecordValue()
        if F.RefreshScanStatus and F.window and F.window:IsShown() then F.RefreshScanStatus() end
    end)
end)
