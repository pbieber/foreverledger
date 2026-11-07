"""Two copies of the actual addon, in separate Lua states, joined by a fake whisper bus."""
import json
import unittest
import test_ledger as base

FILES=("Core.lua","Collectors.lua","Disenchant.lua","Valuation.lua","Profit.lua","Prices.lua","Sync.lua","Highlights.lua","Chart.lua","UI.lua","Minimap.lua")
NOT_FOUND="No player named '%s' is currently playing."
EXTRA_MOCKS=r'''
SENT={}; POPUPS={}; SEND_RESULT=0
date=date or function(format,t) return os.date(format,t) end
C_ChatInfo={RegisterAddonMessagePrefix=function(p) PREFIX=p end,
    SendAddonMessage=function(prefix,text,kind,target)
        assert(kind=="WHISPER" and prefix=="FLedger" and #text<=255)
        if SEND_RESULT==0 then SENT[#SENT+1]={target,text} end
        return SEND_RESULT
    end}
StaticPopupDialogs={}
StaticPopup_Show=function(name,arg) POPUPS[#POPUPS+1]={name,arg} end
ERR_CHAT_PLAYER_NOT_FOUND_S="No player named '%s' is currently playing."
function FILTER_INSTALL(event,fn) FILTER=fn end
ChatFrame_AddMessageEventFilter=FILTER_INSTALL
'''


class Account:
    def __init__(self,name,guid,wallet,saved=None):
        # latin-1 keeps every byte, because a message part can split a UTF-8 character.
        self.lua=base.LuaRuntime(unpack_returned_tuples=True,encoding="latin-1")
        self.name=name
        self.lua.execute(base.MOCKS)
        self.lua.execute(EXTRA_MOCKS)
        self.realm=name.split("-",1)[1]
        self.lua.execute('function GetNormalizedRealmName() return "%s" end'%self.realm)
        self.lua.execute("F={}; WALLET=%d"%wallet)
        for file in FILES:
            code=(base.ROOT/"ForeverLedger"/file).read_bytes().decode("latin-1")
            self.lua.execute("assert(loadstring(...))('ForeverLedger',F)",code)
        self.guid=guid
        db=self.copy(saved) if saved is not None else self.lua.table()
        self.lua.execute('local db=...; F.Init(db, {guid="%s",name="%s",realm="%s",build="test"}); F.ObserveBalance(WALLET); F.RecordValue(true)'%(guid,name,self.realm),db)

    def copy(self,table):
        lua_type=__import__(base.LuaRuntime.__module__,fromlist=["lua_type"]).lua_type
        result=self.lua.table()
        for key,value in table.items():
            result[key]=self.copy(value) if lua_type(value)=="table" else value
        return result

    def relog(self,name):
        """The same account logging in again, as the named character, from what it saved."""
        wallet=self.run("return WALLET")
        return Account(name,self.guid,wallet,saved=self.run("return F.db"))

    def run(self,code):
        return self.lua.execute(code)

    def result(self,code):
        return json.loads(self.run("return F.JSON(%s)"%code))

    def messages(self):
        return self.result('(function() local o={} for i,m in ipairs(MESSAGES) do o[i]=tostring(m[1]) end return o end)()')

    def printed(self,text):
        return any(text in message for message in self.messages())

    def receive(self,sender,text):
        self.lua.globals().F.events.CHAT_MSG_ADDON("FLedger",text,"WHISPER",sender)


class Network:
    """Routes whispers like the client. A name without a realm means the sender's realm,
    except on Forever's hidden realms, where it finds that character on any of them."""
    def __init__(self,*accounts,hidden_realms=False,bare_senders=False):
        self.accounts=list(accounts)
        self.hidden_realms=hidden_realms
        self.bare_senders=bare_senders
        self.sent=[]
        self.hidden=[]
        # Lose one middle part of the next long message, choosing one whose loss still
        # leaves valid JSON, as the client sometimes does under load.
        self.lose_a_part=False
        self.holding={}

    def _lose_a_part(self,sender,target,text):
        """The parts to deliver now. Holds a long message's parts until its last one."""
        key=(sender.name,target)
        if not self.lose_a_part or (text[0]!="F" and key not in self.holding):
            return [text]
        parts=self.holding.setdefault(key,[])
        parts.append(text)
        if text[0]!="L":
            return []
        del self.holding[key]
        for i in range(1,len(parts)-1):
            body="".join(p[1:] for j,p in enumerate(parts) if j!=i)
            try:
                json.loads(body[body.index("{"):])
            except ValueError:
                continue
            self.lose_a_part=False
            return parts[:i]+parts[i+1:]
        return parts

    def find(self,name,sender=None):
        for account in self.accounts:
            if account.name.lower()==name.lower():
                return account
            if "-" not in name:
                if self.hidden_realms and account.name.split("-")[0].lower()==name.lower():
                    return account
                if sender and account.name.lower()==("%s-%s"%(name,sender.realm)).lower():
                    return account

    def sender_name(self,account):
        return account.name.split("-")[0] if self.bare_senders else account.name

    def step(self,seconds=1.2):
        for account in self.accounts:
            account.run("CLOCK=CLOCK+%f; NOW=NOW+%d; F.SyncTick()"%(seconds,round(seconds)))
        delivered=0
        for account in self.accounts:
            outgoing=[(m[1],m[2]) for m in account.lua.table_from(account.run("local s=SENT; SENT={}; return s")).values()]
            for target,sent in outgoing:
                delivered+=1
                for text in self._lose_a_part(account,target,sent):
                    self.sent.append((account.name,target,text))
                    other=self.find(target,account)
                    if other:
                        other.receive(self.sender_name(account),text)
                    else:
                        self.hidden.append(account.lua.globals().F.SyncHideNotFound(None,"CHAT_MSG_SYSTEM",NOT_FOUND%target))
        return delivered

    def settle(self,steps=400):
        quiet=0
        for _ in range(steps):
            quiet=0 if self.step() else quiet+1
            if quiet>=40:
                return
        raise AssertionError("Sync did not settle")


@unittest.skipIf(base.LuaRuntime is None,"Install lupa")
class SyncTests(unittest.TestCase):
    def setUp(self):
        self.main=Account("Main-Realm","Player-Main",100000)
        self.bank=Account("Bank-Realm","Player-Bank",200000)
        self.bank.run(r'''
        F.db.accountLabel="Bank"
        F.db.characters["Player-Alt"]={name="BankAlt-Realm",realm="Realm",class="MAGE",marketScope=F.marketScope,balance=500000,snapshots={}}
        F.market.catalog["2770:0"]={name="\195\156bererz",quality=1}
        F.RecordValue(true)
        F.db.characters["Player-Alt"].tops={{time=NOW,assets={{key="2770:0",value=900,quantity=3}},equipped={}}}
        ''')
        self.net=Network(self.main,self.bank)

    def link(self):
        self.main.run('F.SyncAdd("Bank")')
        self.net.step(); self.net.step()
        self.bank.run('StaticPopupDialogs.FOREVERLEDGER_SYNC_CONFIRM.OnAccept()')
        self.net.settle()

    def peer(self,account):
        return next(iter(account.lua.table_from(account.run("return F.db.peers")).values()))

    def chart_gold(self,account):
        return account.result('''(function()
            local points=F.StackHistory(F.ChartHistory(F.marketScope),{gold=true},F.marketScope,F.SelectedCharacters(),10,F.Now())
            return points[#points].totals.gold
        end)()''')

    def test_nothing_is_shared_before_the_second_account_confirms(self):
        self.main.run('F.SyncAdd("Bank")')
        self.net.step(); self.net.step()
        self.assertEqual(self.bank.result('POPUPS')[0],["FOREVERLEDGER_SYNC_CONFIRM","Main-Realm"])
        self.assertTrue(self.main.printed("Waiting for Bank-Realm to confirm"))
        for _ in range(30):
            self.net.step()
        self.assertEqual(self.main.result('F.db.peers'),{})
        self.assertEqual(self.bank.result('F.db.peers'),{})

    def test_decline_links_nothing_and_blocks_repeat_popups(self):
        self.main.run('F.SyncAdd("Bank")')
        self.net.step(); self.net.step()
        self.bank.run('StaticPopupDialogs.FOREVERLEDGER_SYNC_CONFIRM.OnCancel()')
        self.net.step(); self.net.step()
        self.assertTrue(self.main.printed("declined"))
        self.assertEqual(self.main.result('F.db.peers'),{})
        self.main.run('F.SyncAdd("Bank")')
        self.net.step(); self.net.step()
        self.assertEqual(len(self.bank.result('POPUPS')),1)

    def test_a_character_on_this_account_is_refused(self):
        self.assertFalse(self.main.run('return F.SyncAdd("main")'))
        self.assertEqual(self.net.step(),0)

    def progress(self,account):
        return account.result('(function() local source=next(F.db.peers); local f,t,d=F.SyncProgress(source); return {f=f,t=t,d=d or false} end)()')

    def test_progress_fills_pauses_resumes_and_reports_done(self):
        self.bank.run('for i=1,600 do NOW=NOW+60; F.character.balance=200000+i; F.RecordValue(true) end')
        self.main.run('F.SyncAdd("Bank")')
        self.net.step(); self.net.step()
        self.bank.run('StaticPopupDialogs.FOREVERLEDGER_SYNC_CONFIRM.OnAccept()')
        seen=[]
        for _ in range(25):
            self.net.step()
            seen.append(self.progress(self.main))
        fractions=[p["f"] for p in seen]
        self.assertTrue(any(p["t"].startswith("Syncing") and 0<p["f"]<1 for p in seen),seen[-3:])
        self.assertFalse(seen[-1]["d"])
        self.assertLess(fractions[-1],1)
        before=fractions[-1]
        self.net.accounts.remove(self.bank)
        self.main.run('F.SyncOffline("Bank-Realm")')
        self.assertEqual(self.progress(self.main)["t"],"Looking for Bank")
        for _ in range(15):
            self.net.step()
        self.assertTrue(self.main.printed("No reply from Bank"))
        paused=self.progress(self.main)
        self.assertTrue(paused["t"].startswith("Paused at"),paused)
        self.assertEqual(paused["f"],before)
        self.assertFalse(paused["d"])
        self.net.accounts.append(self.bank)
        self.main.run('F.SyncNow()')
        self.net.settle()
        done=self.progress(self.main)
        self.assertEqual(done,{"f":1,"t":"Complete","d":True})
        self.assertEqual(self.main.run('return F.syncStatus'),"Synced Bank: 2 characters.")

    def test_both_accounts_report_completion(self):
        self.link()
        self.assertEqual(self.progress(self.main)["t"],"Complete")
        self.assertEqual(self.progress(self.bank)["t"],"Complete")
        self.assertTrue(self.bank.printed("Synced Main-Realm"))

    def test_new_data_reopens_progress_then_completes_again(self):
        self.link()
        self.bank.run('for i=1,300 do NOW=NOW+60; F.character.balance=300000+i; F.RecordValue(true) end')
        self.net.step(31); self.net.step(); self.net.step()
        self.assertFalse(self.progress(self.main)["d"])
        self.net.settle()
        self.assertEqual(self.progress(self.main)["t"],"Complete")

    def test_progress_survives_a_reload_while_offline(self):
        self.bank.run('for i=1,600 do NOW=NOW+60; F.character.balance=200000+i; F.RecordValue(true) end')
        self.main.run('F.SyncAdd("Bank")')
        self.net.step(); self.net.step()
        self.bank.run('StaticPopupDialogs.FOREVERLEDGER_SYNC_CONFIRM.OnAccept()')
        for _ in range(25):
            self.net.step()
        before=self.progress(self.main)["f"]
        reloaded=Account("Main-Realm","Player-Main",100000)
        reloaded.run('function rows() end')
        peers=self.main.run('return F.JSON(F.db.peers)')
        reloaded.lua.globals().PEERS=peers
        reloaded.run('F.db.peers=F.ParseJSON(PEERS)')
        after=self.progress(reloaded)
        self.assertTrue(after["t"].startswith("Paused at"),after)
        self.assertAlmostEqual(after["f"],before)

    def stocked(self):
        self.bank.run('''
        ORE={name="Ore",classID=7,subclassID=7}
        F.db.characters["Player-Alt"].stock=nil; F.character.stock=nil
        F.RememberStock(F.db.characters["Player-Alt"],NOW-100000,{Mining=500})
        F.RememberStock(F.character,NOW-100000,{Herbs=40})
        NOW=NOW+10
        ''')

    def linked_profit(self,account,since=0,code='F.SelectedCharacters()'):
        return account.result('''(function()
            local list,total,linked=F.CategoryProfit(%s,%s)
            local out={total=total,linked=linked}
            for _,r in ipairs(list) do out[r.category]=r end
            return out
        end)()'''%(code,since))

    def test_profit_view_adds_the_linked_accounts_characters(self):
        self.stocked()
        self.bank.run('''
        F.Claim("auction_sale",900,{item=ORE})
        F.db.events[#F.db.events].character="Player-Alt"
        F.Claim("vendor_purchase",-200,{item=ORE})
        F.db.events[#F.db.events].character="Player-Alt"
        F.Claim("vendor_sale",70,{item={name="Weed",classID=7,subclassID=9}})
        F.RememberStock(F.db.characters["Player-Alt"],NOW,{Mining=650})
        ''')
        self.main.run('F.ObserveBalance(WALLET); F.Claim("vendor_sale",11,{item=F.Item(nil,1,"X")}); F.db.events[#F.db.events].data.item={classID=7,subclassID=7}')
        self.link()
        got=self.linked_profit(self.main)
        mining=got["Mining"]
        self.assertEqual((mining["sold"],mining["spent"],mining["held"],mining["change"]),(911,-200,650,150))
        self.assertEqual(mining["profit"],861)
        self.assertEqual((got["Herbs"]["sold"],got["Herbs"]["held"]),(70,40))
        self.assertTrue(got["linked"]["at"])
        self.assertNotIn("missing",got["linked"])

    def test_on_sale_includes_the_linked_accounts_listings(self):
        self.bank.run("""
        F.db.characters["Player-Alt"].snapshots.auctions={data={rows={
            {status=0,quantity=2,totalBuyout=40000,item={id=9,vendorPrice=1000}},
            {status=1,quantity=2,totalBuyout=99999,item={id=9,vendorPrice=1000}}}}}
        """)
        self.link()
        self.assertEqual(self.main.result('F.OnSale({["Player-Alt"]=true})'),
            {"count":1,"total":40000,"deposit":1200,"estimated":1,"cut":2000})
        self.assertEqual(self.main.result('F.OnSale({["Player-Main"]=true})')["total"],0)

    def test_linked_figures_follow_this_accounts_period_and_selection(self):
        self.stocked()
        self.bank.run('''
        F.Claim("vendor_sale",100,{item=ORE}); F.db.events[#F.db.events].character="Player-Alt"; F.db.events[#F.db.events].time=NOW-90000
        table.insert(F.db.events,1,table.remove(F.db.events))
        F.Claim("vendor_sale",40,{item=ORE}); F.db.events[#F.db.events].character="Player-Alt"
        F.RememberStock(F.db.characters["Player-Alt"],NOW,{Mining=510})
        ''')
        self.link()
        since=self.main.run('return F.GainStart(F.Now())')
        today=self.linked_profit(self.main,since)["Mining"]
        self.assertEqual((today["sold"],today["change"],today["held"]),(40,10,510))
        always=self.linked_profit(self.main,0)["Mining"]
        self.assertEqual((always["sold"],always["change"],always["held"]),(140,10,510))
        self.assertNotIn("Mining",self.linked_profit(self.main,0,'{["Player-Main"]=true}'))
        self.assertEqual(self.linked_profit(self.main,0,'{["Player-Alt"]=true}')["Mining"]["sold"],140)

    def test_a_category_sold_out_during_the_period_still_shows_its_drop(self):
        self.bank.run('''
        F.character.stock=nil
        F.RememberStock(F.character,NOW-1000,{Mining=10})
        F.RememberStock(F.character,NOW-500,{Mining=10,Herbs=90})
        F.RememberStock(F.character,NOW,{Mining=10})
        ''')
        self.link()
        since=self.main.run('return NOW')-600
        self.main.run('F.GainStart=function() return %d end; F.SyncRefreshProfit()'%since)
        self.net.settle()
        self.assertEqual(self.linked_profit(self.main,since).get("Herbs",{}).get("change"),None)
        since=self.main.run('return NOW')
        self.bank.run('F.RememberStock(F.character,NOW,{Mining=10,Herbs=90})')
        self.bank.run('F.RememberStock(F.character,NOW+1,{Mining=10})')
        self.net.step(); self.net.step()
        self.main.run('F.GainStart=function() return %d end; F.SyncRefreshProfit()'%since)
        self.net.settle()
        herbs=self.linked_profit(self.main,since).get("Herbs")
        self.assertEqual(herbs["change"],-90)
        self.assertEqual(herbs["held"],0)

    def test_stale_period_is_flagged_and_refreshed_when_the_account_returns(self):
        self.stocked()
        self.bank.run('F.Claim("vendor_sale",40,{item=ORE}); F.db.events[#F.db.events].character="Player-Alt"')
        self.link()
        self.net.accounts.remove(self.bank)
        self.main.run('F.SyncOffline("Bank-Realm")')
        self.main.run('NOW=NOW+100; F.SetMarker("Run")')
        since=self.main.run('return F.GainStart(F.Now())')
        stale=self.linked_profit(self.main,since)
        self.assertTrue(stale["linked"]["missing"])
        self.assertEqual((stale["Mining"]["sold"],stale["Mining"]["held"]),(0,500))
        self.assertEqual(self.linked_profit(self.main,0)["Mining"]["sold"],40)
        self.assertNotIn("missing",self.linked_profit(self.main,0)["linked"])
        self.net.accounts.append(self.bank)
        self.main.run('F.SyncNow()')
        self.net.settle()
        self.main.run('F.SyncRefreshProfit()')
        self.net.settle()
        self.assertNotIn("missing",self.linked_profit(self.main,since)["linked"])

    def pulls(self):
        return [t for _,_,t in self.net.sent if '"w":"profit"' in t]

    def test_figures_refresh_on_a_timer_unless_the_view_is_open(self):
        self.link()
        first=len(self.pulls())
        self.assertGreaterEqual(first,1)
        def change(amount):
            self.bank.run('F.character.balance=%d; F.RecordValue(true)'%amount)
            self.net.step(31); self.net.step(); self.net.settle()
        change(777)
        self.assertEqual(len(self.pulls()),first)
        self.main.run('F.window={IsShown=function() return true end}; F.mode="profit"; F.RefreshProfit=function() end; F.RefreshChart=function() end')
        change(888)
        self.assertEqual(len(self.pulls()),first+1)
        self.main.run('F.mode="overview"')
        for _ in range(10):
            self.net.step(31)
        change(999)
        self.assertEqual(len(self.pulls()),first+2)

    def test_opening_the_view_refreshes_without_new_history(self):
        self.link()
        first=len(self.pulls())
        self.main.run('F.SyncRefreshProfit()')
        self.net.settle()
        self.assertEqual(len(self.pulls()),first+1)

    def test_a_copy_without_the_feature_is_never_asked(self):
        self.link()
        first=len(self.pulls())
        peer=self.main.result('(function() local s,p=next(F.db.peers); return {s=s,k=p.key} end)()')
        hello=json.dumps({"t":"hello","s":peer["s"],"k":peer["k"],"n":self.bank.run('return #F.db.history'),
            "c":self.bank.run('return select(2,0,0)') or 0,"r":1},separators=(",",":"))
        self.main.receive("Bank-Realm","S"+hello)
        self.main.run('F.SyncRefreshProfit()')
        self.net.settle()
        self.assertEqual(len(self.pulls()),first)

    def test_received_figures_are_checked(self):
        self.link()
        peer=self.main.result('(function() local s,p=next(F.db.peers); return {s=s,k=p.key} end)()')
        def send(key,rows):
            self.main.receive("Bank-Realm","S"+json.dumps({"t":"profit","s":peer["s"],"k":key,"f":0,"at":123,"c":rows},separators=(",",":")))
        send("wrong",{"Player-Alt":{"Mining":[1,2,3,4,5,6,7]}})
        self.assertNotEqual(self.main.run('local _,p=next(F.db.peers); return p.profit.at'),123)
        send(peer["k"],{"Player-Main":{"Mining":[9,9,9,9,9,9,9]},"Player-Unknown":{"Mining":[9,9,9,9,9,9,9]},
            "Player-Alt":{"Mining":["x",None,3,"y",5,6,7],"|cffbad":[1,0,0,0,0,0,0]},"Player-Bank":"nope"})
        rows=self.main.result('(function() local _,p=next(F.db.peers); return p.profit.rows end)()')
        self.assertEqual(set(rows),{"Player-Alt"})
        self.assertEqual(rows["Player-Alt"]["Mining"],[0,0,3,0,5,6,7])
        self.assertIn("cffbad",rows["Player-Alt"])

    def test_figures_stay_out_of_exports_and_go_on_unlink(self):
        self.stocked()
        self.link()
        self.assertTrue(self.main.run('local _,p=next(F.db.peers); return p.profit~=nil'))
        self.assertNotIn('"profit"',self.main.run('return F.Export(1,100000)'))
        self.main.run('F.SyncUnlink(next(F.db.peers))')
        self.net.settle()
        got=self.linked_profit(self.main)
        self.assertEqual(got["total"]["held"],0)
        self.assertEqual(got["linked"],{})

    def test_fetching_figures_does_not_reopen_a_finished_bar(self):
        self.link()
        self.main.run('F.SyncRefreshProfit()')
        self.assertEqual(self.progress(self.main)["t"],"Complete")
        self.net.settle()
        self.assertEqual(self.progress(self.main)["t"],"Complete")

    def test_whole_account_syncs_both_ways_after_confirmation(self):
        self.link()
        names=[c["name"] for c in self.main.result('F.ChartCharacterList()')]
        self.assertEqual(names,["Bank-Realm","BankAlt-Realm","Main-Realm"])
        self.assertEqual([c["name"] for c in self.bank.result('F.ChartCharacterList()')],["Bank-Realm","BankAlt-Realm","Main-Realm"])
        self.assertEqual(self.chart_gold(self.main),800000)
        self.assertEqual(self.chart_gold(self.bank),800000)
        self.assertTrue(self.main.printed("Synced Bank: 2 characters."))
        self.assertEqual(self.main.run('return next(F.db.peers) and F.db.peers[next(F.db.peers)].label'),"Bank")

    def test_item_breakdown_keeps_names_across_message_parts(self):
        self.link()
        rows=self.main.result('''(function()
            local h=F.ChartHistory(F.marketScope); local last=h[#h]
            return F.BreakdownRows({raw=last,time=F.Now()},"assets",{["Player-Alt"]=true})
        end)()''')
        self.assertEqual(rows[0]["value"],900)
        self.assertIn("Ã\u009cbererz",rows[0]["label"])

    def test_synced_characters_stay_out_of_local_records(self):
        self.link()
        self.main.run('F.RecordValue(true)')
        export=json.loads(self.main.run('return F.Export(1,100000)'))
        valuation=[e for e in export["events"] if e["kind"]=="valuation"][-1]["data"]
        self.assertEqual(valuation["gold"],100000)
        self.assertEqual(sorted(valuation["characters"]),["Player-Main"])
        self.assertEqual({e["sourceID"] for e in export["events"]},{self.main.run('return F.db.sourceID')})
        self.assertNotIn("Player-Alt",self.main.result('F.db.characters'))

    def test_linking_marks_every_character_as_owned_for_the_database(self):
        self.link()
        export=json.loads(self.main.run('return F.Export(1,100000)'))
        self.assertEqual(sorted(export["owners"]),["Bank-Realm","BankAlt-Realm","Main-Realm"])
        self.assertEqual(sorted(e["data"]["name"] for e in export["events"] if e["kind"]=="owner"),["Bank-Realm","BankAlt-Realm"])
        self.assertEqual(len([e for e in export["events"] if e["kind"]=="sync_linked"]),1)

    def test_strangers_get_nothing_and_change_nothing(self):
        self.link()
        source=self.bank.run('return F.db.sourceID')
        for text in ('{"t":"pull","w":"index","s":"%s","k":"guess"}'%source,'{"t":"pull","w":"index","s":"%s"}'%source,
                     '{"t":"hist","f":1,"n":1,"s":"%s","k":"guess","g":["X"],"m":["s"],"r":[[1,1,0,[1,9,9,9]]]}'%source,
                     '{"t":"linked","s":"evil","k":"x"}','{"t":"asked"}','{"t":"unlink","s":"%s"}'%source,'not json','S','{"t":"unknown"}'):
            self.main.receive("Stranger-Realm","S"+text)
        self.assertEqual(self.main.result('SENT'),{})
        self.assertEqual(len(self.main.result('(next(F.db.peers) and F.db.peers[next(F.db.peers)].history)')),2)
        self.assertEqual(len(self.main.result('(function() local n={} for k in pairs(F.db.peers) do n[#n+1]=k end return n end)()')),1)

    def test_a_large_message_from_a_stranger_is_dropped(self):
        self.main.receive("Stranger-Realm","F"+"x"*254)
        for _ in range(10):
            self.main.receive("Stranger-Realm","M"+"x"*254)
        self.assertEqual(self.main.lua.globals().F.events.CHAT_MSG_ADDON("FLedger","L}","WHISPER","Stranger-Realm"),None)
        self.assertEqual(self.main.result('POPUPS'),{})

    def test_other_prefixes_and_channels_are_ignored(self):
        events=self.main.lua.globals().F.events
        link='S{"t":"link","s":"x","v":1}'
        events.CHAT_MSG_ADDON("OtherAddon",link,"WHISPER","Bank-Realm")
        events.CHAT_MSG_ADDON("FLedger",link,"GUILD","Bank-Realm")
        self.assertEqual(self.main.result('POPUPS'),{})

    def test_large_history_is_split_paced_and_fully_transferred(self):
        self.bank.run('''
        for i=1,300 do
            NOW=NOW+60; F.character.balance=200000+i
            if i%50==0 then F.db.characters["Player-Alt"].balance=500000+i end
            F.RecordValue(true)
        end
        ''')
        total=self.bank.run('return #F.db.history')
        self.link()
        self.assertEqual(self.main.run('local _,p=next(F.db.peers); return #p.history'),total)
        self.assertEqual(self.chart_gold(self.main),100000+200300+500300)
        pulls=[m for m in self.net.sent if m[0]=="Bank-Realm"]
        self.assertTrue(all(len(m[2].encode("latin-1"))<=255 for m in pulls))
        per_sample=sum(len(m[2]) for m in pulls)/total
        self.assertLess(per_sample,80)

    def test_sending_stays_within_the_budget(self):
        self.main.run('for i=1,100 do F.SyncAdd("Bank") end')
        counts=[]
        for _ in range(10):
            counts.append(self.net.step())
        self.assertLessEqual(counts[0],8)
        self.assertTrue(all(count<=2 for count in counts[1:]))

    def test_interrupted_transfer_resumes_from_what_was_stored(self):
        self.bank.run('for i=1,600 do NOW=NOW+60; F.character.balance=200000+i; F.RecordValue(true) end')
        total=self.bank.run('return #F.db.history')
        self.main.run('F.SyncAdd("Bank")')
        self.net.step(); self.net.step()
        self.bank.run('StaticPopupDialogs.FOREVERLEDGER_SYNC_CONFIRM.OnAccept()')
        for _ in range(30):
            self.net.step()
        stored=self.main.run('local _,p=next(F.db.peers); return #p.history')
        self.assertGreater(stored,0)
        self.assertLess(stored,total)
        self.net.accounts.remove(self.bank)
        for _ in range(250):
            self.net.step()
        self.assertEqual(self.main.run('local _,p=next(F.db.peers); return #p.history'),stored)
        self.net.accounts.append(self.bank)
        self.net.sent.clear()
        self.bank.run('F.InstallSync()')
        self.net.settle()
        self.assertEqual(self.main.run('local _,p=next(F.db.peers); return #p.history'),total)
        first=next(json.loads(m[2][1:]) for m in self.net.sent if m[0]=="Main-Realm" and '"w":"hist"' in m[2])
        self.assertGreater(first["f"],stored)
        self.assertEqual(self.chart_gold(self.main),100000+200600+500000)

    def test_another_character_on_the_linked_account_is_recognized(self):
        self.link()
        self.net.accounts.remove(self.bank)
        self.bank.name="BankNew-Realm"
        self.net.accounts.append(self.bank)
        self.bank.run('F.InstallSync()')
        self.net.settle()
        self.assertEqual(self.main.run('local _,p=next(F.db.peers); return p.lastName'),"BankNew-Realm")
        self.assertIs(self.main.run('return F.db.owners["BankNew-Realm"]'),True)

    def test_finding_the_other_account_tries_all_its_characters_quietly(self):
        self.link()
        self.bank.name="BankAlt-Realm"
        self.net.hidden.clear()
        self.main.run('F.SyncNow()')
        self.net.settle()
        self.assertTrue(self.net.hidden and all(self.net.hidden))
        self.assertEqual(self.main.run('local _,p=next(F.db.peers); return p.lastName'),"BankAlt-Realm")
        self.assertTrue(self.main.printed("Synced Bank"))

    def test_no_reply_is_reported(self):
        self.link()
        self.net.accounts.remove(self.bank)
        self.net.step(); self.net.step()
        self.main.run('F.SyncNow()')
        for _ in range(30):
            self.net.step()
        self.assertTrue(self.main.printed("No reply from Bank"))

    def test_unrelated_not_found_messages_stay_visible(self):
        filter_=self.main.lua.globals().F.SyncHideNotFound
        self.assertFalse(filter_(None,"CHAT_MSG_SYSTEM",NOT_FOUND%"Friend-Realm"))
        self.assertFalse(filter_(None,"CHAT_MSG_SYSTEM","Some other system message"))

    def test_unreachable_request_is_reported(self):
        self.main.run('F.SyncAdd("Nobody")')
        self.net.step()
        self.assertTrue(self.net.hidden[0])
        self.assertTrue(self.main.printed("Nobody is not online"))

    def test_silent_target_times_out(self):
        self.net.accounts.remove(self.bank)
        self.main.run('F.SyncAdd("Bank")')
        self.main.run('C_ChatInfo.SendAddonMessage=function() return 0 end')
        for _ in range(25):
            self.net.step()
        self.assertTrue(self.main.printed("No reply from Bank."))

    def test_throttled_message_is_retried_and_offline_result_handled(self):
        self.main.run('SEND_RESULT=3; F.SyncAdd("Bank")')
        self.net.step()
        self.assertEqual(self.bank.result('POPUPS'),{})
        self.main.run('SEND_RESULT=0')
        self.net.step(); self.net.step()
        self.assertEqual(len(self.bank.result('POPUPS')),1)
        other=Account("Solo-Realm","Player-Solo",1)
        other.run('SEND_RESULT=12; F.SyncAdd("Bank"); CLOCK=CLOCK+1; F.SyncTick()')
        self.assertTrue(other.printed("Bank is not online"))

    def test_changes_reach_a_connected_account_without_a_new_link(self):
        self.link()
        self.bank.run('NOW=NOW+10; F.character.balance=250000; F.RecordValue(true)')
        for _ in range(60):
            self.net.step()
        self.assertEqual(self.chart_gold(self.main),850000)
        self.assertEqual(self.main.run('local _,p=next(F.db.peers); return p.characters["Player-Bank"].balance'),250000)

    def test_restored_backup_is_fetched_again(self):
        self.bank.run('for i=1,5 do NOW=NOW+60; F.character.balance=200000+i; F.RecordValue(true) end')
        self.link()
        self.bank.run('''
        for i=#F.db.history,3,-1 do F.db.history[i]=nil end
        F.character.balance=300000; NOW=NOW+60; F.RecordValue(true)
        F.InstallSync()
        ''')
        self.net.settle()
        self.assertEqual(self.main.run('local _,p=next(F.db.peers); return #p.history'),self.bank.run('return #F.db.history'))
        self.assertEqual(self.chart_gold(self.main),100000+300000+500000)

    def history_times(self,account,peer=False):
        code='local _,p=next(F.db.peers); return p.history' if peer else 'return F.db.history'
        return [h["time"] for h in account.lua.table_from(account.run(code)).values()]

    def test_a_long_message_missing_a_part_is_refused_and_fetched_again(self):
        self.link()
        self.net.lose_a_part=True
        self.bank.run('for i=1,60 do NOW=NOW+61; F.character.balance=200000+i*7919; F.RecordValue(true) end')
        self.net.settle(2000)
        self.assertFalse(self.net.lose_a_part,"no part was lost")
        self.assertEqual(self.history_times(self.main,peer=True),self.history_times(self.bank))

    def test_history_synced_by_an_earlier_version_is_fetched_again_once(self):
        self.bank.run('for i=1,5 do NOW=NOW+60; F.character.balance=200000+i; F.RecordValue(true) end')
        self.link()
        self.main.run('local _,p=next(F.db.peers); p.history[3].time=p.history[3].time*10+5; F.db.peerHistoryRefetched=nil')
        main=self.main.relog("Main-Realm")
        main.run('F.InstallSync()')
        net=Network(main,self.bank)
        net.settle()
        self.assertEqual(self.history_times(main,peer=True),self.history_times(self.bank))
        main.run('local _,p=next(F.db.peers); p.history[1].time=1')
        again=main.relog("Main-Realm")
        self.assertEqual(again.run('local _,p=next(F.db.peers); return p.history[1].time'),1)

    def test_later_samples_hold_earlier_values_of_unchanged_characters(self):
        self.bank.run('NOW=NOW+60; F.character.balance=210000; F.RecordValue(true)')
        self.link()
        last=self.main.result('''(function()
            local _,p=next(F.db.peers); return p.history[#p.history].chars
        end)()''')
        self.assertEqual(sorted(last),["Player-Bank"])
        merged=self.main.result('(function() local h=F.ChartHistory(F.marketScope); return h[#h].chars end)()')
        self.assertEqual(merged["Player-Alt"]["gold"],500000)
        self.assertEqual(merged["Player-Main"]["gold"],100000)

    def test_gain_counts_synced_characters(self):
        self.link()
        self.bank.run('NOW=NOW+10; F.character.balance=260000; F.RecordValue(true)')
        for _ in range(60):
            self.net.step()
        gain=self.main.run('return F.GoldGain(F.SelectedCharacters(),F.Now())')
        self.assertEqual(gain,60000)

    def test_other_scopes_sync_but_stay_off_this_chart(self):
        self.bank.run('''
        F.db.characters["Player-Far"]={name="Far-Other",realm="Other",marketScope="forever:Other:unknown",balance=7,snapshots={}}
        ''')
        self.link()
        self.assertNotIn("Far-Other",[c["name"] for c in self.main.result('F.ChartCharacterList()')])
        self.assertEqual(self.chart_gold(self.main),800000)
        self.assertTrue(any("Far-Other" in line for line in self.main.run('return F.Summary()').split("\n")))

    def test_summary_lists_the_linked_account_and_a_combined_total(self):
        self.link()
        summary=self.main.run('return F.Summary()')
        self.assertIn("Linked account: Bank",summary)
        self.assertIn("BankAlt-Realm",summary)
        self.assertIn("All accounts total: 80|T",summary)

    def test_unlink_removes_synced_data_on_both_accounts(self):
        self.link()
        self.main.run('local source=next(F.db.peers); F.SyncUnlink(source)')
        self.assertEqual(self.main.result('F.db.peers'),{})
        self.assertEqual(self.chart_gold(self.main),100000)
        for _ in range(5):
            self.net.step()
        self.assertEqual(self.bank.result('F.db.peers'),{})
        self.assertTrue(self.bank.printed("unlinked this account"))
        self.assertEqual(len([e for e in json.loads(self.main.run('return F.Export(1,100000)'))["events"] if e["kind"]=="sync_unlinked"]),1)

    def test_a_key_from_an_old_link_is_refused_after_relinking(self):
        self.link()
        old=self.main.run('local _,p=next(F.db.peers); return p.key')
        self.main.run('F.SyncUnlink(next(F.db.peers))')
        for _ in range(5):
            self.net.step()
        self.link()
        self.assertNotEqual(self.main.run('local _,p=next(F.db.peers); return p.key'),old)

    def test_commands_and_install_register_the_prefix(self):
        self.main.run('F.InstallSync()')
        self.assertEqual(self.main.run('return PREFIX'),"FLedger")
        self.assertIsNotNone(self.main.run('return FILTER'))
        self.main.run('F.Command("sync add Bank")')
        self.net.step(); self.net.step()
        self.assertEqual(len(self.bank.result('POPUPS')),1)
        self.main.run('F.Command("sync now")')
        self.assertTrue(self.main.printed("No linked account yet"))
        self.main.run('F.Command("sync add")')
        self.assertEqual(self.main.result('POPUPS')[-1][0],"FOREVERLEDGER_SYNC_ADD")

    def test_add_popup_passes_the_name_on(self):
        self.main.run('''
        F.PromptSyncAdd()
        StaticPopupDialogs.FOREVERLEDGER_SYNC_ADD.OnAccept({GetEditBox=function() return {GetText=function() return " Bank " end} end})
        ''')
        self.net.step(); self.net.step()
        self.assertEqual(self.bank.result('POPUPS')[0][1],"Main-Realm")

    def test_parse_json_round_trips_and_rejects_everything_else(self):
        self.assertEqual(self.main.run(r'''
        local input={a=1,b={1,2,{c="x\"y\\z\n\195\156"}},d=true,e=false,f=-5,g=1.5,h={}}
        return F.JSON(input)==F.JSON(F.ParseJSON(F.JSON(input)))
        '''),True)
        for bad in ('nope','{"a":1','[1,]','{"a"}','{a:1}','"open','1 2','os.exit()','[[[[[[[[[[1]]]]]]]]]]','"\\q"','{"a":1}}','-'):
            self.assertIsNone(self.main.lua.globals().F.ParseJSON(bad),bad)


@unittest.skipIf(base.LuaRuntime is None,"Install lupa")
class HiddenRealmTests(unittest.TestCase):
    """Forever puts each account on its own hidden realm behind the same visible realm."""
    def accounts(self,bare_senders):
        main=Account("Sare-CAMWOWEU5Realm6PvP","Player-Sare",100000)
        bank=Account("Modars-CAMWOWEU5Realm2PvP","Player-Modars",200000)
        bank.run('F.db.accountLabel="Bank"')
        return main,bank,Network(main,bank,hidden_realms=True,bare_senders=bare_senders)

    def link_and_check(self,bare_senders):
        main,bank,net=self.accounts(bare_senders)
        main.run('F.SyncAdd("Modars")')
        net.step(); net.step()
        self.assertEqual(len(bank.result('POPUPS')),1)
        bank.run('StaticPopupDialogs.FOREVERLEDGER_SYNC_CONFIRM.OnAccept()')
        net.settle()
        self.assertFalse(main.printed("not online"))
        self.assertTrue(main.printed("Synced Bank"))
        self.assertTrue(bank.printed("Synced"))
        self.assertEqual(main.result('(function() local _,p=next(F.db.peers); local o={} for _,c in pairs(p.characters) do o[#o+1]=c.name end return o end)()'),
            ["Modars-CAMWOWEU5Realm2PvP"])
        # The next session finds the account again without a new link.
        main.run('F.SyncNow()')
        net.settle()
        self.assertEqual(main.result('(function() local _,p=next(F.db.peers); return p.lastSync and true end)()'),True)
        return main,bank

    def test_a_name_without_realm_reaches_a_character_on_another_hidden_realm(self):
        main,_=self.link_and_check(bare_senders=False)
        self.assertEqual(main.run('local _,p=next(F.db.peers); return p.lastName'),"Modars-CAMWOWEU5Realm2PvP")

    def test_replies_without_a_realm_are_not_given_this_characters_realm(self):
        main,_=self.link_and_check(bare_senders=True)
        self.assertEqual(main.run('local _,p=next(F.db.peers); return p.lastName'),"Modars")

    def test_the_other_hidden_realm_shares_this_chart(self):
        main,_=self.link_and_check(bare_senders=False)
        self.assertEqual(sorted(c["name"] for c in main.result('F.ChartCharacterList()')),
            ["Modars-CAMWOWEU5Realm2PvP","Sare-CAMWOWEU5Realm6PvP"])
        gold=main.result('''(function()
            local points=F.StackHistory(F.ChartHistory(F.marketScope),{gold=true},F.marketScope,F.SelectedCharacters(),10,F.Now())
            return points[#points].totals.gold
        end)()''')
        self.assertEqual(gold,300000)

    def test_chart_scope_joins_only_numbered_forever_realms(self):
        main,_,_=self.accounts(False)
        same=lambda a,b: main.lua.globals().F.SameChart(a,b)
        self.assertTrue(same("forever:CAMWOWEU5Realm6PvP:Horde","forever:CAMWOWEU5Realm2PvP:Horde"))
        self.assertFalse(same("forever:CAMWOWEU5Realm6PvP:Horde","forever:CAMWOWEU5Realm2PvP:Alliance"))
        self.assertFalse(same("forever:CAMWOWEU5Realm6PvP:Horde","forever:CAMWOWEU4Realm6PvP:Horde"))
        self.assertFalse(same("tbc:Spineshatter:Horde","tbc:Thunderstrike:Horde"))
        self.assertFalse(same("forever:Realm:Horde",None))

    def peer_names(self,account):
        return sorted(account.lua.table_from(account.run("local _,p=next(F.db.peers); return p.names")).keys())

    def test_both_accounts_find_each_other_after_a_restart_moves_their_realms(self):
        main,bank=self.link_and_check(bare_senders=False)
        main,bank=main.relog("Sare-CAMWOWEU5Realm3PvP"),bank.relog("Modars-CAMWOWEU5Realm5PvP")
        net=Network(main,bank,hidden_realms=True)
        for account in (main,bank):
            account.run("F.InstallSync()")
        net.settle()
        self.assertEqual(main.run('local _,p=next(F.db.peers); return p.lastName'),"Modars-CAMWOWEU5Realm5PvP")
        self.assertEqual(bank.run('local _,p=next(F.db.peers); return p.lastName'),"Sare-CAMWOWEU5Realm3PvP")
        self.assertEqual(self.peer_names(main),["Modars-CAMWOWEU5Realm5PvP"])
        self.assertEqual(sorted(c["name"] for c in main.result('F.ChartCharacterList()')),
            ["Modars-CAMWOWEU5Realm5PvP","Sare-CAMWOWEU5Realm3PvP"])

    def test_a_realm_change_mid_session_is_followed(self):
        main,bank,net=self.accounts(False)
        main.run('F.SyncAdd("Modars")'); net.step(); net.step()
        bank.run('StaticPopupDialogs.FOREVERLEDGER_SYNC_CONFIRM.OnAccept()'); net.settle()
        bank.name="Modars-CAMWOWEU5Realm5PvP"
        main.run('NOW=NOW+10; F.character.balance=150000; F.RecordValue(true)')
        net.settle()
        self.assertEqual(main.run('local _,p=next(F.db.peers); return p.lastName'),"Modars-CAMWOWEU5Realm5PvP")
        self.assertEqual(bank.result('(function() local _,p=next(F.db.peers); for _,c in pairs(p.characters) do return c.balance end end)()'),150000)

    def test_a_name_with_its_forever_surname_is_matched(self):
        main,bank,net=self.accounts(False)
        net.find=lambda name,sender=None: bank if name=="Modars Setharius" else main if name.startswith("Sare") else None
        main.run('F.SyncAdd("Modars Setharius")')
        net.step(); net.step()
        bank.run('StaticPopupDialogs.FOREVERLEDGER_SYNC_CONFIRM.OnAccept()')
        net.step(); net.step()
        self.assertTrue(main.printed("Linked with Modars-CAMWOWEU5Realm2PvP"))

    def test_own_character_is_still_refused_without_its_realm(self):
        main,_,_=self.accounts(False)
        self.assertFalse(main.run('return F.SyncAdd("sare")'))


if __name__=="__main__":
    unittest.main()
