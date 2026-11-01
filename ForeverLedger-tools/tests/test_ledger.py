"""Run: python -m unittest discover -s tests -v (install lupa for Lua 5.1 tests)."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

try:
    from lupa.lua51 import LuaRuntime
except ImportError:
    LuaRuntime = None

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location("ledger",ROOT/"ForeverLedger-tools"/"ledger.py")
ledger=importlib.util.module_from_spec(spec)
spec.loader.exec_module(ledger)

MOCKS=r'''
NOW=1800000000; CLOCK=0; WALLET=100000; BAGS={}; INBOX={}; HOOKS={}; MESSAGES={}
function GetServerTime() return NOW end
function time() return NOW end
function GetTime() return CLOCK end
function GetMoney() return WALLET end
function GetNormalizedRealmName() return "Realm" end
function UnitGUID() return "Player-Main" end
function UnitFullName() return "Main","Realm" end
function GetBuildInfo() return "1.60.1","70450" end
function GetZoneText() return "Elwynn" end
function GetSubZoneText() return "Goldshire" end
function GetUnitName() return "Bank-Realm" end
function GetInventoryItemLink() return nil end
function issecretvalue() return false end
function print(...) MESSAGES[#MESSAGES+1]={...} end
function hooksecurefunc(a,b,c)
    local target,name,callback
    if type(a)=="string" then target,name,callback=_G,a,b else target,name,callback=a,b,c end
    local original=target[name]
    target[name]=function(...)
        local result={original(...)}
        callback(...)
        return unpack(result)
    end
end
local function noop() end
function CreateFrame()
    local f={scripts={},registered={}}
    function f:RegisterEvent(e) self.registered[e]=true end
    function f:SetScript(e,fn) self.scripts[e]=fn end
    LAST_FRAME=f
    return f
end
UISpecialFrames={}; SlashCmdList={}
NUM_TOTAL_EQUIPPED_BAG_SLOTS=4
C_Container={
 GetContainerNumSlots=function(bag) return #(BAGS[bag] or {}) end,
 GetContainerItemInfo=function(bag,slot) return (BAGS[bag] or {})[slot] end,
 UseContainerItem=noop,
}
C_Item={GetItemInfo=function(link)
    return "Copper Ore",link,1,1,1,"Trade Goods","Metal",20,"",1,50
end, GetItemLink=function(loc) return loc.link end}
C_AuctionHouse={
 PostItem=noop,ConfirmPostItem=noop,PostCommodity=noop,ConfirmPostCommodity=noop,
 CalculateItemDeposit=function() return 5000 end,
 CalculateCommodityDeposit=function() return 5000 end,
 GetOwnedAuctions=function() return OWNED or {} end,
 HasFullOwnedAuctionResults=function() return COMPLETE~=false end,
 QueryOwnedAuctions=noop,PlaceBid=noop,ConfirmCommoditiesPurchase=noop,
}
function GetInboxNumItems() return #INBOX,MAIL_TOTAL or #INBOX end
function GetInboxHeaderInfo(i)
    local m=INBOX[i]
    if not m then return end
    return nil,nil,m.sender or "Auction House",m.subject or "Auction successful: Copper Ore",m.money or 0,m.cod or 0,30,#(m.items or {}),false,false,false,true
end
function GetInboxInvoiceInfo(i)
    local m=INBOX[i]
    if not m then return end
    return m.invoiceType,m.name or "Copper Ore",m.buyer,m.gross,nil,m.refund,m.fee,nil,nil,nil,m.quantity
end
function GetInboxItemLink(i,s) return INBOX[i] and INBOX[i].items and INBOX[i].items[s] and INBOX[i].items[s].link end
function GetInboxItem(i,s)
    local item=INBOX[i].items[s]; return "Copper Ore",2770,nil,item.quantity
end
TakeInboxMoney=noop; AutoLootMailItem=noop; TakeInboxItem=noop; SendMail=noop
function GetSendMailMoney() return 10000 end
function GetSendMailPrice() return 30 end
function GetSendMailCOD() return 0 end
function GetSendMailItemLink() return nil end
function GetTargetTradeMoney() return 2000 end
function GetPlayerTradeMoney() return 1000 end
function GetTradePlayerItemLink() return nil end
function GetTradeTargetItemLink() return nil end
function SetTradeMoney() end
function BuyMerchantItem() end
function BuybackItem() end
function RepairAllItems() end
function GetRepairAllCost() return 150 end
function TakeTaxiNode() end
function TaxiNodeCost() return 100 end
function TaxiNodeName() return "Stormwind" end
GOLD_AMOUNT="%d Gold"; SILVER_AMOUNT="%d Silver"; COPPER_AMOUNT="%d Copper"
AUCTION_EXPIRED_MAIL_SUBJECT="Auction expired: %s"
AUCTION_REMOVED_MAIL_SUBJECT="Auction cancelled: %s"
ERR_TRADE_COMPLETE="Trade complete."; ERR_TRADE_CANCELLED="Trade cancelled."
'''


@unittest.skipIf(LuaRuntime is None,"Install lupa to test the actual Lua addon")
class AddonTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(MOCKS)
        self.lua.execute("F={}")
        for name in ("Core.lua","Collectors.lua","Disenchant.lua","Valuation.lua","Prices.lua","Chart.lua","UI.lua"):
            code=(ROOT/"ForeverLedger"/name).read_text(encoding="utf-8")
            self.lua.execute("assert(loadstring(...))('ForeverLedger',F)",code)
        self.lua.execute('F.Init({}, {guid="Player-Main",name="Main-Realm",realm="Realm",build="test"}); F.ObserveBalance(WALLET)')

    def run_lua(self,code):
        return self.lua.execute(code)

    def events(self):
        return json.loads(self.run_lua("return F.Export(1,100000)"))["events"]

    def kind(self,name):
        return [e["data"] for e in self.events() if e["kind"]==name]

    def test_baseline_is_not_income(self):
        self.assertEqual(self.kind("balance"),[])

    def test_balance_duplicate_suppressed(self):
        self.run_lua("F.ObserveBalance(100100); F.ObserveBalance(100100); F.Flush()")
        self.assertEqual(len(self.kind("balance")),1)
        self.assertEqual(self.kind("reconciliation")[0]["residual"],100)

    def test_quest_money_arrives_before_evidence(self):
        self.run_lua("F.ObserveBalance(102000); F.events.QUEST_TURNED_IN(10,100,2000); F.Flush()")
        self.assertEqual(self.kind("reconciliation")[0]["residual"],0)

    def test_quest_evidence_arrives_before_money(self):
        self.run_lua("F.events.QUEST_TURNED_IN(10,100,2000); F.ObserveBalance(102000); F.Flush()")
        self.assertEqual(self.kind("reconciliation")[0]["residual"],0)

    def test_unknown_source_preserved(self):
        self.run_lua("F.ObserveBalance(99999); F.Flush()")
        self.assertEqual(self.kind("reconciliation")[0]["residual"],-1)

    def test_failed_intent_does_not_create_expense(self):
        self.run_lua('F.Intent("purchase",-100,{}); F.Flush()')
        self.assertEqual(self.kind("activity"),[])

    def test_unique_intent_correlated(self):
        self.run_lua('F.Intent("purchase",-100,{}); F.ObserveBalance(99900); F.Flush()')
        self.assertEqual(self.kind("activity")[0]["confidence"],"correlated_amount")
        self.assertEqual(self.kind("reconciliation")[0]["residual"],0)

    def test_ambiguous_intent_not_guessed(self):
        self.run_lua('F.Intent("purchase",-100,{}); F.Intent("repair",-100,{}); F.ObserveBalance(99900); F.Flush()')
        self.assertEqual(self.kind("activity"),[])
        self.assertEqual(self.kind("reconciliation")[0]["residual"],-100)

    def test_old_intent_not_reused(self):
        self.run_lua('F.Intent("purchase",-100,{}); CLOCK=20; F.ObserveBalance(99900); F.Flush()')
        self.assertEqual(self.kind("activity"),[])

    def test_bulk_vendor_sales_reconcile(self):
        self.run_lua('F.Intent("vendor_sale",100,{}); F.Intent("vendor_sale",200,{}); F.ObserveBalance(100300); F.Flush()')
        self.assertEqual([d["amount"] for d in self.kind("activity")],[100,200])
        self.assertEqual(self.kind("reconciliation")[0]["residual"],0)

    def test_failed_extra_intent_prevents_bulk_guess(self):
        self.run_lua('F.Intent("vendor_sale",100,{}); F.Intent("vendor_sale",200,{}); F.Intent("vendor_sale",500,{}); F.ObserveBalance(100300); F.Flush()')
        self.assertEqual(self.kind("activity"),[])

    def test_observation_and_claim_not_added_twice(self):
        self.run_lua('F.Claim("loot",100,{}); F.ObserveBalance(100100); F.Flush(); F.Flush()')
        self.assertEqual(len(self.kind("reconciliation")),1)
        self.assertEqual(self.kind("reconciliation")[0]["observed"],100)

    def test_reload_gap_is_explicit(self):
        self.run_lua('F.baselined=nil; F.Init(F.db,F.identity); F.ObserveBalance(101000)')
        self.assertEqual(self.kind("baseline")[-1]["gap"],1000)
        self.assertEqual(self.kind("balance"),[])

    def test_immutable_event_payload(self):
        self.run_lua('D={item={id=1}}; F.Emit("test",D); D.item.id=2')
        self.assertEqual(self.kind("test")[0]["item"]["id"],1)

    def test_json_escaping_and_utf8(self):
        result=self.run_lua('return F.JSON({s="Grüße\\n\\\"\\\\",b=true,n=-2})')
        self.assertEqual(json.loads(result)["s"],'Grüße\n"\\')

    def test_json_preserves_non_money_fractional_metadata(self):
        result=json.loads(self.run_lua('return F.JSON({clock=0.125,amount=12345})'))
        self.assertEqual(result["clock"],0.125)

    def test_post_call_without_success_not_posted(self):
        self.run_lua('F.InstallHooks(); C_AuctionHouse.PostItem({link="item:2770"},1,1,0,100000)')
        self.assertEqual(self.kind("auction_posted"),[])
        self.assertEqual(self.kind("activity"),[])

    def test_post_confirm_and_duplicate(self):
        self.run_lua('F.InstallHooks(); C_AuctionHouse.PostItem({link="item:2770"},1,1,0,100000); F.Created(55); F.Created(55)')
        self.assertEqual(len(self.kind("auction_posted")),1)
        self.assertEqual(self.kind("activity")[0]["amount"],-5000)

    def test_warned_post_confirmed_once(self):
        self.run_lua('''
        F.InstallHooks(); C_AuctionHouse.PostItem({link="item:2770"},1,1,0,100000)
        F.events.AUCTION_HOUSE_POST_WARNING(); CLOCK=2
        C_AuctionHouse.ConfirmPostItem({link="item:2770"},1,1,0,100000); F.Created(55)
        CLOCK=5; C_AuctionHouse.PostItem({link="item:999"},1,1,0,7000); F.Created(56)
        ''')
        posted=self.kind("auction_posted")
        self.assertEqual([p["totalPrice"] for p in posted],[100000,7000])
        self.assertEqual(len(self.kind("auction_post_intent")),2)

    def test_cancelled_warning_does_not_shift_queue(self):
        self.run_lua('''
        F.InstallHooks(); C_AuctionHouse.PostItem({link="item:2770"},1,1,0,100000)
        F.events.AUCTION_HOUSE_POST_WARNING(); CLOCK=5
        C_AuctionHouse.PostItem({link="item:999"},1,1,0,7000); F.Created(56)
        ''')
        self.assertEqual(self.kind("auction_posted")[0]["item"]["link"],"item:999")

    def test_multisell_splits_quantity_and_deposit(self):
        self.run_lua('''
        CalculateDeposit=C_AuctionHouse.CalculateItemDeposit
        C_AuctionHouse.CalculateItemDeposit=function() return 5003 end
        F.InstallHooks(); C_AuctionHouse.PostItem({link="item:2770"},1,3,0,100000)
        F.events.AUCTION_MULTISELL_START(3); F.Created(55); CLOCK=20; F.Created(56); CLOCK=40; F.Created(57)
        ''')
        posted=self.kind("auction_posted")
        self.assertEqual([p["quantity"] for p in posted],[1,1,1])
        self.assertEqual([p["deposit"] for p in posted],[1667,1668,1668])
        self.assertTrue(all(p["item"]["link"]=="item:2770" for p in posted))

    def test_commodity_price_is_total(self):
        self.run_lua('F.InstallHooks(); C_AuctionHouse.PostCommodity({link="item:2770"},1,20,100); F.Created(55)')
        self.assertEqual(self.kind("auction_posted")[0]["totalPrice"],2000)

    def post(self,id=55):
        self.run_lua(f'F.Posted({id},{{item={{id=2770,name="Copper Ore"}},quantity=1,deposit=5000,totalPrice=100000}})')

    def test_successful_deposit_not_forfeited(self):
        self.post()
        self.run_lua('F.Invoice({invoiceType="seller",item={name="Copper Ore"},quantity=1,gross=100000,commission=5000,depositRefund=5000,money=100000})')
        self.assertEqual(self.kind("auction_outcome")[0]["outcome"],"sold")
        self.assertNotIn("depositLost",self.kind("auction_outcome")[0])

    def test_cancel_and_return_mail_no_double_fee(self):
        self.post(); self.post(56)
        self.run_lua('F.events.AUCTION_CANCELED(55); F.Invoice({failure="cancelled",item={id=2770,name="Copper Ore"},quantity=1})')
        self.assertEqual(len(self.kind("auction_outcome")),1)
        self.assertEqual(self.kind("auction_return")[0]["auctionKey"],"Player-Main:55")

    def test_offline_failure_fifo_is_explicit(self):
        self.post(); self.post(56)
        self.run_lua('F.Invoice({failure="expired",item={id=2770},quantity=1})')
        self.assertEqual(self.kind("auction_outcome")[0]["confidence"],"allocated_fifo")

    def test_missing_post_does_not_invent_deposit(self):
        self.run_lua('F.Invoice({failure="expired",item={id=2770},quantity=1})')
        self.assertEqual(self.kind("auction_outcome"),[])
        self.assertEqual(self.kind("auction_return")[0]["matchConfidence"],"unmatched")

    def test_post_failure_clears_stale_queue(self):
        self.run_lua('F.CapturePost({link="item:2770"},1,1,0,100000,false); F.events.AUCTION_HOUSE_POST_ERROR(); F.Created(56)')
        self.assertNotIn("deposit",self.kind("auction_posted")[0])

    def test_expired_mail_subject_detected(self):
        self.run_lua('INBOX={{subject="Auction expired: Copper Ore",items={{link="item:2770",quantity=1}}}}; M=F.ReadMail(1)')
        self.assertEqual(self.run_lua('return M.failure'),"expired")

    def test_partial_stack_sale_left_unmatched(self):
        self.post()
        self.run_lua('F.Invoice({invoiceType="seller",item={name="Copper Ore"},quantity=2,gross=200000,commission=10000,depositRefund=5000,money=195000})')
        self.assertEqual(self.kind("auction_sale")[0]["matchConfidence"],"unmatched")

    def test_nil_positions_in_api_return(self):
        self.assertEqual(self.run_lua('local a,b,c,d=F.Call(function() return nil,"x",nil,42 end); return d'),42)

    def test_mail_sale_and_duplicate_success(self):
        self.post()
        self.run_lua('''
        INBOX={{invoiceType="seller",money=100000,gross=100000,refund=5000,fee=5000,quantity=1}}
        F.context.mail=true; F.ScanMail(); F.TakeMail(1,"money"); F.MailSuccess(nil); F.MailSuccess(nil)
        ''')
        self.assertEqual(len(self.kind("auction_sale")),1)
        self.assertEqual(self.kind("auction_sale")[0]["commission"],5000)

    def test_stale_mail_cache_not_used_after_index_shift(self):
        self.run_lua('''
        INBOX={{sender="Alt-Realm",subject="Gold",money=100},{sender="Bank-Realm",subject="Rent",money=900}}
        F.context.mail=true; F.ScanMail(); table.remove(INBOX,1)
        F.TakeMail(1,"money"); F.MailSuccess(nil)
        ''')
        activity=self.kind("activity")[0]
        self.assertEqual((activity["amount"],activity["sender"]),(900,"Bank-Realm"))

    def test_mail_failed_no_claim(self):
        self.run_lua('INBOX={{money=500}}; F.TakeMail(1,"money"); F.events.MAIL_FAILED(); F.MailSuccess(nil)')
        self.assertEqual(self.kind("activity"),[])

    def test_open_all_item_confirmation_not_money(self):
        self.run_lua('INBOX={{money=500}}; F.TakeMail(1,"all"); F.MailSuccess(2770)')
        self.assertEqual(self.kind("activity"),[])
        self.run_lua('F.MailSuccess(nil)')
        self.assertEqual(self.kind("activity")[0]["amount"],500)

    def test_mail_send_postage_separate(self):
        self.run_lua('F.InstallHooks(); SendMail("Bank-Realm"); F.events.MAIL_SEND_SUCCESS()')
        self.assertEqual([e["amount"] for e in self.kind("activity")],[-10000,-30])

    def test_trade_requires_completed_event(self):
        self.run_lua('F.events.TRADE_SHOW(); F.events.TRADE_CLOSED()')
        self.assertEqual(self.kind("activity"),[])
        self.run_lua('F.events.UI_INFO_MESSAGE(0,ERR_TRADE_COMPLETE); F.events.UI_INFO_MESSAGE(0,ERR_TRADE_COMPLETE)')
        self.assertEqual(len(self.kind("activity")),1)
        self.assertEqual(self.kind("activity")[0]["amount"],1000)

    def test_cancel_trade_no_income(self):
        self.run_lua('F.events.TRADE_SHOW(); F.events.TRADE_REQUEST_CANCEL(); F.events.UI_INFO_MESSAGE(0,ERR_TRADE_COMPLETE)')
        self.assertEqual(self.kind("activity"),[])

    def test_money_parser(self):
        self.assertEqual(self.run_lua('return F.ParseMoney("You loot 1 Gold, 23 Silver, 45 Copper.")'),12345)
        self.assertIsNone(self.run_lua('return F.ParseMoney("unknown locale")'))

    def test_partial_mail_snapshot_is_marked(self):
        self.run_lua('INBOX={{money=500}}; MAIL_TOTAL=2; F.context.mail=true; F.ScanMail()')
        self.assertFalse(self.kind("snapshot")[0]["complete"])

    def test_owned_auction_disappearance_not_failure(self):
        self.post()
        self.run_lua('F.context.auction=true; OWNED={}; F.ScanAuctions()')
        self.assertEqual(self.kind("auction_outcome"),[])

    def test_inventory_vendor_value(self):
        self.run_lua('BAGS[0]={{hyperlink="item:2770",itemID=2770,stackCount=20}}; F.ScanBags(true)')
        row=self.kind("snapshot")[0]["rows"][0]
        self.assertEqual(row["quantity"]*row["item"]["vendorPrice"],1000)

    def test_export_pages_keep_stable_ids(self):
        self.run_lua('F.Emit("test",{}); F.Emit("test",{})')
        a=json.loads(self.run_lua('return F.Export(1,2)'))
        b=json.loads(self.run_lua('return F.Export(2,2)'))
        self.assertEqual(a["events"][1],b["events"][0])

    def test_main_login_and_logout(self):
        self.lua.execute("assert(loadstring(...))('ForeverLedger',F)",(ROOT/"ForeverLedger"/"Main.lua").read_text())
        self.run_lua('LAST_FRAME.scripts.OnEvent(nil,"ADDON_LOADED","ForeverLedger"); LAST_FRAME.scripts.OnEvent(nil,"PLAYER_LOGIN"); LAST_FRAME.scripts.OnEvent(nil,"PLAYER_LOGOUT")')
        self.assertEqual(self.kind("diagnostic"),[])
        self.assertEqual(len(self.kind("logout")),1)

    def test_real_lua_export_to_sqlite(self):
        self.run_lua('''
        for i=1,6 do
            F.Posted(i,{item={id=2770,name="Copper Ore"},quantity=1,deposit=20000,totalPrice=100000})
            F.AuctionOutcome(F.AuctionKey(i),"expired","server_id")
        end
        F.Invoice({invoiceType="seller",item={id=2770,name="Copper Ore"},quantity=1,gross=100000,commission=5000,depositRefund=1000,money=96000})
        ''')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/"real.json"
            path.write_text(self.run_lua('return F.Export(1,100000)'),encoding="utf-8")
            db=ledger.connect(":memory:")
            first=ledger.import_file(db,path)
            self.assertGreater(first,10)
            self.assertEqual(ledger.import_file(db,path),0)
            row=ledger.report(db)["items"][0]
            self.assertEqual(row["deposits_forfeited"],120000)
            self.assertEqual(row["margin_before_acquisition"],-25000)
            db.close()


def event(source,seq,kind,data,name="Main-Realm",stamp=1800000000):
    return dict(schema=1,id=f"{source}:{seq}",sequence=seq,sourceID=source,character=name,
        characterName=name,realm="Realm",time=stamp,kind=kind,data=data)


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=ledger.connect(":memory:")

    def tearDown(self):
        self.db.close(); self.temp.cleanup()

    def save(self,source,events):
        path=Path(self.temp.name)/(source+".json")
        path.write_text(json.dumps(dict(schema=1,sourceID=source,events=events,owners={})),encoding="utf-8")
        return path

    def test_repeated_import_is_idempotent(self):
        p=self.save("one",[event("one",1,"balance",dict(before=0,after=50,delta=50))])
        self.assertEqual(ledger.import_file(self.db,p),1)
        self.assertEqual(ledger.import_file(self.db,p),0)

    def test_two_accounts_merge_and_exclude_internal_transfers(self):
        a=[event("one",1,"activity",dict(category="mail_sent",amount=-100,recipient="Bank-Realm")),
           event("one",2,"activity",dict(category="postage",amount=-30,recipient="Bank-Realm"))]
        b=[event("two",1,"activity",dict(category="mail_received",amount=100,sender="Main-Realm"),"Bank-Realm")]
        ledger.import_file(self.db,self.save("one",a)); ledger.import_file(self.db,self.save("two",b))
        r=ledger.report(self.db)
        self.assertEqual(r["internal_transfer_net"],0)
        self.assertEqual(r["classified_external_cash_in"],0)
        self.assertEqual(r["classified_external_cash_out"],30)

    def test_external_trade_preserves_both_gross_flows(self):
        e=event("one",1,"activity",dict(category="trade",amount=0,moneyIn=100,moneyOut=100,counterparty="Other-Realm"))
        ledger.import_file(self.db,self.save("one",[e]))
        r=ledger.report(self.db)
        self.assertEqual(r["classified_external_cash_in"],100)
        self.assertEqual(r["classified_external_cash_out"],100)

    def test_conflicting_id_rolls_back(self):
        e=event("one",1,"test",dict(value=1))
        ledger.import_file(self.db,self.save("one",[e]))
        e["data"]["value"]=2
        with self.assertRaises(ValueError):
            ledger.import_file(self.db,self.save("one",[event("one",2,"test",{}),e]))
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0],1)

    def test_detect_missing_export_pages(self):
        ledger.import_file(self.db,self.save("one",[event("one",2,"test",{})]))
        self.assertEqual(len(ledger.report(self.db)["incomplete_imports"]),1)

    def test_selling_fees_can_exceed_revenue(self):
        events=[event("one",1,"auction_posted",dict(key="a",item=dict(id=1,name="Sword"),deposit=50000)),
            event("one",2,"auction_outcome",dict(auctionKey="a",item=dict(id=1,name="Sword"),outcome="expired",depositLost=50000,confidence="server_id")),
            event("one",3,"auction_sale",dict(item=dict(id=1,name="Sword"),gross=40000,commission=2000,quantity=1))]
        ledger.import_file(self.db,self.save("one",events))
        row=ledger.report(self.db)["items"][0]
        self.assertEqual(row["margin_before_acquisition"],-12000)
        self.assertTrue(row["selling_costs_exceed_revenue"])
        self.assertIsNone(row["profit_at_supplied_unit_cost"])

    def test_success_refund_not_revenue_or_fee_loss(self):
        events=[event("one",1,"auction_sale",dict(item=dict(id=1),gross=10000,commission=500,depositRefund=1000,quantity=1))]
        ledger.import_file(self.db,self.save("one",events))
        row=ledger.report(self.db,{"1":1000})["items"][0]
        self.assertEqual(row["margin_before_acquisition"],9500)
        self.assertEqual(row["profit_at_supplied_unit_cost"],8500)

    def test_snapshot_history_not_summed(self):
        events=[event("one",1,"snapshot",dict(location="bags",complete=True,rows=[dict(quantity=10,item=dict(id=1,vendorPrice=50))])),
            event("one",2,"snapshot",dict(location="bags",complete=True,rows=[dict(quantity=2,item=dict(id=1,vendorPrice=50))]))]
        ledger.import_file(self.db,self.save("one",events))
        snap=ledger.report(self.db)["latest_snapshots"]
        self.assertEqual(len(snap),1)
        self.assertEqual(snap[0]["vendor_value"],100)

    def test_saved_variables_literal_parser(self):
        obj=ledger.LuaReader('ForeverLedgerDB = { ["schema"]=1, ["sourceID"]="abc", ["events"]={}, ["owners"]={["Grüße-Realm"]=true}, }').read()
        self.assertEqual(obj["owners"],{"Grüße-Realm":True})

    def test_reject_executable_lua(self):
        for text in ('ForeverLedgerDB = os.execute("bad")','ForeverLedgerDB = {}; print("bad")'):
            with self.assertRaises(ValueError): ledger.LuaReader(text).read()

    def test_lua_sequences_and_escapes(self):
        obj=ledger.LuaReader(r'ForeverLedgerDB = { ["rows"] = { { ["text"] = "a\010b\"c" }, }, }').read()
        self.assertEqual(obj["rows"][0]["text"],'a\nb"c')

    def test_lua_utf8_byte_escapes(self):
        self.assertEqual(ledger.LuaReader(r'ForeverLedgerDB={name="Gr\195\188\195\159e"}').read()["name"],"Grüße")

    def test_unmatched_return_is_flagged(self):
        ledger.import_file(self.db,self.save("one",[event("one",1,"auction_return",dict(failure="expired",item=dict(id=1)))]))
        self.assertEqual(len(ledger.report(self.db)["unmatched_auction_returns"]),1)

    def test_csv_export(self):
        ledger.export_csv(self.db,self.temp.name)
        self.assertTrue((Path(self.temp.name)/"auction_sales.csv").exists())


if __name__=="__main__":
    unittest.main()
