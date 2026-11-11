local _,F=...
local PREFIX="FLedger"
-- 2: long messages carry their length and checksum.
local PROTOCOL=2
-- Told in every hello, so a copy without a feature is never asked for it.
local FEATURES=2
-- An addon message carries 255 bytes, and one of them is the part marker.
local PART_SIZE=254
local MAX_MESSAGE,MAX_UNLINKED=65536,1024
local MAX_REPLY=3000
-- The client throttles each prefix. Stay well under it and honor its refusals.
local BURST,REFILL=8,1.1
local RESULT_RETRY={[3]=true,[8]=true,[11]=true}
local RESULT_OFFLINE=12
local MAX_TRIES=40
local REPLY_TIMEOUT,REPLY_RETRIES=45,3
local ANNOUNCE_EVERY,HIDE_WINDOW=30,15
local PROFIT_EVERY=300
local REQUEST_TIMEOUT,CONFIRM_TIMEOUT,DECLINE_COOLDOWN=20,130,60
local SHARE_TEXT="Both accounts will share their characters' gold, item values and history."

local queue,buffers,states,sentTo,declinedAt={},{},{},{},{}
local tokens,refilled=BURST,nil
local request,asking,announceAt,merged

local function clean(text,limit)
    if type(text)~="string" then return nil end
    return (text:gsub("|","")):sub(1,limit or 100)
end

local function same(a,b)
    return a:lower()==b:lower() or (strcmputf8i and strcmputf8i(a,b)==0)
end

-- A name without a realm is whoever the client finds by it. On Forever that may be a
-- character on another hidden realm, so it must never get this character's realm added.
-- Forever also shows a surname after the name ("Modars Setharius").
local function firstName(name)
    return name:match("^[^-]*"):match("^%s*(%S*)")
end

local function sameCharacter(a,b)
    if same(a,b) then return true end
    if a:find("-",1,true) and b:find("-",1,true) then return false end
    return same(firstName(a),firstName(b))
end

local function state(source)
    states[source]=states[source] or {}
    return states[source]
end

local function peerName(p)
    return p.label or p.lastName or "linked account"
end

local function refresh()
    if not F.window or not F.window:IsShown() then return end
    if F.mode=="overview" then F.RefreshChart()
    elseif F.mode=="sync" then F.RefreshSyncPanel()
    elseif F.mode=="profit" then F.RefreshProfit() end
end

local function setStatus(text)
    F.syncStatus=text
    F.Print(text)
    refresh()
end

-- Characters from another account never enter db.characters, because that table
-- feeds this account's valuation records and its database export.
function F.CharacterInfo(guid)
    local c=F.db.characters[guid]
    if c then return c end
    for _,p in pairs(F.db.peers) do
        if p.characters[guid] then return p.characters[guid] end
    end
end

function F.SyncedCharacters(scope)
    local list={}
    for _,p in pairs(F.db.peers) do
        for guid,c in pairs(p.characters) do
            if F.SameChart(c.marketScope,scope) and not F.db.characters[guid] then
                list[#list+1]={guid=guid,name=c.name or guid,account=peerName(p)}
            end
        end
    end
    return list
end

-- Every account's samples in time order, each carrying the latest known values of
-- all characters. Without synced samples this is simply the local history.
function F.ChartHistory(scope)
    local sources={F.db.history}
    local size=#F.db.history
    for _,p in pairs(F.db.peers) do
        if #p.history>0 then sources[#sources+1]=p.history; size=size+#p.history end
    end
    if #sources==1 then return F.db.history end
    if merged and merged.scope==scope and merged.size==size then return merged.list end
    local all={}
    for s,list in ipairs(sources) do
        for i,h in ipairs(list) do
            if F.SameChart(h.scope,scope) and h.chars then all[#all+1]={h=h,s=s,i=i} end
        end
    end
    table.sort(all,function(a,b)
        if a.h.time~=b.h.time then return a.h.time<b.h.time end
        if a.s~=b.s then return a.s<b.s end
        return a.i<b.i
    end)
    local latest,unpriced,list={},{},{}
    for _,entry in ipairs(all) do
        local h=entry.h
        for guid,v in pairs(h.chars) do
            if entry.s==1 or not F.db.characters[guid] then latest[guid]=v end
        end
        unpriced[entry.s]=h.unpricedRows or 0
        local chars,rows={},0
        for guid,v in pairs(latest) do chars[guid]=v end
        for _,n in pairs(unpriced) do rows=rows+n end
        list[#list+1]={time=h.time,scope=scope,chars=chars,unpricedRows=rows}
    end
    merged={scope=scope,size=size,list=list}
    return list
end

-- A linked character's value per category, as its account last sent it.
function F.LinkedHeld(guid)
    local held={}
    for _,p in pairs(F.db.peers) do
        local categories=p.profit and p.profit.rows[guid]
        for category,v in pairs(categories or {}) do held[category]=v[1] end
    end
    return held
end

-- Adds the selected characters' figures from linked accounts to a profit table.
-- Period figures only count if they were worked out for this exact period. Otherwise
-- only what is held still applies, and the result says so.
function F.LinkedProfit(characters,since,add)
    local status={}
    for _,p in pairs(F.db.peers) do
        local selected=false
        for guid in pairs(p.characters) do selected=selected or characters[guid] end
        local s=p.profit
        if selected and not s then status.missing=true end
        if selected and s then
            status.at=math.min(status.at or s.at,s.at)
            local current=since==s.since
            if since~=0 and not current then status.missing=true end
            for guid,categories in pairs(s.rows) do
                if characters[guid] then
                    local out={}
                    for category,v in pairs(categories) do
                        if since==0 then out[category]={held=v[1],sold=v[5],spent=v[6],change=v[7]}
                        elseif current then out[category]={held=v[1],sold=v[2],spent=v[3],change=v[4]}
                        else out[category]={held=v[1],sold=0,spent=0,change=0} end
                    end
                    add(out)
                end
            end
        end
    end
    return status
end

function F.SyncSummary(lines,total)
    if not next(F.db.peers) then return end
    for _,p in pairs(F.db.peers) do
        lines[#lines+1]=""
        lines[#lines+1]="Linked account: "..peerName(p)..(p.lastSync and " (synced "..date("%d %b %H:%M",p.lastSync)..")" or " (not synced yet)")
        for _,c in pairs(p.characters) do
            total=total+(c.balance or 0)
            lines[#lines+1]=(c.name or "?").."  "..F.Money(c.balance)
        end
    end
    lines[#lines+1]=""
    lines[#lines+1]="All accounts total: "..F.Money(total)
end

local function checksum(text)
    local a,b=1,0
    for i=1,#text do
        a=(a+text:byte(i))%65521
        b=(b+a)%65521
    end
    return b*65536+a
end

-- A long message starts with its length and checksum. The client can lose a part
-- under load, and the parts either side of it can still join into valid JSON.
local function frame(text)
    return #text..":"..checksum(text)..":"..text
end

local function unframe(text)
    local size,sum,body=text:match("^(%d+):(%d+):(.*)$")
    if body and tonumber(size)==#body and tonumber(sum)==checksum(body) then return body end
end

local function whisper(target,payload,ping)
    local text=F.JSON(payload)
    if #text<=PART_SIZE then
        queue[#queue+1]={target=target,text="S"..text,ping=ping}
        return
    end
    text=frame(text)
    local size=#text
    for first=1,size,PART_SIZE do
        local marker=first==1 and "F" or first+PART_SIZE>size and "L" or "M"
        queue[#queue+1]={target=target,text=marker..text:sub(first,first+PART_SIZE-1),ping=ping}
    end
end

local function dropQueued(keep)
    local kept={}
    for _,item in ipairs(queue) do
        if keep(item) then kept[#kept+1]=item end
    end
    queue=kept
end

local function toPeer(source,target,payload,ping)
    payload.s=F.db.sourceID
    payload.k=F.db.peers[source].key
    whisper(target,payload,ping)
end

local function localIndex()
    local chars={}
    for guid,c in pairs(F.db.characters) do
        local last=c.tops and c.tops[#c.tops]
        local l=F.CharacterListings(c)
        chars[guid]={n=c.name,r=c.realm,c=c.class,m=c.marketScope,b=c.balance,t=last and last.time,
            l=l.count>0 and {l.count,l.total,l.deposit,l.estimated} or nil}
    end
    return chars,checksum(F.JSON({l=F.db.accountLabel,c=chars}))
end

-- The recording marker: its name, or none once ended, and when that happened.
local function markerState()
    local at=F.db.markerAt or 0
    if at>0 then return {n=F.db.episode,a=at} end
end

local function hello(source,target,isReply,ping)
    local st=state(source)
    local _,signature=localIndex()
    st.announcedCount,st.announcedSig=#F.db.history,signature
    toPeer(source,target,{t="hello",n=#F.db.history,c=signature,r=isReply and 1 or nil,v=FEATURES,e=markerState()},ping)
end

local function adoptMarker(m,p)
    local e=type(m.e)=="table" and m.e
    local at=e and F.Number(e.a)
    if not at or at<=0 then return end
    local name=clean(e.n,250)
    if name and not name:match("%S") then name=nil end
    F.AdoptMarker(name,at,peerName(p))
end

-- Sent to every linked account online now. The others get it with their next hello.
function F.ShareMarker()
    local e=markerState()
    if not e then return end
    for source,st in pairs(states) do
        if st.online and F.db.peers[source] then toPeer(source,st.online,{t="marker",e=e}) end
    end
end

-- Tries the character seen last first; a reply cancels the remaining pings.
local function announce(source)
    local p,st=F.db.peers[source],state(source)
    dropQueued(function(item) return item.ping~=source end)
    if st.online then hello(source,st.online); return end
    local tried={}
    local function try(name)
        if name and name~="" and not tried[name:lower()] then
            tried[name:lower()]=true
            hello(source,name,false,source)
        end
    end
    try(p.lastName)
    for name in pairs(p.names) do try(name) end
    -- A Forever character can come back on another hidden realm, where its old full
    -- name finds no one. Its name alone still does.
    if not F.isTBC then
        try(p.lastName and firstName(p.lastName))
        for name in pairs(p.names) do try(firstName(name)) end
    end
end

-- Look for the account, and report it if no character answers in time.
local function search(source)
    local st,count=state(source),0
    for _ in pairs(F.db.peers[source].names) do count=count+1 end
    st.notify=true
    st.noticeAt=F.Clock()+count*REFILL+10
    announce(source)
end

-- Figures change with every bag update, so refresh them now and then unless the
-- player is looking at them.
local function profitDue(p,st,key)
    if st.profitForce or not p.profit then return true end
    if p.profit.key==key then return false end
    local watching=F.mode=="profit" and F.window and F.window:IsShown()
    return watching or F.Clock()-(st.profitAt or -PROFIT_EVERY)>=PROFIT_EVERY
end

-- The receiver drives the transfer, so it resumes from what was actually stored.
local function nextRequest(source)
    local p,st=F.db.peers[source],state(source)
    if not p or st.wait or not st.online then return end
    local ask
    if st.signature and st.signature~=p.signature then
        ask={w="index"}
    else
        for guid,c in pairs(p.characters) do
            if c.topTime and not (c.tops and c.tops[1] and c.tops[1].time==c.topTime) then ask={w="top",g=guid}; break end
        end
        if not ask and st.total and #p.history<st.total then ask={w="hist",f=#p.history+1} end
        if not ask and (st.features or 0)>=2 then
            local since=F.GainStart(F.Now())
            local key=tostring(st.signature)..":"..tostring(st.total)..":"..since
            if profitDue(p,st,key) then
                ask={w="profit",f=since}
                st.profitKey,st.profitForce,st.profitAt=key,nil,F.Clock()
            end
        end
    end
    if ask then
        ask.t="pull"
        st.wait={clock=F.Clock(),ask=ask,tries=0}
        toPeer(source,st.online,ask)
    else
        p.lastSync=F.Now()
        if st.notify then
            st.notify=nil
            local count=0
            for _ in pairs(p.characters) do count=count+1 end
            setStatus("Synced "..peerName(p)..": "..count.." characters.")
        end
    end
    refresh()
end

local function own(name)
    name=F.FullName(name)
    if not F.db.owners[name] then
        F.db.owners[name]=true
        F.Emit("owner",{name=name})
    end
end

-- On Forever, a new realm for a known character replaces its old name, so the
-- names to try do not pile up with realms it has left.
local function remember(p,name)
    if not F.isTBC and name:find("-",1,true) then
        for known in pairs(p.names) do
            if known~=name and known:find("-",1,true) and same(firstName(known),firstName(name)) then
                p.names[known]=nil
            end
        end
    end
    p.names[name]=true
end

local function createPeer(source,name,key,label)
    local p=F.db.peers[source] or {characters={},history={},names={}}
    F.db.peers[source]=p
    p.key,p.label,p.lastName=key,clean(label,50),name
    remember(p,name)
    own(name)
    F.Emit("sync_linked",{sourceID=source,name=name})
    return p
end

-- History synced before messages were checked can have rows missing, repeated or
-- spliced together. Fetch it again once; everything else is replaced on each sync.
function F.RepairPeerHistory()
    if F.db.peerHistoryRefetched then return end
    F.db.peerHistoryRefetched=true
    for _,p in pairs(F.db.peers) do p.history={} end
    merged=nil
end

local function applyTotal(p,st,total)
    total=F.Number(total)
    if not total then return end
    st.total,p.total=total,total
    -- The other account restored a backup. What was stored no longer matches it.
    if total<#p.history then p.history={}; merged=nil end
end

local function topRows(rows)
    local result={}
    for _,row in ipairs(type(rows)=="table" and rows or {}) do
        local value=F.Number(row.v)
        if value and type(row.k)=="string" then
            result[#result+1]={key=clean(row.k),value=value,quantity=F.Number(row.q),name=clean(row.n),quality=F.Number(row.c)}
        end
    end
    return result
end

local function sendTop(source,sender,guid)
    local c=type(guid)=="string" and F.db.characters[guid]
    local last=c and c.tops and c.tops[#c.tops]
    local function rows(list)
        local market=F.db.markets and F.db.markets[c.marketScope]
        local out={}
        for _,e in ipairs(list or {}) do
            local item=market and market.catalog[e.key] or {}
            out[#out+1]={k=e.key,v=e.value,q=e.quantity,n=item.name,c=item.quality}
        end
        return out
    end
    toPeer(source,sender,{t="top",g=guid,at=last and last.time,a=last and rows(last.assets),e=last and rows(last.equipped)})
end

-- Worked out here, because the other account's raw records never cross over. One
-- list per character and category: held, then sold, spent and stock change for the
-- period asked about, then the same three for all time.
local function sendProfit(source,sender,since)
    local period,all=F.AccountProfit(since),F.AccountProfit(0)
    local rows={}
    local function collect(guid,category)
        rows[guid]=rows[guid] or {}
        if rows[guid][category] then return end
        local a=all[guid] and all[guid][category] or {}
        local t=period[guid] and period[guid][category] or {}
        rows[guid][category]={a.held or t.held or 0,t.sold or 0,t.spent or 0,t.change or 0,a.sold or 0,a.spent or 0,a.change or 0}
    end
    for _,figures in ipairs({all,period}) do
        for guid,categories in pairs(figures) do
            for category in pairs(categories) do collect(guid,category) end
        end
    end
    toPeer(source,sender,{t="profit",f=since,at=F.Now(),c=rows})
end

-- Samples only list the characters whose values changed. A batch names each
-- character and scope once. Both keep a first sync within the message budget.
local function sendHistory(source,sender,from)
    local history=F.db.history
    local guids,guidIndex,scopes,scopeIndex,rows,size={},{},{},{},{},0
    local function indexOf(list,index,value)
        if not index[value] then
            list[#list+1]=value; index[value]=#list
            size=size+#value+3
        end
        return index[value]
    end
    for i=math.max(1,from),#history do
        if size>=MAX_REPLY then break end
        local h=history[i]
        local previous
        for j=i-1,1,-1 do
            if history[j].scope==h.scope then previous=history[j]; break end
        end
        local changed={}
        for guid,v in pairs(h.chars or {}) do
            local before=previous and previous.chars and previous.chars[guid]
            if not before or before.gold~=v.gold or before.assets~=v.assets or before.equipped~=v.equipped then
                changed[#changed+1]=indexOf(guids,guidIndex,guid)
                changed[#changed+1]=v.gold or 0
                changed[#changed+1]=v.assets or 0
                changed[#changed+1]=v.equipped or 0
            end
        end
        rows[#rows+1]={h.time,indexOf(scopes,scopeIndex,h.scope or "unknown"),h.unpricedRows or 0,changed}
        size=size+20+#changed*8
    end
    toPeer(source,sender,{t="hist",f=from,n=#history,g=guids,m=scopes,r=rows})
end

local handlers={}

function handlers.hello(m,sender,p,st)
    p.label=clean(m.l,50) or p.label
    st.signature=F.Number(m.c)
    st.features=F.Number(m.v)
    applyTotal(p,st,m.n)
    -- Before replying, so the reply carries the marker both now share.
    adoptMarker(m,p)
    if not m.r then hello(m.s,sender,true) end
    nextRequest(m.s)
end

function handlers.marker(m,sender,p)
    adoptMarker(m,p)
end

function handlers.pull(m,sender)
    if m.w=="index" then
        local chars,signature=localIndex()
        toPeer(m.s,sender,{t="index",c=chars,l=F.db.accountLabel,sig=signature})
    elseif m.w=="top" then sendTop(m.s,sender,m.g)
    elseif m.w=="hist" and F.Number(m.f) then sendHistory(m.s,sender,F.Number(m.f))
    elseif m.w=="profit" and F.Number(m.f) then sendProfit(m.s,sender,F.Number(m.f)) end
end

function handlers.index(m,sender,p,st)
    p.label=clean(m.l,50) or p.label
    for guid,v in pairs(type(m.c)=="table" and m.c or {}) do
        if type(v)=="table" and not F.db.characters[guid] then
            local c=p.characters[guid] or {}
            p.characters[guid]=c
            c.name,c.realm,c.class=clean(v.n,80),clean(v.r,50),clean(v.c,20)
            c.marketScope,c.balance,c.topTime=clean(v.m),F.Number(v.b),F.Number(v.t)
            local l=type(v.l)=="table" and v.l or {}
            c.listings={count=F.Number(l[1]) or 0,total=F.Number(l[2]) or 0,deposit=F.Number(l[3]) or 0,estimated=F.Number(l[4]) or 0}
            if c.name then remember(p,c.name); own(c.name) end
        end
    end
    p.signature=F.Number(m.sig)
    st.signature,st.wait=p.signature,nil
    nextRequest(m.s)
end

function handlers.top(m,sender,p,st)
    local c=type(m.g)=="string" and p.characters[m.g]
    if c then
        c.topTime=F.Number(m.at)
        c.tops=c.topTime and {{time=c.topTime,assets=topRows(m.a),equipped=topRows(m.e)}} or nil
    end
    st.wait=nil
    nextRequest(m.s)
end

function handlers.hist(m,sender,p,st)
    local from=F.Number(m.f)
    local guids,scopes=type(m.g)=="table" and m.g or {},type(m.m)=="table" and m.m or {}
    if from==1 then p.history={}; merged=nil end
    local stored=#p.history
    if from==stored+1 then
        for _,row in ipairs(type(m.r)=="table" and m.r or {}) do
            local time,scope=type(row)=="table" and F.Number(row[1]),type(row)=="table" and scopes[row[2]]
            if not time or type(scope)~="string" then break end
            local chars,changed={},type(row[4])=="table" and row[4] or {}
            for i=1,#changed,4 do
                local guid=guids[changed[i]]
                if type(guid)=="string" then
                    chars[guid]={gold=F.Number(changed[i+1]) or 0,assets=F.Number(changed[i+2]) or 0,equipped=F.Number(changed[i+3]) or 0}
                end
            end
            p.history[#p.history+1]={time=time,scope=clean(scope),unpricedRows=F.Number(row[3]) or 0,chars=chars}
        end
    end
    applyTotal(p,st,m.n)
    -- A reply that stored nothing must not repeat the same request forever.
    if from==stored+1 and #p.history==stored then st.total=stored end
    st.wait=nil
    nextRequest(m.s)
end

function handlers.profit(m,sender,p,st)
    local rows={}
    for guid,categories in pairs(type(m.c)=="table" and m.c or {}) do
        -- Only characters this link announced, never one of this account's own.
        if p.characters[guid] and not F.db.characters[guid] and type(categories)=="table" then
            rows[guid]={}
            for category,v in pairs(categories) do
                local values={}
                for i=1,7 do values[i]=type(v)=="table" and F.Number(v[i]) or 0 end
                local name=clean(category,30)
                if name then rows[guid][name]=values end
            end
        end
    end
    local since,at=F.Number(m.f),F.Number(m.at)
    if since and at then p.profit={since=since,at=at,rows=rows,key=st.profitKey} end
    st.wait=nil
    nextRequest(m.s)
    refresh()
end

function handlers.unlink(m,sender,p)
    F.Emit("sync_unlinked",{sourceID=m.s,name=sender})
    local name=peerName(p)
    F.db.peers[m.s]=nil; states[m.s]=nil; merged=nil
    setStatus(name.." unlinked this account. Its synced data was removed here.")
end

local function showRequest(sender,source)
    asking={sender=sender,source=source}
    whisper(sender,{t="asked"})
    if not StaticPopupDialogs or not StaticPopup_Show then return end
    StaticPopupDialogs.FOREVERLEDGER_SYNC_CONFIRM={
        text="%s wants to link accounts with Forever Ledger.\n\nAccept only if this character is yours. "..SHARE_TEXT,
        button1="Link accounts",button2="Decline",
        timeout=120,whileDead=true,hideOnEscape=true,preferredIndex=3,
        OnAccept=function() F.SyncAnswer(true) end,
        OnCancel=function() F.SyncAnswer(false) end,
    }
    StaticPopup_Show("FOREVERLEDGER_SYNC_CONFIRM",sender)
end

function F.SyncAnswer(accept)
    local a=asking
    if not a then return end
    asking=nil
    if not accept then
        declinedAt[a.sender:lower()]=F.Clock()
        whisper(a.sender,{t="declined"})
        return
    end
    local key=F.Now()..":"..math.random(100000,999999)..":"..math.random(100000,999999)
    createPeer(a.source,a.sender,key)
    local st=state(a.source)
    st.online,st.notify=a.sender,true
    whisper(a.sender,{t="linked",s=F.db.sourceID,k=key,l=F.db.accountLabel})
    setStatus("Linked with "..a.sender..". Syncing.")
end

-- These four run before an account is linked. Only a character the player typed
-- can answer, and only the player's own confirmation can create the link.
local open={}

function open.link(m,sender)
    if type(m.s)~="string" or m.s==F.db.sourceID then return end
    if m.v~=PROTOCOL then whisper(sender,{t="declined",why="version"}); return end
    local declined=declinedAt[sender:lower()]
    if asking or (declined and F.Clock()-declined<DECLINE_COOLDOWN) then return end
    showRequest(sender,m.s)
end

function open.asked(_,sender)
    if not request or not sameCharacter(request.name,sender) then return end
    request.asked=true
    setStatus("Waiting for "..sender.." to confirm on that account.")
end

function open.declined(m,sender)
    if not request or not sameCharacter(request.name,sender) then return end
    request=nil
    setStatus(m.why=="version" and sender.." runs a different Forever Ledger version. Update both accounts."
        or sender.." declined the link.")
end

function open.linked(m,sender)
    if not request or not sameCharacter(request.name,sender) then return end
    if type(m.s)~="string" or type(m.k)~="string" or m.s==F.db.sourceID then return end
    request=nil
    createPeer(m.s,sender,m.k,m.l)
    local st=state(m.s)
    st.online,st.notify=sender,true
    setStatus("Linked with "..sender..". Syncing.")
    hello(m.s,sender)
end

local function reassemble(sender,text)
    local marker,body=text:sub(1,1),text:sub(2)
    if marker=="S" then return body end
    local known=false
    for _,p in pairs(F.db.peers) do known=known or p.names[sender] end
    local limit=known and MAX_MESSAGE or MAX_UNLINKED
    if marker=="F" then
        buffers[sender]={parts={body},size=#body}
        return
    end
    local buffer=buffers[sender]
    if not buffer then return end
    buffer.size=buffer.size+#body
    if buffer.size>limit then buffers[sender]=nil; return end
    buffer.parts[#buffer.parts+1]=body
    if marker=="L" then
        buffers[sender]=nil
        -- A message that lost a part is dropped; the request for it is retried.
        return unframe(table.concat(buffer.parts))
    end
end

F.events.CHAT_MSG_ADDON=function(prefix,text,channel,sender)
    if issecretvalue and (issecretvalue(prefix) or issecretvalue(text) or issecretvalue(sender)) then return end
    if prefix~=PREFIX or channel~="WHISPER" or type(text)~="string" or type(sender)~="string" then return end
    -- Reply to the name exactly as the client gave it; it knows where that character is.
    -- A long reply is still arriving; do not count it as silence.
    for _,st in pairs(states) do
        if st.wait and st.online==sender then st.wait.clock=F.Clock() end
    end
    local message=reassemble(sender,text)
    local m=message and F.ParseJSON(message)
    if type(m)~="table" then return end
    if open[m.t] then open[m.t](m,sender); return end
    local p=handlers[m.t] and type(m.s)=="string" and F.db.peers[m.s]
    if not p or m.k~=p.key then return end
    local st=state(m.s)
    st.online,st.noticeAt,st.heardAt=sender,nil,F.Clock()
    remember(p,sender); p.lastName=sender
    own(sender)
    dropQueued(function(item) return item.ping~=m.s end)
    handlers[m.t](m,sender,p,st)
end

-- sentAt is when the whisper that failed went out, if the report could be about
-- another whisper to a similar name.
function F.SyncOffline(name,sentAt)
    if request and sameCharacter(request.name,name) then
        request=nil
        setStatus(name.." is not online. Log in to it on the other account, then try again.")
    end
    local stale
    for source,st in pairs(states) do
        if st.online and same(st.online,name) then
            if sentAt and st.heardAt and st.heardAt>=sentAt then
                -- It answered after that whisper went out, so the report is about another name.
                stale=true
            else
                st.online,st.wait=nil,nil
                -- The account may be online on another character, or on another hidden realm.
                if st.notify then search(source) else announce(source) end
            end
        end
    end
    if not stale then dropQueued(function(item) return item.ping or not same(item.target,name) end) end
    refresh()
end

-- Finding the other account means whispering characters that may be offline. The
-- client reports each of those in chat, so hide the replies to these whispers only.
local function hideNotFound(_,_,message)
    local format=ERR_CHAT_PLAYER_NOT_FOUND_S
    if not format or type(message)~="string" or (issecretvalue and issecretvalue(message)) then return false end
    local pattern=format:gsub("([%^%$%(%)%.%[%]%*%+%-%?])","%%%1"):gsub("%%s","(.+)")
    local name=message:match("^"..pattern.."$")
    local sent=name and sentTo[name:lower()]
    if not sent or F.Clock()-sent.clock>HIDE_WINDOW then return false end
    F.SyncOffline(sent.name,sent.clock)
    return true
end
F.SyncHideNotFound=hideNotFound

local function flush()
    local now=F.Clock()
    tokens=math.min(BURST,tokens+(now-(refilled or now))/REFILL)
    refilled=now
    while tokens>=1 and queue[1] do
        local item=queue[1]
        local send=C_ChatInfo and C_ChatInfo.SendAddonMessage or SendAddonMessage
        local result=F.Call(send,PREFIX,item.text,"WHISPER",item.target)
        item.tries=(item.tries or 0)+1
        if (RESULT_RETRY[result] or result==false) and item.tries<MAX_TRIES then
            tokens=0
            break
        end
        table.remove(queue,1)
        tokens=tokens-1
        local mark={name=item.target,clock=now}
        sentTo[item.target:lower()]=mark
        sentTo[item.target:match("^[^-]+"):lower()]=mark
        if result==RESULT_OFFLINE then F.SyncOffline(item.target) end
    end
end

function F.SyncTick()
    flush()
    local now=F.Clock()
    if announceAt and now>=announceAt then
        announceAt=nil
        for source in pairs(F.db.peers) do announce(source) end
    end
    if request and now-request.clock>(request.asked and CONFIRM_TIMEOUT or REQUEST_TIMEOUT) then
        local asked,name=request.asked,request.name
        request=nil
        setStatus(asked and name.." did not confirm in time."
            or "No reply from "..name..". It must be online, on the same faction, with Forever Ledger enabled.")
    end
    for source,st in pairs(states) do
        local p=F.db.peers[source]
        if st.wait and now-st.wait.clock>REPLY_TIMEOUT then
            st.wait.tries=st.wait.tries+1
            if st.wait.tries>REPLY_RETRIES or not st.online then
                st.online,st.wait=nil,nil
            else
                st.wait.clock=now
                toPeer(source,st.online,st.wait.ask)
            end
            refresh()
        end
        if st.noticeAt and now>=st.noticeAt then
            st.noticeAt,st.notify=nil,nil
            setStatus("No reply from "..peerName(p)..". A character on it must be online, on the same faction, with Forever Ledger enabled.")
        end
        if st.online and not st.wait and now>=(st.nextAnnounce or 0) then
            st.nextAnnounce=now+ANNOUNCE_EVERY
            local _,signature=localIndex()
            if signature~=st.announcedSig or #F.db.history~=st.announcedCount then hello(source,st.online,true) end
        end
    end
end

function F.InstallSync()
    F.Call(C_ChatInfo and C_ChatInfo.RegisterAddonMessagePrefix or RegisterAddonMessagePrefix,PREFIX)
    local addFilter=ChatFrame_AddMessageEventFilter or (ChatFrameUtil and ChatFrameUtil.AddMessageEventFilter)
    if addFilter then addFilter("CHAT_MSG_SYSTEM",hideNotFound) end
    announceAt=F.Clock()+5
end

function F.SyncAdd(text)
    local name=(text or ""):match("^%s*(.-)%s*$")
    if name=="" then return false end
    for _,c in pairs(F.db.characters) do
        if c.name and sameCharacter(c.name,name) then
            setStatus(name.." is on this account. Enter a character from your other account.")
            return false
        end
    end
    for source,p in pairs(F.db.peers) do
        for known in pairs(p.names) do
            -- Offline may mean the other side unlinked, so fall through and ask again.
            if sameCharacter(known,name) and state(source).online then F.SyncNow(source); return true end
        end
    end
    request={name=name,clock=F.Clock()}
    whisper(name,{t="link",s=F.db.sourceID,v=PROTOCOL})
    setStatus("Asking "..name.." to link accounts.")
    return true
end

function F.SyncNow(only)
    if not next(F.db.peers) then
        setStatus("No linked account yet. Add a character from your other account first.")
        return
    end
    for source in pairs(F.db.peers) do
        if not only or only==source then search(source) end
    end
    refresh()
end

-- The player opened the figures, so bring them up to date if the account is online.
function F.SyncRefreshProfit()
    for source in pairs(F.db.peers) do
        state(source).profitForce=true
        nextRequest(source)
    end
end

function F.SyncUnlink(source)
    local p,st=F.db.peers[source],state(source)
    if not p then return end
    if st.online then toPeer(source,st.online,{t="unlink"}) end
    F.Emit("sync_unlinked",{sourceID=source,name=p.lastName})
    local name=peerName(p)
    F.db.peers[source]=nil; states[source]=nil; merged=nil
    setStatus("Unlinked "..name..". Its synced data was removed here.")
end

function F.PromptSyncAdd()
    if not StaticPopupDialogs or not StaticPopup_Show then F.Print("Use /fl sync add Name-Realm."); return end
    local edit=F.PopupEditBox
    StaticPopupDialogs.FOREVERLEDGER_SYNC_ADD={
        text="Enter a character on your other account, as Name or Name-Realm. It must be online, and you will confirm the link there.",
        button1="Add character",button2="Cancel",hasEditBox=true,maxLetters=80,
        timeout=0,whileDead=true,hideOnEscape=true,preferredIndex=3,
        OnShow=function(dialog) local box=edit(dialog); box:SetText(""); box:SetFocus() end,
        OnAccept=function(dialog) F.SyncAdd(edit(dialog):GetText()) end,
        EditBoxOnEnterPressed=function(box) if F.SyncAdd(box:GetText()) then StaticPopup_Hide("FOREVERLEDGER_SYNC_ADD") end end,
    }
    StaticPopup_Show("FOREVERLEDGER_SYNC_ADD")
end

function F.PromptSyncUnlink(source)
    local p=F.db.peers[source]
    if not p then return end
    if not StaticPopupDialogs or not StaticPopup_Show then F.SyncUnlink(source); return end
    StaticPopupDialogs.FOREVERLEDGER_SYNC_UNLINK={
        text="Unlink %s? Its synced data is removed from this account, and from that account if it is online. Recorded events are kept.",
        button1="Unlink",button2="Cancel",
        timeout=0,whileDead=true,hideOnEscape=true,preferredIndex=3,
        OnAccept=function() F.SyncUnlink(source) end,
    }
    StaticPopup_Show("FOREVERLEDGER_SYNC_UNLINK",peerName(p))
end

function F.SyncCommand(rest)
    local action,argument=(rest or ""):match("^(%S*)%s*(.-)%s*$")
    action=action:lower()
    if action=="add" then
        if argument=="" then F.PromptSyncAdd() else F.SyncAdd(argument) end
    elseif action=="now" then F.SyncNow()
    elseif action=="remove" and argument~="" then
        for source,p in pairs(F.db.peers) do
            if same(peerName(p),argument) then F.PromptSyncUnlink(source); return end
        end
        F.Print("No linked account named "..argument..".")
    else F.Show("sync") end
end

local function describe(source,p)
    local st=state(source)
    local count=0
    for _ in pairs(p.characters) do count=count+1 end
    local parts={"|cffffffff"..peerName(p).."|r  "..count..(count==1 and " character" or " characters")}
    parts[#parts+1]=st.online and "connected through "..st.online or "offline"
    parts[#parts+1]=p.lastSync and "last synced "..date("%d %b %H:%M",p.lastSync) or "not synced yet"
    return table.concat(parts,"  |  ")
end

-- How much of the other account has arrived, from what is actually stored, so it
-- survives a reload. Returns the fraction, the text and whether it is done.
function F.SyncProgress(source)
    local p,st=F.db.peers[source],state(source)
    local all=st.total or p.total or #p.history
    local got=math.min(#p.history,all)
    for _,c in pairs(p.characters) do
        if c.topTime then
            all=all+1
            if c.tops and c.tops[1] and c.tops[1].time==c.topTime then got=got+1 end
        end
    end
    local listing=st.signature and st.signature~=p.signature
    local waiting=st.wait and st.wait.ask.w~="profit"
    if p.lastSync and got>=all and not waiting and not listing then return 1,"Complete",true end
    local fraction=all>0 and got/all or 0
    local percent=math.floor(fraction*100).."%"
    if st.online then
        if st.wait or all>0 then return fraction,"Syncing "..percent,false end
        return fraction,"Connecting",false
    end
    if st.notify then return fraction,"Looking for "..peerName(p),false end
    if got>0 then return fraction,"Paused at "..percent..". Waiting for that account to come online.",false end
    return fraction,"Not connected",false
end

function F.BuildSyncPanel(parent)
    local s=CreateFrame("Frame",nil,parent); s:SetPoint("TOPLEFT",16,-58); s:SetSize(612,430); s.rows={}
    F.syncPanel=s
    local intro=s:CreateFontString(nil,"OVERLAY","GameFontHighlight")
    intro:SetPoint("TOPLEFT",0,0); intro:SetWidth(612); intro:SetJustifyH("LEFT")
    intro:SetText("Link your other account to see all of its characters in this window. Add one of its characters while it is online, then confirm on that account. "
        ..SHARE_TEXT.." They stay up to date whenever both accounts are online.")
    local function button(text,x,action)
        local b=CreateFrame("Button",nil,s,"UIPanelButtonTemplate")
        b:SetSize(120,24); b:SetPoint("TOPLEFT",x,-66); b:SetText(text); b:SetScript("OnClick",action)
        return b
    end
    s.add=button("Add character",0,F.PromptSyncAdd)
    s.now=button("Sync now",128,function() F.SyncNow() end)
    s.status=s:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall")
    s.status:SetPoint("TOPLEFT",0,-98); s.status:SetWidth(612); s.status:SetJustifyH("LEFT")
    s.empty=s:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall")
    s.empty:SetPoint("TOPLEFT",0,-124); s.empty:SetWidth(612); s.empty:SetJustifyH("LEFT")
    s.empty:SetText("No linked account yet.")
    s:Hide()
end

function F.RefreshSyncPanel()
    local s=F.syncPanel
    if not s then return end
    s.status:SetText(F.syncStatus or "")
    local sources={}
    for source in pairs(F.db.peers) do sources[#sources+1]=source end
    table.sort(sources)
    for _,row in ipairs(s.rows) do row:Hide() end
    for i,source in ipairs(sources) do
        local row=s.rows[i]
        if not row then
            row=CreateFrame("Frame",nil,s); row:SetPoint("TOPLEFT",0,-124-(i-1)*34); row:SetSize(612,30)
            row.text=row:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall")
            row.text:SetPoint("TOPLEFT",0,-2); row.text:SetWidth(508); row.text:SetJustifyH("LEFT")
            row.bar=CreateFrame("StatusBar",nil,row)
            row.bar:SetPoint("TOPLEFT",0,-16); row.bar:SetSize(508,14)
            row.bar:SetStatusBarTexture("Interface\\TargetingFrame\\UI-StatusBar"); row.bar:SetMinMaxValues(0,1)
            local back=row.bar:CreateTexture(nil,"BACKGROUND"); back:SetAllPoints(); back:SetColorTexture(0.1,0.1,0.1,0.9)
            row.bar.label=row.bar:CreateFontString(nil,"OVERLAY","GameFontHighlightSmall"); row.bar.label:SetPoint("CENTER")
            row.unlink=CreateFrame("Button",nil,row,"UIPanelButtonTemplate")
            row.unlink:SetSize(96,24); row.unlink:SetPoint("TOPLEFT",516,0); row.unlink:SetText("Unlink")
            row.unlink:SetScript("OnClick",function(self) F.PromptSyncUnlink(self.source) end)
            s.rows[i]=row
        end
        row.unlink.source=source
        row.text:SetText(describe(source,F.db.peers[source]))
        local fraction,text,done=F.SyncProgress(source)
        row.bar:SetValue(fraction); row.bar.label:SetText(text)
        if done then row.bar:SetStatusBarColor(0.165,0.663,0.408)
        elseif state(source).online then row.bar:SetStatusBarColor(0.290,0.608,0.847)
        else row.bar:SetStatusBarColor(0.45,0.45,0.45) end
        row:Show()
    end
    s.empty:SetShown(#sources==0)
end
