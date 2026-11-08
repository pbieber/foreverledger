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
function GetSendMailPrice() return 10030 end
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
        for name in ("Core.lua","Collectors.lua","Disenchant.lua","Valuation.lua","Profit.lua","Prices.lua","Sync.lua","Highlights.lua","Chart.lua","UI.lua","Minimap.lua"):
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

    # Forever fires AUCTION_CANCELED when an auction sells or expires, not only on a cancel.
    def sell_mail(self):
        self.run_lua('F.Invoice({invoiceType="seller",item={id=2770,name="Copper Ore"},quantity=1,gross=100000,'
                     'commission=5000,depositRefund=5000,money=100000})')

    def test_auction_canceled_without_a_cancel_is_not_a_cancellation(self):
        self.post()
        self.run_lua('NOW=NOW+60; F.events.AUCTION_CANCELED(55); NOW=NOW+3600')
        self.assertEqual(self.kind("auction_outcome"),[])
        self.assertEqual(self.kind("auction_left")[0]["auctionKey"],"Player-Main:55")
        self.sell_mail()
        outcome=self.kind("auction_outcome")
        self.assertEqual([o["outcome"] for o in outcome],["sold"])
        self.assertNotIn("depositLost",outcome[0])
        self.assertEqual(outcome[0]["leftAt"],1800000060)  # When it sold, not when the mail came.

    def test_players_own_cancel_is_a_cancellation(self):
        self.post()
        self.run_lua('''
        C_AuctionHouse.CancelAuction=function() end; C_AuctionHouse.GetCancelCost=function() return 0 end
        F.InstallHooks(); C_AuctionHouse.CancelAuction(55); CLOCK=1; F.events.AUCTION_CANCELED(55)
        ''')
        outcome=self.kind("auction_outcome")
        self.assertEqual([(o["outcome"],o["confidence"],o["depositLost"]) for o in outcome],[("cancelled","player_cancel",5000)])
        self.assertEqual(self.kind("auction_left"),[])

    def test_an_old_cancel_only_counts_if_the_event_follows_the_call(self):
        self.post()
        self.run_lua('''
        C_AuctionHouse.CancelAuction=function() end; C_AuctionHouse.GetCancelCost=function() return 0 end
        F.InstallHooks(); C_AuctionHouse.CancelAuction(55); CLOCK=600; F.events.AUCTION_CANCELED(55)
        ''')
        self.assertEqual(self.kind("auction_outcome"),[])

    def test_a_later_sale_overrides_a_cancel(self):
        self.post()
        self.run_lua('F.AuctionOutcome(F.AuctionKey(55),"cancelled","server_id")')  # As earlier versions recorded it.
        self.sell_mail()
        outcome=self.kind("auction_outcome")
        self.assertEqual([o["outcome"] for o in outcome],["cancelled","sold"])
        self.assertEqual(outcome[1]["replaces"],"cancelled")
        self.assertEqual(self.kind("auction_sale")[0]["auctionKey"],"Player-Main:55")
        self.assertEqual(self.run_lua('return F.db.auctions["Player-Main:55"].outcome'),"sold")
        self.sell_mail()  # The same auction cannot sell twice.
        self.assertEqual(self.kind("auction_sale")[1]["matchConfidence"],"unmatched")

    def test_a_sale_does_not_override_a_cancel_without_mail(self):
        self.post()
        self.run_lua('F.AuctionOutcome(F.AuctionKey(55),"cancelled","server_id"); F.AuctionOutcome(F.AuctionKey(55),"sold","x")')
        self.assertEqual([o["outcome"] for o in self.kind("auction_outcome")],["cancelled"])

    def test_mail_goes_to_the_auction_that_left_the_house(self):
        self.post(); self.post(56)
        self.run_lua('NOW=NOW+10; F.events.AUCTION_CANCELED(56)')
        self.run_lua('F.Invoice({failure="expired",item={id=2770,name="Copper Ore"},quantity=1})')
        self.assertEqual([(o["auctionKey"],o["outcome"]) for o in self.kind("auction_outcome")],[("Player-Main:56","expired")])

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

    def test_mail_sale_counts_once_however_often_the_client_confirms(self):
        self.post()
        self.run_lua("""
        INBOX={{invoiceType="seller",money=100000,gross=100000,refund=5000,fee=5000,quantity=1}}
        F.context.mail=true; F.ScanMail()
        INBOX[1].money=0; F.ScanMail(); F.events.MAIL_SUCCESS(); F.events.MAIL_SUCCESS()
        INBOX={}; F.ScanMail(); F.ScanMail()
        """)
        self.assertEqual(len(self.kind("auction_sale")),1)
        self.assertEqual(self.kind("auction_sale")[0]["commission"],5000)
        self.assertEqual(self.kind("mail_collected")[0]["mode"],"money")

    def test_sales_collected_right_after_an_item_mail_are_not_lost(self):
        # An expired item followed by sold mail left 2250g under Not identified on TBC,
        # where an item take is never confirmed.
        self.run_lua("""
        local sale={invoiceType="seller",money=300,gross=300,refund=0,fee=15,quantity=1}
        INBOX={{subject="Auction expired: Copper Ore",items={{link="item:2770",quantity=2}}},
            sale,{invoiceType="seller",money=700,gross=700,refund=0,fee=35,quantity=1,subject="Auction successful: Tin Ore"}}
        F.context.mail=true; F.ScanMail()
        table.remove(INBOX,1); F.ScanMail()
        table.remove(INBOX,1); F.ObserveBalance(100300); F.ScanMail()
        table.remove(INBOX,1); F.ObserveBalance(101000); F.ScanMail()
        F.Flush()
        """)
        self.assertEqual([d["money"] for d in self.kind("auction_sale")],[300,700])
        self.assertEqual(len(self.kind("auction_return")),1)
        reconciliation=self.kind("reconciliation")[0]
        self.assertEqual((reconciliation["residual"],reconciliation["status"]),(0,"balanced"))

    def test_retried_take_of_a_paid_mail_counts_only_what_was_paid(self):
        # A mail addon took one of two identical sales again after it had paid.
        self.run_lua("""
        local function sale() return {invoiceType="seller",money=500,gross=500,refund=0,fee=25,quantity=5} end
        INBOX={sale(),sale()}
        F.context.mail=true; F.ScanMail()
        INBOX[1].money=0; F.ScanMail(); F.events.MAIL_SUCCESS(); F.ScanMail()
        F.ObserveBalance(100500); F.Flush()
        """)
        self.assertEqual(len(self.kind("auction_sale")),1)
        self.assertEqual(self.kind("reconciliation")[0]["residual"],0)
        self.run_lua('table.remove(INBOX,1); INBOX[1].money=0; F.ScanMail(); F.ObserveBalance(101000); F.Flush()')
        self.assertEqual(len(self.kind("auction_sale")),2)
        self.assertEqual(self.kind("reconciliation")[1]["residual"],0)

    def test_identical_sales_with_different_amounts_keep_their_own(self):
        self.run_lua("""
        INBOX={{invoiceType="seller",money=3341,gross=3500,quantity=1},{invoiceType="seller",money=3332,gross=3490,quantity=1},
            {invoiceType="seller",money=3341,gross=3500,quantity=1}}
        F.context.mail=true; F.ScanMail()
        table.remove(INBOX,2); F.ScanMail()
        """)
        self.assertEqual([d["money"] for d in self.kind("auction_sale")],[3332])

    def test_collected_mail_is_named_after_an_index_shift(self):
        self.run_lua("""
        INBOX={{sender="Alt-Realm",subject="Gold",money=100},{sender="Bank-Realm",subject="Rent",money=900}}
        F.context.mail=true; F.ScanMail(); table.remove(INBOX,1); F.ScanMail()
        table.remove(INBOX,1); F.ScanMail()
        """)
        activity=self.kind("activity")
        self.assertEqual([(a["amount"],a["sender"]) for a in activity],[(100,"Alt-Realm"),(900,"Bank-Realm")])

    def test_mail_failed_no_claim(self):
        self.run_lua('INBOX={{money=500}}; F.context.mail=true; F.ScanMail(); F.events.MAIL_FAILED(); F.ScanMail()')
        self.assertEqual(self.kind("activity"),[])
        self.assertEqual(self.kind("mail_collected"),[])

    def test_mail_still_loading_is_not_taken_for_collected(self):
        self.run_lua("""
        RETRIEVING_DATA="Retrieving data"
        INBOX={{sender="Alt-Realm",subject="Gold",money=100},{sender="Bank-Realm",subject="Rent",money=900}}
        F.context.mail=true; F.ScanMail()
        INBOX[2].subject=RETRIEVING_DATA; F.ScanMail()
        INBOX[2].subject="Rent"; F.ScanMail()
        """)
        self.assertEqual(self.kind("activity"),[])

    def test_returned_and_deleted_mail_is_not_income(self):
        self.run_lua("""
        ReturnInboxItem=function() end; DeleteInboxItem=function() end
        F.InstallHooks()
        INBOX={{sender="Alt-Realm",subject="Gold",money=100},{sender="Bank-Realm",subject="Junk",items={{link="item:2770",quantity=1}}}}
        F.context.mail=true; F.ScanMail()
        ReturnInboxItem(1); table.remove(INBOX,1); F.ScanMail()
        DeleteInboxItem(1); table.remove(INBOX,1); F.ScanMail()
        """)
        self.assertEqual(self.kind("mail_collected"),[])

    def test_mailbox_reopened_empty_collects_nothing(self):
        self.run_lua("""
        INBOX={{money=500}}; F.events.MAIL_SHOW()
        F.events.MAIL_CLOSED(); INBOX={}; F.events.MAIL_SHOW()
        """)
        self.assertEqual(self.kind("mail_collected"),[])

    def test_one_attachment_taken_then_cod_paid_once(self):
        self.run_lua("""
        INBOX={{sender="Alt-Realm",subject="Ore",cod=400,items={{link="item:2770",quantity=2},{link="item:2771",quantity=3}}}}
        F.context.mail=true; F.ScanMail()
        table.remove(INBOX[1].items,1); INBOX[1].cod=0; F.ScanMail()
        INBOX={}; F.ScanMail()
        """)
        collected=self.kind("mail_collected")
        self.assertEqual([(c["mode"],len(c["items"])) for c in collected],[("item",1),("item",1)])
        self.assertEqual([a["amount"] for a in self.kind("activity") if a["category"]=="mail_cod"],[-400])

    def old_mail_records(self):
        # Records as earlier versions left them: mailbox reads and unexplained gold, no sale.
        self.run_lua("""
        function READ()
            local rows={}
            for i=1,#INBOX do rows[i]=F.ReadMail(i) end
            F.Snapshot("mail",rows,true,{visible=#rows,total=#rows})
        end
        function SALE(money) return {invoiceType="seller",money=money,gross=money,refund=0,fee=5,quantity=1} end
        F.db.mailBackfilled=nil
        """)

    def test_backfill_recovers_sales_an_item_mail_hid(self):
        self.old_mail_records()
        self.run_lua("""
        INBOX={{subject="Auction expired: Copper Ore",items={{link="item:2770",quantity=2}}},SALE(300),SALE(700)}
        READ(); table.remove(INBOX,1); READ()
        NOW=NOW+1; table.remove(INBOX,1); READ(); table.remove(INBOX,1); READ()
        STAMP=NOW
        F.ObserveBalance(101000); F.Flush()
        NOW=NOW+500
        RESULT=F.BackfillMail()
        """)
        self.assertEqual(self.run_lua('return RESULT.amount'),1000)
        sold=[d for d in self.kind("activity") if d["category"]=="auction_sale"]
        self.assertEqual(sorted(d["amount"] for d in sold),[300,700])
        for d in sold:
            self.assertTrue(d["backfilled"])
            self.assertEqual(d["occurredAt"],self.run_lua('return STAMP'))
            self.assertEqual(d["confidence"],"backfilled_snapshot")
        self.assertEqual(len(self.kind("auction_sale")),2)
        summary=self.kind("mail_backfill")[0]
        self.assertEqual((summary["status"],summary["added"],summary["amount"],summary["residual"]),("applied",2,1000,1000))
        self.assertEqual(summary["reconciliationIDs"],[self.events_of("reconciliation")[0]["id"]])

    def test_backfill_belongs_to_the_character_that_collected(self):
        self.old_mail_records()
        self.run_lua("""
        INBOX={SALE(300)}; READ(); INBOX={}; READ(); F.ObserveBalance(100300); F.Flush()
        F.identity={guid="Player-Other",name="Other-Realm",realm="Realm"}; F.session="later"
        F.BackfillMail()
        """)
        for e in self.events_of("activity"):
            self.assertEqual((e["character"],e["characterName"]),("Player-Main","Main-Realm"))

    def test_backfill_leaves_the_current_batch_alone(self):
        self.old_mail_records()
        self.run_lua("""
        INBOX={SALE(300)}; READ(); INBOX={}; READ(); F.ObserveBalance(100300); F.Flush()
        F.BackfillMail()
        F.ObserveBalance(100350); F.Flush()
        """)
        self.assertEqual(self.kind("reconciliation")[-1]["residual"],50)

    def test_backfill_voids_a_retried_take_recorded_twice(self):
        self.old_mail_records()
        self.run_lua("""
        INBOX={SALE(500),SALE(500)}; READ()
        local paid=F.Copy(F.ReadMail(1)); paid.mode="money"
        INBOX={SALE(500)}; READ()
        F.Invoice(F.Copy(paid)); F.Invoice(F.Copy(paid))
        F.ObserveBalance(100500); F.Flush()
        F.BackfillMail()
        """)
        sold=self.events_of("activity")
        self.assertEqual(sum(e["data"]["amount"] for e in sold),500)
        void=[e["data"] for e in sold if e["data"].get("correctsActivityID")]
        self.assertEqual(len(void),1)
        self.assertEqual(void[0]["amount"],-500)
        self.assertEqual(self.kind("mail_backfill")[0]["removed"],1)

    def test_backfill_refuses_a_correction_the_gold_does_not_prove(self):
        self.old_mail_records()
        self.run_lua("""
        INBOX={SALE(300)}; READ(); INBOX={}; READ(); F.ObserveBalance(100299); F.Flush()
        RESULT=F.BackfillMail()
        """)
        self.assertEqual(self.kind("activity"),[])
        self.assertEqual(self.kind("auction_sale"),[])
        self.assertEqual(self.run_lua('return RESULT.skipped'),1)
        self.assertEqual(self.kind("mail_backfill")[0]["status"],"skipped")

    def test_backfill_ignores_mail_that_was_recorded(self):
        self.old_mail_records()
        self.run_lua("""
        INBOX={SALE(300)}; READ(); local paid=F.Copy(F.ReadMail(1)); paid.mode="money"; INBOX={}; READ()
        F.Invoice(paid); F.ObserveBalance(100300); F.Flush()
        F.BackfillMail()
        """)
        self.assertEqual(len(self.kind("activity")),1)
        self.assertEqual(self.kind("mail_backfill"),[])

    def test_backfill_ignores_unread_rows(self):
        self.old_mail_records()
        self.run_lua("""
        RETRIEVING_DATA="Retrieving data"
        INBOX={SALE(300),{subject="Rent",money=900}}; READ()
        F.Snapshot("mail",{F.ReadMail(1)},false,{visible=2,total=2})
        READ(); F.ObserveBalance(100900); F.Flush()
        F.BackfillMail()
        """)
        self.assertEqual(self.kind("activity"),[])

    def test_backfill_runs_once_from_login(self):
        self.old_mail_records()
        self.run_lua("""
        INBOX={SALE(300)}; READ(); INBOX={}; READ(); F.ObserveBalance(100300); F.Flush()
        F.baselined=nil; F.Init(F.db,F.identity)
        F.baselined=nil; F.Init(F.db,F.identity)
        """)
        self.assertEqual(len(self.kind("auction_sale")),1)
        self.assertTrue(self.run_lua('return F.db.mailBackfilled'))
        self.assertTrue(self.run_lua('return #MESSAGES>0'))

    def events_of(self,kind):
        return [e for e in self.events() if e["kind"]==kind]

    TRAINER_MOCKS='''function BuyTrainerService() end
function GetTrainerServiceCost() return 500 end
function GetTrainerServiceInfo() return "Linen Belt","","available" end
function GetTrainerServiceSkillLine() return "Tailoring" end
'''

    def test_training_records_which_kind_of_trainer(self):
        for answer,kind in [("1","profession"),("nil","class")]:
            self.setUp()
            self.run_lua(self.TRAINER_MOCKS+f'function IsTradeskillTrainer() return {answer} end\n'
                'F.InstallHooks(); BuyTrainerService(3); F.ObserveBalance(WALLET-500); F.Flush()')
            training=self.kind("activity")[0]
            self.assertEqual((training["service"],training["skillLine"],training["trainer"]),("Linen Belt","Tailoring",kind))

    def test_training_without_a_trainer_check_leaves_the_kind_unknown(self):
        self.run_lua(self.TRAINER_MOCKS+'F.InstallHooks(); BuyTrainerService(3); F.ObserveBalance(WALLET-500); F.Flush()')
        training=self.kind("activity")[0]
        self.assertEqual((training["category"],training["amount"]),("training",-500))
        self.assertNotIn("trainer",training)

    def repair(self,standing,cost):
        self.run_lua(f'function UnitReaction() return {standing} end\n'
            f'function GetRepairAllCost() return {cost} end\n'
            f'F.events.MERCHANT_SHOW(); RepairAllItems(); F.ObserveBalance(GetMoney()-{cost}); WALLET=WALLET-{cost}; F.Flush()')

    def train(self,standing,cost):
        self.run_lua(f'function UnitReaction() return {standing} end\n'
            f'function GetTrainerServiceCost() return {cost} end\n'
            f'BuyTrainerService(3); F.ObserveBalance(GetMoney()-{cost}); WALLET=WALLET-{cost}; F.Flush()')

    def lines(self):
        return self.run_lua('return table.concat(F.ReputationSavingsLines(),string.char(10))')

    def test_repair_records_the_vendors_standing_and_discount(self):
        self.run_lua('F.InstallHooks()')
        self.repair(7,8500)
        repair=self.kind("activity")[0]
        self.assertEqual((repair["category"],repair["amount"],repair["standing"],repair["discount"],repair["npc"]),
            ("repair",-8500,7,10,"Bank-Realm"))

    def test_training_records_the_trainers_standing_and_discount(self):
        self.run_lua(self.TRAINER_MOCKS+'F.InstallHooks()')
        self.train(6,900)
        training=self.kind("activity")[0]
        self.assertEqual((training["category"],training["amount"],training["service"],training["standing"],training["discount"],training["npc"]),
            ("training",-900,"Linen Belt",6,10,"Bank-Realm"))

    def savings_by_standing(self,category="repair"):
        r=self.run_lua(f'local r=F.ReputationSavings("{category}"); local t={{r.count,r.paid,r.full,r.saved}} '
            'for s=1,8 do t[#t+1]=r.byStanding[s] and r.byStanding[s].saved or -1 end return t')
        return list(r.values())

    def test_forever_repairs_save_ten_percent_from_honored_up(self):
        self.run_lua('F.InstallHooks()')
        for standing in (8,7,6):
            self.repair(standing,9000)
        self.repair(5,1000)
        self.repair(4,1000)
        # Totals, then the saving at each standing from Hated to Exalted (-1: none recorded).
        self.assertEqual(self.savings_by_standing(),[5,29000,32000,3000,-1,-1,-1,0,0,1000,1000,1000])

    def test_tbc_repairs_save_more_at_each_standing_from_friendly(self):
        self.run_lua('F.InstallHooks(); F.isTBC=true')
        self.repair(8,8000)
        self.repair(7,8500)
        self.repair(6,9000)
        self.repair(5,9500)
        self.repair(4,1000)
        self.assertEqual(self.savings_by_standing(),[5,36000,41000,5000,-1,-1,-1,0,500,1000,1500,2000])

    def test_training_savings_are_counted_apart_from_repairs(self):
        self.run_lua(self.TRAINER_MOCKS+'F.InstallHooks(); F.isTBC=true')
        self.train(8,8000)
        self.train(4,500)
        self.repair(6,9000)
        self.assertEqual(self.savings_by_standing("training"),[2,8500,10500,2000,-1,-1,-1,0,-1,-1,-1,2000])
        self.assertEqual(self.savings_by_standing("repair")[:4],[1,9000,10000,1000])
        lines=self.lines()
        self.assertIn("Repairs: 1 paid",lines)
        self.assertIn("Training: 2 paid",lines)
        self.assertIn("Total saved: "+self.run_lua("return F.Money(3000)"),lines)

    def test_savings_leave_out_records_without_a_standing(self):
        self.run_lua(self.TRAINER_MOCKS+'F.InstallHooks(); F.events.MERCHANT_SHOW(); RepairAllItems(); WALLET=WALLET-150; F.ObserveBalance(WALLET); F.Flush()')
        self.run_lua('BuyTrainerService(3); WALLET=WALLET-500; F.ObserveBalance(WALLET); F.Flush()')
        self.repair(6,900)
        r=self.run_lua('local r=F.ReputationSavings("repair"); return {r.count,r.saved,r.unknown.count,r.unknown.paid}')
        self.assertEqual(list(r.values()),[1,100,1,150])
        lines=self.lines()
        self.assertIn("Honored (10% off): 1",lines)
        self.assertIn("Training: none with a standing recorded yet.",lines)
        self.assertIn("so left out: 1 repairs",lines)
        self.assertIn(", 1 training",lines)
        self.assertIn("Reputation discounts",self.run_lua('return F.Summary()'))

    def test_savings_command_prints_the_comparison(self):
        self.run_lua('F.InstallHooks()')
        self.repair(8,8000)
        self.run_lua('MESSAGES={}; F.Command("savings")')
        printed=self.run_lua('local t={} for _,m in ipairs(MESSAGES) do t[#t+1]=m[1] end return table.concat(t,string.char(10))')
        self.assertIn("Repairs: 1 paid",printed)
        self.assertIn("Exalted (10% off)",printed)

    def test_mail_send_postage_separate(self):
        self.run_lua('F.InstallHooks(); SendMail("Bank-Realm"); F.events.MAIL_SEND_SUCCESS()')
        self.assertEqual([e["amount"] for e in self.kind("activity")],[-10000,-30])
        self.assertEqual(self.kind("mail_sent")[0]["postage"],30)

    def test_mail_send_balances_when_price_includes_the_money(self):
        self.run_lua('F.InstallHooks(); SendMail("Bank-Realm"); F.events.MAIL_SEND_SUCCESS(); F.ObserveBalance(100000-10030); F.Flush()')
        self.assertEqual(self.kind("reconciliation")[0]["status"],"balanced")

    def test_mail_postage_read_from_either_kind_of_price(self):
        for price,money,attachments,postage in [(10030,10000,0,30),(10120,10000,4,120),(30,10000,0,30),
                (30,10,0,30),(120,10,4,120),(30,0,0,30),(360,0,12,360)]:
            self.assertEqual(self.run_lua(f'return F.MailPostage({price},{money},{attachments})'),postage,(price,money,attachments))
        self.assertIsNone(self.run_lua('return F.MailPostage(nil,10000,0)'))

    def old_mail_send(self,money=10000,postage=10030,seen=None,items="{}"):
        # A send as earlier versions recorded it, with the money counted again as postage.
        seen=100000-postage if seen is None else seen
        self.run_lua(f"""
        F.db.postageRepaired=nil
        F.Emit("mail_sent",{{recipient="Bank-Realm",money={money},postage={postage},cod=0,items={items}}})
        F.Claim("mail_sent",-{money},{{recipient="Bank-Realm",items={items}}})
        F.Claim("postage",-{postage},{{recipient="Bank-Realm"}})
        F.ObserveBalance({seen}); F.Flush()
        """)

    def test_postage_repair_corrects_a_send_the_gold_proves(self):
        self.old_mail_send()
        self.run_lua('STAMP=NOW; NOW=NOW+500; RESULT=F.RepairPostage()')
        self.assertEqual((self.run_lua('return RESULT.fixed'),self.run_lua('return RESULT.amount')),(1,10000))
        rows=[d for d in self.kind("activity") if d["category"]=="postage"]
        self.assertEqual(sum(d["amount"] for d in rows),-30)
        self.assertEqual([d["amount"] for d in rows],[-10030,10030,-30])
        self.assertEqual(rows[1]["correctsActivityID"],self.events_of("activity")[1]["id"])
        for d in rows[1:]:
            self.assertTrue(d["backfilled"])
            self.assertEqual(d["occurredAt"],self.run_lua('return STAMP'))
        summary=self.kind("mail_backfill")[0]
        self.assertEqual((summary["repair"],summary["status"],summary["amount"],summary["residual"]),("postage","applied",10000,10000))
        self.assertEqual(summary["reconciliationIDs"],[self.events_of("reconciliation")[0]["id"]])

    def test_postage_repair_belongs_to_the_character_that_sent(self):
        self.old_mail_send()
        self.run_lua("""
        F.identity={guid="Player-Other",name="Other-Realm",realm="Realm"}; F.session="later"
        F.RepairPostage()
        """)
        for e in self.events_of("activity"):
            self.assertEqual((e["character"],e["characterName"]),("Player-Main","Main-Realm"))

    def test_postage_repair_refuses_what_the_gold_does_not_prove(self):
        self.old_mail_send(seen=100000-10029)
        self.run_lua('RESULT=F.RepairPostage()')
        self.assertEqual(self.run_lua('return RESULT.skipped'),1)
        self.assertEqual(len(self.kind("activity")),2)
        self.assertEqual(self.kind("mail_backfill")[0]["status"],"skipped")

    def test_postage_repair_skips_a_send_with_no_unexplained_gold_on_record(self):
        self.run_lua("""
        F.db.postageRepaired=nil
        F.Emit("mail_sent",{recipient="Bank-Realm",money=10000,postage=10030,cod=0,items={}})
        F.Claim("mail_sent",-10000,{recipient="Bank-Realm",items={}})
        F.Claim("postage",-10030,{recipient="Bank-Realm"})
        RESULT=F.RepairPostage()
        """)
        self.assertEqual(self.run_lua('return RESULT.skipped'),1)
        self.assertEqual(len([d for d in self.kind("activity") if d["category"]=="postage"]),1)

    def test_postage_repair_leaves_correct_sends_alone(self):
        self.old_mail_send(money=0,postage=120,items='{{quantity=1},{quantity=1},{quantity=1},{quantity=1}}')
        self.old_mail_send(money=10000,postage=30,seen=100000-120-10030)
        self.run_lua('F.RepairPostage()')
        self.assertEqual(self.kind("mail_backfill"),[])
        self.assertEqual(len(self.kind("activity")),4)

    def test_postage_repair_leaves_a_charge_that_is_not_the_sends_price(self):
        self.run_lua("""
        F.db.postageRepaired=nil
        F.Emit("mail_sent",{recipient="Bank-Realm",money=10000,postage=10030,cod=0,items={}})
        F.Claim("mail_sent",-10000,{recipient="Bank-Realm",items={}})
        F.Claim("postage",-5000,{recipient="Bank-Realm"})
        F.ObserveBalance(95000); F.Flush()
        F.RepairPostage()
        """)
        self.assertEqual(self.kind("reconciliation")[0]["residual"],10000)
        self.assertEqual(self.kind("mail_backfill"),[])

    def test_postage_repair_keeps_attachment_postage(self):
        items='{{quantity=1},{quantity=1},{quantity=1},{quantity=1}}'
        self.old_mail_send(money=10000,postage=10120,items=items)
        self.run_lua('F.RepairPostage()')
        self.assertEqual(sum(d["amount"] for d in self.kind("activity") if d["category"]=="postage"),-120)

    def test_postage_repair_runs_once_from_login(self):
        self.old_mail_send()
        self.run_lua("""
        F.baselined=nil; F.Init(F.db,F.identity)
        F.baselined=nil; F.Init(F.db,F.identity)
        """)
        self.assertEqual(len(self.kind("mail_backfill")),1)
        self.assertTrue(self.run_lua('return F.db.postageRepaired'))
        self.assertTrue(self.run_lua('return #MESSAGES>0'))

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

    def test_logout_zero_money_keeps_balance(self):
        self.lua.execute("assert(loadstring(...))('ForeverLedger',F)",(ROOT/"ForeverLedger"/"Main.lua").read_text())
        self.run_lua('''
        LAST_FRAME.scripts.OnEvent(nil,"ADDON_LOADED","ForeverLedger"); LAST_FRAME.scripts.OnEvent(nil,"PLAYER_LOGIN")
        KEPT=WALLET; WALLET=0; LAST_FRAME.scripts.OnEvent(nil,"PLAYER_LOGOUT")
        ''')
        self.assertEqual(self.kind("balance"),[])
        self.assertEqual(self.run_lua('return F.character.balance'),self.run_lua('return KEPT'))

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

    def test_corrected_logout_balance_is_excluded(self):
        p=self.save("one",[
            event("one",1,"baseline",dict(balance=500)),
            event("one",2,"balance",dict(before=500,after=0,delta=-500)),
            event("one",3,"reconciliation",dict(balanceIDs=["one:2"],activityIDs=[],observed=-500,explained=0,residual=-500,status="unresolved")),
            event("one",4,"balance_correction",dict(balanceID="one:2",owner="Main-Realm",amount=500))])
        ledger.import_file(self.db,p)
        report=ledger.report(self.db)
        self.assertEqual(self.db.execute("SELECT count(*) FROM cash_movements").fetchone()[0],0)
        self.assertEqual(json.dumps(report).count("-500"),0)

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

    def test_forever_surnames_and_hidden_realms_still_count_as_internal(self):
        # Each account sits on its own hidden realm, and mail names carry a surname plus
        # the sender's own realm: Modars on Realm2 mails "Setha Bank", who is on Realm6.
        a=[event("one",1,"activity",dict(category="mail_sent",amount=-100,recipient="Setha Bank-Realm2"),"Modars-Realm2"),
           event("one",2,"activity",dict(category="trade",amount=50,counterparty="Setha Bank-Realm2"),"Modars-Realm2")]
        b=[event("two",1,"activity",dict(category="mail_received",amount=100,sender="Modars Setharius-Realm6"),"Setha-Realm6"),
           event("two",2,"activity",dict(category="trade",amount=-50,counterparty="Modars Setharius-Realm6"),"Setha-Realm6"),
           event("two",3,"activity",dict(category="mail_received",amount=70,sender="Stranger Smith-Realm6"),"Setha-Realm6")]
        ledger.import_file(self.db,self.save("one",a)); ledger.import_file(self.db,self.save("two",b))
        r=ledger.report(self.db)
        self.assertEqual(r["internal_transfer_net"],0)
        self.assertEqual(r["classified_external_cash_in"],70)

    def test_character_key_ignores_realm_surname_and_case(self):
        for name in ("Setha","setha-Realm","Setha Bank","Setha Bank-CAMWOWEU5Realm6PvP"," Setha "):
            self.assertEqual(ledger.character_key(name),"setha",name)
        self.assertEqual(ledger.character_key("Grüße-Realm"),ledger.character_key("GRÜSSE"))

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

    def test_backfill_corrections_change_cash_sales_and_unresolved(self):
        events=[event("one",1,"balance",dict(delta=500,after=500)),
            event("one",2,"auction_sale",dict(item=dict(id=1),gross=500,commission=25,quantity=1)),
            event("one",3,"activity",dict(category="auction_sale",amount=500,saleID="one:2")),
            event("one",4,"auction_sale",dict(item=dict(id=1),gross=500,commission=25,quantity=1)),
            event("one",5,"activity",dict(category="auction_sale",amount=500,saleID="one:4")),
            event("one",6,"reconciliation",dict(balanceIDs=["one:1"],observed=500,explained=1000,residual=-500,status="unresolved")),
            event("one",7,"reconciliation",dict(balanceIDs=[],observed=9,explained=0,residual=9,status="unresolved")),
            event("one",8,"activity",dict(category="auction_sale",amount=-500,correctsActivityID="one:5",correctsSaleID="one:4",backfilled=True)),
            event("one",9,"mail_backfill",dict(status="applied",amount=-500,residual=-500,reconciliationIDs=["one:6"]))]
        ledger.import_file(self.db,self.save("one",events))
        r=ledger.report(self.db)
        self.assertEqual((r["classified_external_cash_in"],r["classified_external_cash_out"]),(500,0))
        self.assertEqual([u["event"] for u in r["unresolved_reconciliation"]],["one:7"])
        self.assertEqual((r["items"][0]["gross"],r["items"][0]["sold_quantity"]),(500,1))

    def test_postage_repair_changes_cash_and_unresolved(self):
        events=[event("one",1,"balance",dict(delta=-10030,after=0)),
            event("one",2,"activity",dict(category="mail_sent",amount=-10000,recipient="Other-Realm")),
            event("one",3,"activity",dict(category="postage",amount=-10030,recipient="Other-Realm")),
            event("one",4,"reconciliation",dict(balanceIDs=["one:1"],observed=-10030,explained=-20030,residual=10000,status="unresolved")),
            event("one",5,"activity",dict(category="postage",amount=10030,correctsActivityID="one:3",backfilled=True)),
            event("one",6,"activity",dict(category="postage",amount=-30,recipient="Other-Realm",backfilled=True)),
            event("one",7,"mail_backfill",dict(repair="postage",status="applied",amount=10000,residual=10000,reconciliationIDs=["one:4"]))]
        ledger.import_file(self.db,self.save("one",events))
        r=ledger.report(self.db)
        self.assertEqual(r["classified_external_cash_out"],10030)
        self.assertEqual(r["unresolved_reconciliation"],[])

    def test_report_compares_repairs_and_training_with_their_full_price(self):
        events=[event("one",1,"activity",dict(category="repair",amount=-8500,standing=7,discount=15)),
            event("one",2,"activity",dict(category="repair",amount=-9000,standing=7,discount=10)),
            event("one",3,"activity",dict(category="repair",amount=-1000,standing=4,discount=0)),
            event("one",4,"activity",dict(category="repair",amount=-500)),
            event("one",5,"activity",dict(category="repair",amount=-700,standing=6)),
            event("one",6,"activity",dict(category="training",amount=-9000,standing=6,discount=10,service="Linen Belt")),
            event("one",7,"activity",dict(category="training",amount=-300,service="Bandage"))]
        ledger.import_file(self.db,self.save("one",events))
        savings=ledger.report(self.db)["reputation_savings"]
        training=savings["training"]
        self.assertEqual((training["count"],training["paid"],training["full_price"],training["saved"]),(1,9000,10000,1000))
        self.assertEqual(training["not_compared"],{"count":1,"paid":300})
        r=savings["repair"]
        self.assertEqual((r["count"],r["paid"],r["full_price"],r["saved"]),(3,18500,21000,2500))
        self.assertEqual({k:v["saved"] for k,v in r["by_standing"].items()},
            {"Revered (15% off)":1500,"Revered (10% off)":1000,"Neutral (0% off)":0})
        self.assertEqual(r["not_compared"],{"count":2,"paid":1200})

    def test_skipped_backfill_leaves_gold_unresolved(self):
        events=[event("one",1,"reconciliation",dict(balanceIDs=[],observed=9,explained=0,residual=9,status="unresolved")),
            event("one",2,"mail_backfill",dict(status="skipped",amount=8,residual=9,reconciliationIDs=["one:1"]))]
        ledger.import_file(self.db,self.save("one",events))
        self.assertEqual(len(ledger.report(self.db)["unresolved_reconciliation"]),1)

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
