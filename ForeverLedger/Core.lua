local _, F = ...
ForeverLedger = F
F.VERSION = "0.2.0"
F.SCHEMA = 1

function F.Copy(value)
    if type(value) ~= "table" then return value end
    local result = {}
    for k, v in pairs(value) do result[k] = F.Copy(v) end
    return result
end

function F.Number(value)
    if issecretvalue and issecretvalue(value) then return nil end
    if type(value) ~= "number" or value ~= value or math.abs(value) > 9007199254740991 then return nil end
    return math.floor(value)
end

function F.Now() return GetServerTime and GetServerTime() or time() end
function F.Clock() return GetTime and GetTime() or F.Now() end
function F.FullName(name)
    if not name or name == "" then return nil end
    if not name:find("-", 1, true) then name = name .. "-" .. (GetNormalizedRealmName() or "") end
    return name
end

local function escape(s)
    return '"' .. s:gsub('[%z\1-\31\\"]', function(c)
        if c == '"' then return '\\"' end
        if c == '\\' then return '\\\\' end
        return string.format("\\u%04x", string.byte(c))
    end) .. '"'
end

function F.JSON(v)
    local t = type(v)
    if t == "nil" then return "null" end
    if t == "string" then return escape(v) end
    if t == "boolean" then return v and "true" or "false" end
    if t == "number" then
        assert(F.Number(v), "Non-finite or unsafe JSON number")
        return v%1==0 and string.format("%.0f",v) or string.format("%.17g",v)
    end
    assert(t == "table", "Unsupported JSON value: " .. t)
    local n, array, keys = 0, true, {}
    for k in pairs(v) do
        n = n + 1
        if type(k) ~= "number" or k < 1 or k % 1 ~= 0 then array = false end
        keys[#keys + 1] = k
    end
    array = array and n > 0 and #v == n
    local out = {}
    if array then
        for i = 1, n do out[i] = F.JSON(v[i]) end
        return "[" .. table.concat(out, ",") .. "]"
    end
    table.sort(keys, function(a,b) return tostring(a) < tostring(b) end)
    for _, k in ipairs(keys) do out[#out + 1] = escape(tostring(k)) .. ":" .. F.JSON(v[k]) end
    return "{" .. table.concat(out, ",") .. "}"
end

function F.Init(db, identity)
    assert(not db.schema or db.schema == F.SCHEMA, "Unsupported saved-data schema; backup before upgrading")
    db.schema = F.SCHEMA
    db.sourceID = db.sourceID or (identity.guid .. ":" .. F.Now() .. ":" .. math.random(100000,999999))
    db.sequence = db.sequence or 0
    db.events, db.characters, db.auctions = db.events or {}, db.characters or {}, db.auctions or {}
    db.owners, db.settings = db.owners or {}, db.settings or {}
    db.settings.commissionBps = db.settings.commissionBps or 500
    F.db, F.identity = db, identity
    F.baselined, F.session = false, nil
    db.owners[identity.name] = true
    F.character = db.characters[identity.guid] or {name=identity.name, realm=identity.realm}
    db.characters[identity.guid] = F.character
    F.character.snapshots = F.character.snapshots or {}
    F.batch, F.intents = {balances={}, claims={}}, {}
    F.session = F.Emit("session", {version=F.VERSION, build=identity.build}).id
    if F.InitValuation then F.InitValuation() end
end

function F.Emit(kind, data)
    local db = F.db
    db.sequence = db.sequence + 1
    local event = {id=db.sourceID .. ":" .. db.sequence, sequence=db.sequence,
        schema=F.SCHEMA, sourceID=db.sourceID, character=F.identity.guid,
        characterName=F.identity.name, realm=F.identity.realm, time=F.Now(),
        session=F.session, episode=db.episode, kind=kind, data=F.Copy(data or {})}
    db.events[#db.events+1] = event
    return event
end

function F.Touch() F.lastActivity = F.Clock() end

function F.ObserveBalance(money, context)
    money = F.Number(money)
    if not money then return end
    local old = F.character.balance
    F.character.balance = money
    F.historyDirty=true
    if not F.baselined then
        F.baselined = true
        F.Emit("baseline", {balance=money, previous=old, gap=old and money-old or 0})
        return
    end
    if old == money then return end
    local e = F.Emit("balance", {before=old, after=money, delta=money-old, context=context})
    F.batch.balances[#F.batch.balances+1] = e
    F.Touch()
end

function F.Claim(category, amount, details, confidence)
    amount = F.Number(amount)
    if not amount then return end
    local data = F.Copy(details or {})
    data.category, data.amount, data.confidence = category, amount, confidence or "confirmed_event"
    local e = F.Emit("activity", data)
    F.batch.claims[#F.batch.claims+1] = e
    F.Touch()
    return e
end

-- An API call is intent, not proof that money moved. Only a unique amount match
-- upgrades an intent, and even that is labelled as correlation.
function F.Intent(category, amount, details)
    if not F.Number(amount) or amount == 0 then return end
    local e = F.Emit("intent", {category=category, amount=amount, details=details})
    F.intents[#F.intents+1] = {event=e, clock=F.Clock()}
    F.Touch()
    return e
end

function F.Flush()
    local b = F.batch
    if #b.balances == 0 and #b.claims == 0 then return end
    local observed, explained, balanceIDs, claimIDs = 0, 0, {}, {}
    for _, e in ipairs(b.balances) do observed=observed+e.data.delta; balanceIDs[#balanceIDs+1]=e.id end
    for _, e in ipairs(b.claims) do explained=explained+e.data.amount; claimIDs[#claimIDs+1]=e.id end
    local residual = observed-explained
    local matches = {}
    if residual ~= 0 then
        for _, i in ipairs(F.intents) do
            if not i.used and F.Clock()-i.clock < 15 and i.event.data.amount == residual then matches[#matches+1]=i end
        end
    end
    if #matches == 1 then
        local i = matches[1]
        local d = F.Copy(i.event.data.details or {})
        d.intentID = i.event.id
        local e = F.Claim(i.event.data.category, residual, d, "correlated_amount")
        claimIDs[#claimIDs+1] = e.id
        explained, residual, i.used = observed, 0, true
    elseif #matches == 0 and residual~=0 then
        local candidates,sum={},0
        for _, i in ipairs(F.intents) do
            if not i.used and F.Clock()-i.clock<15 then
                candidates[#candidates+1]=i; sum=sum+i.event.data.amount
            end
        end
        if #candidates>1 and sum==residual then
            for _, i in ipairs(candidates) do
                local d=F.Copy(i.event.data.details or {}); d.intentID=i.event.id
                local e=F.Claim(i.event.data.category,i.event.data.amount,d,"correlated_batch")
                claimIDs[#claimIDs+1]=e.id; i.used=true
            end
            explained,residual=observed,0
        end
    end
    -- Raw deltas remain authoritative even when the cause is unknown.
    F.Emit("reconciliation", {balanceIDs=balanceIDs, activityIDs=claimIDs,
        observed=observed, explained=explained, residual=residual,
        status=residual == 0 and "balanced" or "unresolved"})
    F.batch = {balances={}, claims={}}
    local keep = {}
    for _, i in ipairs(F.intents) do
        if not i.used and F.Clock()-i.clock < 15 then keep[#keep+1] = i end
    end
    F.intents = keep
end

function F.Snapshot(location, rows, complete, extra)
    rows=F.Copy(rows)
    if F.ValueRow then
        for _,row in ipairs(rows) do
            if row.item and (location=="bags" or location=="equipment" or location=="bank") then
                row.valuation=F.ValueRow(row,F.character,F.marketScope)
            end
        end
    end
    local d = {location=location, rows=rows, complete=complete, metadata=extra}
    local e = F.Emit("snapshot", d)
    F.character.snapshots[location] = {eventID=e.id, time=e.time, data=e.data}
    F.historyDirty=true
    return e
end

function F.AuctionKey(id) return F.identity.guid .. ":" .. tostring(id) end
function F.Posted(id, details)
    local key = F.AuctionKey(id)
    if F.db.auctions[key] then return end
    local d = F.Copy(details or {})
    d.auctionID, d.status, d.key = id, "active", key
    d.character, d.postedAt = F.identity.guid, F.Now()
    F.db.auctions[key] = d
    F.Emit("auction_posted", d)
    if d.deposit then F.Claim("auction_deposit", -d.deposit, {auctionKey=key, item=d.item}) end
end

function F.AuctionOutcome(key, outcome, confidence, evidenceID)
    local a = F.db.auctions[key]
    if not a or a.outcome then return false end
    a.outcome, a.status = outcome, outcome
    a.outcomeConfidence = confidence
    F.Emit("auction_outcome", {auctionKey=key, item=a.item, quantity=a.quantity,
        outcome=outcome, depositLost=(outcome=="expired" or outcome=="cancelled") and a.deposit or nil,
        confidence=confidence, evidenceID=evidenceID})
    return true
end

-- Mail does not expose an auction ID. A deterministic allocation is explicit,
-- never presented as a server-confirmed link. No match is better than a false one.
function F.MatchAuction(item, quantity, gross, refund, failure)
    local candidates = {}
    for key, a in pairs(F.db.auctions) do
        if a.character == F.identity.guid and (not a.outcome or (failure and a.outcome==failure and not a.returnMailRecorded)) and a.quantity == quantity
            and ((item.id and a.item and a.item.id == item.id) or
                (not item.id and a.item and a.item.name == item.name))
            and (not gross or a.totalPrice == gross)
            and (not refund or a.deposit == refund) then
            candidates[#candidates+1] = {key=key, data=a}
        end
    end
    table.sort(candidates, function(a,b)
        if failure and (a.data.outcome~=nil) ~= (b.data.outcome~=nil) then return a.data.outcome~=nil end
        if a.data.postedAt == b.data.postedAt then return a.key < b.key end
        return a.data.postedAt < b.data.postedAt
    end)
    if #candidates == 0 then return nil, "unmatched" end
    return candidates[1].key, #candidates == 1 and "inferred_unique" or "allocated_fifo"
end

function F.Invoice(mail)
    local d = F.Copy(mail)
    if d.invoiceType == "seller" then
        d.auctionKey, d.matchConfidence = F.MatchAuction(d.item, d.quantity, d.gross, d.depositRefund)
        local e = F.Emit("auction_sale", d)
        if d.auctionKey then F.AuctionOutcome(d.auctionKey,"sold",d.matchConfidence,e.id) end
        F.Claim("auction_sale", d.money, {saleID=e.id, item=d.item, gross=d.gross,
            commission=d.commission, depositRefund=d.depositRefund, quantity=d.quantity})
    elseif d.invoiceType == "buyer" then
        -- Purchase gold already left at the AH. This is cost-basis evidence only.
        F.Emit("auction_purchase_invoice", d)
    elseif d.failure then
        d.auctionKey, d.matchConfidence = F.MatchAuction(d.item, d.quantity,nil,nil,d.failure)
        local e = F.Emit("auction_return", d)
        if d.auctionKey then
            F.db.auctions[d.auctionKey].returnMailRecorded=true
            F.AuctionOutcome(d.auctionKey,d.failure,d.matchConfidence,e.id)
        end
    else
        F.Claim("mail_received", d.money or 0, d)
    end
end

function F.Export(first, count)
    first, count = math.max(1, first or 1), math.max(1, count or 200)
    local events = {}
    for i=first,math.min(#F.db.events,first+count-1) do events[#events+1]=F.db.events[i] end
    return F.JSON({format="forever-ledger", schema=F.SCHEMA, sourceID=F.db.sourceID,
        accountLabel=F.db.accountLabel, owners=F.db.owners, first=first,
        last=first+#events-1, total=#F.db.events, events=events})
end
