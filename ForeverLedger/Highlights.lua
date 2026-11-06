local _,F=...
-- Highlights are moments to find again in the recording. They are their own records
-- and never touch the gold figures or the value chart.
BINDING_HEADER_FOREVERLEDGER="Forever Ledger"
BINDING_NAME_FOREVERLEDGER_HIGHLIGHT="Mark a highlight"

local function text(value)
    if type(value)~="string" then return nil end
    value=value:match("^%s*(.-)%s*$")
    if value=="" then return nil end
    return value
end

-- "12:34" under an hour, "1:02:03" from then on.
function F.Duration(seconds)
    seconds=math.max(0,math.floor(seconds))
    local h,m,s=math.floor(seconds/3600),math.floor(seconds/60)%60,seconds%60
    if h>0 then return string.format("%d:%02d:%02d",h,m,s) end
    return string.format("%d:%02d",m,s)
end

-- Every highlight still standing, oldest first. Each knows the marker it fell under and
-- how far into it, and its number: counted per marker, or per day without one.
function F.Highlights(first,last,characters)
    local removed={}
    for _,e in ipairs(F.db.events) do
        if e.kind=="highlight_removed" and e.data.highlightID then removed[e.data.highlightID]=true end
    end
    local list,counts,marker={},{},nil
    for _,e in ipairs(F.db.events) do
        if e.kind=="episode_start" then marker={name=e.data.name,time=e.time}
        elseif e.kind=="episode_end" then marker=nil
        elseif e.kind=="highlight" and not removed[e.id] then
            local group=marker and "marker:"..marker.time or "day:"..date("%Y-%m-%d",e.time)
            counts[group]=(counts[group] or 0)+1
            if (not first or e.time>=first) and (not last or e.time<=last) and (not characters or characters[e.character]) then
                list[#list+1]={id=e.id,time=e.time,number=counts[group],note=e.data.note,zone=e.data.zone,
                    subzone=e.data.subzone,character=e.character,characterName=e.characterName,
                    marker=marker and marker.name,since=marker and e.time-marker.time}
            end
        end
    end
    return list
end

function F.MarkHighlight(note)
    if not F.db then return end
    local zone=text(GetRealZoneText and GetRealZoneText() or GetZoneText and GetZoneText())
    local subzone=text(GetSubZoneText and GetSubZoneText())
    if subzone==zone then subzone=nil end
    local e=F.Emit("highlight",{note=text(note),zone=zone,subzone=subzone})
    local list=F.Highlights(e.time,e.time)
    local h=list[#list]
    F.Print("Highlight "..h.number.." at "..date("%H:%M:%S",e.time)..(h.since and " (+"..F.Duration(h.since)..")" or "")..
        (h.note and ": "..h.note or ""))
    F.RefreshHighlights()
    return e
end

-- Takes back this account's latest highlight, for a key pressed by mistake.
function F.RemoveLastHighlight()
    local list=F.Highlights()
    local h=list[#list]
    if not h then F.Print("No highlight to remove."); return end
    F.Emit("highlight_removed",{highlightID=h.id})
    F.Print("Removed highlight "..h.number.." from "..date("%H:%M:%S",h.time)..".")
    F.RefreshHighlights()
    return h
end

function F.HighlightCommand(rest)
    if rest=="undo" or rest=="remove" then return F.RemoveLastHighlight() end
    return F.MarkHighlight(rest)
end

function F.RefreshHighlights()
    if F.window and F.window:IsShown() and F.mode=="overview" then F.RefreshChart() end
end
