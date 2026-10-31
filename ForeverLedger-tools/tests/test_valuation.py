"""Behavioral tests using the actual addon in Lua 5.1, without a WoW client."""
import json
import unittest
import test_ledger as base


@unittest.skipIf(base.LuaRuntime is None, "Install lupa")
class ValuationTests(unittest.TestCase):
    setUp = base.AddonTests.setUp
    run_lua = base.AddonTests.run_lua
    events = base.AddonTests.events
    kind = base.AddonTests.kind

    def result(self, code):
        return json.loads(self.run_lua("return F.JSON(" + code + ")"))

    def gear(self):
        self.run_lua('''
        gear={id=999,quality=2,level=10,classID=4,vendorPrice=100}
        row={item=gear,quantity=1,bound=false}
        F.market.prices["999:0"]={price=10000,updatedAt=NOW-10}
        F.market.prices["10940:0"]={price=1000,updatedAt=NOW-10}
        F.market.prices["10938:0"]={price=1000,updatedAt=NOW-10}
        ''')

    def scanner(self, legacy=False):
        self.run_lua('''
        F.context.auction=true; F.TrackItem({id=2770,name="Copper Ore",link="item:2770"})
        SENT={}; READY=true; FULL=true; RESULTS={}
        C_AuctionHouse.SendSearchQuery=function(key) SENT[#SENT+1]=key end
        C_AuctionHouse.IsThrottledMessageSystemReady=function() return READY end
        C_AuctionHouse.HasFullCommoditySearchResults=function() return FULL end
        C_AuctionHouse.GetNumCommoditySearchResults=function() return #RESULTS end
        C_AuctionHouse.GetCommoditySearchResultInfo=function(_,i) return RESULTS[i] end
        C_AuctionHouse.RequestMoreCommoditySearchResults=function(id) SENT[#SENT+1]=id end
        C_AuctionHouse.HasFullItemSearchResults=function() return FULL end
        C_AuctionHouse.GetNumItemSearchResults=function() return #RESULTS end
        C_AuctionHouse.GetItemSearchResultInfo=function(_,i) return RESULTS[i] end
        ''')
        if legacy:
            self.run_lua('''
            F.isTBC=true
            CanSendAuctionQuery=function() return READY end
            QueryAuctionItems=function(name,lo,hi,page,usable,rarity,getAll,exact)
                assert(exact==true and getAll==false); SENT[#SENT+1]={name=name,page=page}
            end
            GetNumAuctionItems=function() return #RESULTS,TOTAL or #RESULTS end
            GetAuctionItemInfo=function(_,i)
                local r=RESULTS[i]; return "Copper Ore",nil,r.quantity,1,true,1,nil,0,0,r.price,0,nil,nil,nil,nil,0,r.id,r.loaded
            end
            GetAuctionItemLink=function(_,i) return RESULTS[i].link or "item:"..RESULTS[i].id end
            ''')

    def test_marker_prompt_and_empty_name(self):
        self.run_lua('StaticPopupDialogs={}; POPUPS=0; StaticPopup_Show=function() POPUPS=POPUPS+1 end')
        self.assertTrue(self.run_lua('return F.PromptMarker()'))
        self.assertFalse(self.run_lua('return F.SetMarker("   ")'))
        self.assertTrue(self.run_lua('return F.SetMarker(" Episode 1 ")'))
        self.assertFalse(self.run_lua('return F.PromptMarker()'))
        self.assertEqual(self.run_lua('return POPUPS'), 1)
        self.assertEqual(self.kind('episode_start')[0]['name'], 'Episode 1')

    def test_marker_popup_accepts_native_dialog_editbox(self):
        self.run_lua('''
        StaticPopupDialogs={}; StaticPopup_Show=function() end
        F.PromptMarker()
        StaticPopupDialogs.FOREVERLEDGER_MARKER.OnAccept({GetEditBox=function() return {GetText=function() return "A" end} end})
        ''')
        self.assertEqual(self.run_lua('return F.db.episode'), 'A')

    def test_boe_equipped_loses_auction_value(self):
        self.gear()
        self.assertEqual(self.result('F.ValueRow(row,F.character)')['value'], 9500)
        self.run_lua('row.equipped=true; row.bound=true')
        value=self.result('F.ValueRow(row,F.character)')
        self.assertEqual(value['value'], 100)
        self.assertNotIn('marketGross',value)

    def test_bound_de_requires_owning_character_profession(self):
        self.gear()
        self.run_lua('row.bound=true; enchanter={professions={enchanting=true,skill=300}}')
        self.assertEqual(self.result('F.ValueRow(row,enchanter)')['value'], 1425)
        self.assertEqual(self.result('F.ValueRow(row,F.character)')['value'], 100)

    def test_unequipped_soulbound_stays_salvage(self):
        self.gear()
        self.run_lua('row.bound=true; row.equipped=false')
        self.assertEqual(self.result('F.ValueRow(row,F.character)')['value'], 100)

    def test_nonbound_de_floor_includes_fees_and_vendor(self):
        self.gear()
        self.run_lua('F.market.prices["999:0"]=nil')
        self.assertEqual(self.result('F.ValueRow(row,F.character)')['value'], 1425)
        self.run_lua('gear.vendorPrice=1500')
        self.assertEqual(self.result('F.ValueRow(row,F.character)')['value'], 1500)

    def test_missing_de_material_never_sums_partial_value(self):
        self.gear()
        self.run_lua('row.bound=true; F.character.professions={enchanting=true,skill=300}; F.market.prices["10938:0"]=nil')
        value=self.result('F.ValueRow(row,F.character)')
        self.assertEqual(value['value'],100)
        self.assertTrue(value['disenchantUnpriced'])

    def test_unknown_binding_never_gets_auction_or_transfer_de(self):
        self.gear()
        self.run_lua('row.bound=nil')
        self.assertEqual(self.result('F.ValueRow(row,F.character)')['value'],100)

    def test_profession_unlearn_reduces_salvage(self):
        self.gear()
        self.run_lua('''
        GetProfessions=function() return 1 end
        GetProfessionInfo=function() return "Enchanting",nil,100,nil,nil,nil,333 end
        row.bound=true; F.ScanProfession()
        ''')
        self.assertEqual(self.result('F.ValueRow(row,F.character)')['value'],1425)
        self.run_lua('GetProfessions=function() end; F.ScanProfession()')
        self.assertEqual(self.result('F.ValueRow(row,F.character)')['value'],100)

    def test_history_is_immutable_and_components_do_not_overlap(self):
        self.gear()
        self.run_lua('''
        F.Snapshot("bags",{row},true); F.Snapshot("equipment",{},true); F.RecordValue()
        NOW=NOW+10; row.bound=true; row.equipped=true
        F.Snapshot("bags",{},true); F.Snapshot("equipment",{row},true); F.RecordValue()
        ''')
        old,new=self.kind('valuation')
        self.assertEqual((old['assets'],old['equipped']), (9500,0))
        self.assertEqual((new['assets'],new['equipped']), (0,100))
        self.assertEqual(new['total'],new['gold']+new['assets']+new['equipped'])
        points=self.run_lua('local p=F.StackHistory(F.db.history,{gold=true,assets=true,equipped=true},F.marketScope); return F.JSON(p)')
        self.assertEqual(json.loads(points)[-1]['values'][-1]['value'],100100)

    def test_history_waits_for_equipment_and_bags_to_settle(self):
        self.run_lua('F.bagDirty=CLOCK; F.RecordValue(); F.equipmentDirty=true; F.bagDirty=nil; F.RecordValue()')
        self.assertEqual(self.kind('valuation'),[])
        self.run_lua('F.equipmentDirty=nil; F.RecordValue()')
        self.assertEqual(len(self.kind('valuation')),1)

    def test_history_scope_excludes_other_realms(self):
        self.run_lua('F.db.characters.other={balance=999999,marketScope="other",snapshots={}}; F.RecordValue()')
        self.assertEqual(self.kind('valuation')[0]['gold'],100000)

    def test_instance_guid_deduplicates_stale_bank_copy(self):
        self.gear()
        self.run_lua('row.guid="same"; F.Snapshot("bank",{row},true); F.Snapshot("bags",{row},true); F.RecordValue()')
        self.assertEqual(self.kind('valuation')[0]['assets'],9500)

    def test_incremental_queue_is_all_unpriced_plus_50_oldest(self):
        self.run_lua('''
        for i=1,80 do
            F.TrackItem({id=i,name="Item"..i})
            if i<=70 then F.market.prices[i..":0"]={price=100,updatedAt=i} end
        end
        ''')
        queue=self.result('F.PriceQueue("oldest")')
        self.assertEqual(len(queue),60)
        self.assertEqual({r['item']['id'] for r in queue},set(range(1,51))|set(range(71,81)))
        self.assertEqual(len(self.result('F.PriceQueue("all")')),80)

    def test_queue_adds_needed_disenchant_materials(self):
        self.gear()
        self.run_lua('F.TrackItem(gear)')
        self.assertEqual({r['item']['id'] for r in self.result('F.PriceQueue("all")')},{999,10940,10938})

    def test_external_quote_age_is_not_time_of_read(self):
        self.run_lua('''
        Auctionator={API={v1={GetAuctionPriceByItemLink=function() return 200 end,GetAuctionAgeByItemLink=function() return 2 end}}}
        F.Item("item:2770"); NOW=NOW+10; F.Item("item:2770")
        ''')
        self.assertEqual(self.run_lua('return F.market.prices["2770:0"].updatedAt'),1800000000-172800)
        self.assertEqual(len(self.kind('price')),1)

    def test_scan_requires_ah_and_respects_throttle(self):
        self.assertFalse(self.run_lua('return F.StartPrices("all")'))
        self.scanner()
        self.run_lua('READY=false; F.StartPrices("all"); F.PriceTick()')
        self.assertEqual(self.run_lua('return #SENT'),0)
        self.run_lua('READY=true; F.PriceTick()')
        self.assertEqual(self.run_lua('return #SENT'),1)

    def test_modern_scan_ignores_wrong_item_and_consumes_full_results(self):
        self.scanner()
        self.run_lua('''
        F.StartPrices("all"); F.PriceTick(); RESULTS={{unitPrice=500},{unitPrice=200}}
        F.PriceResults("commodity",999)
        ''')
        self.assertEqual(self.kind('price'),[])
        self.run_lua('F.PriceResults("commodity",2770); F.PriceResults("commodity",2770)')
        self.assertEqual(len(self.kind('price')),1)
        self.assertEqual(self.kind('price')[0]['quote']['price'],200)

    def test_modern_partial_results_request_more_and_keep_old_price_until_complete(self):
        self.scanner()
        self.run_lua('''
        F.market.prices["2770:0"]={price=800}; FULL=false
        F.StartPrices("all"); F.PriceTick(); F.PriceResults("commodity",2770)
        CLOCK=2; F.PriceTick()
        ''')
        self.assertEqual(self.run_lua('return F.market.prices["2770:0"].price'),800)
        self.assertEqual(self.run_lua('return #SENT'),2)
        self.run_lua('FULL=true; RESULTS={{unitPrice=300}}; F.events.COMMODITY_SEARCH_RESULTS_ADDED(2770)')
        self.assertEqual(self.kind('price')[0]['quote']['price'],300)

    def test_item_scan_uses_stack_unit_price(self):
        self.scanner()
        self.run_lua('F.StartPrices("all"); F.PriceTick(); RESULTS={{quantity=20,buyoutAmount=1000}}; F.PriceResults("item",F.priceScan.itemKey)')
        self.assertEqual(self.kind('price')[0]['quote']['price'],50)

    def test_zero_results_clear_price_but_keep_item_in_unpriced_queue(self):
        self.scanner()
        self.run_lua('F.market.prices["2770:0"]={price=800}; F.StartPrices("all"); F.PriceTick(); F.PriceResults("commodity",2770)')
        self.assertNotIn('price',self.kind('price')[0]['quote'])
        self.assertEqual(len(self.result('F.PriceQueue("oldest")')),1)

    def test_timeout_or_close_does_not_overwrite_quote(self):
        self.scanner()
        self.run_lua('F.market.prices["2770:0"]={price=800}; F.StartPrices("all"); F.PriceTick(); CLOCK=31; F.PriceTick()')
        self.assertIsNone(self.run_lua('return F.priceScan'))
        self.assertEqual(self.run_lua('return F.market.prices["2770:0"].price'),800)
        self.run_lua('F.StartPrices("all"); F.events.AUCTION_HOUSE_CLOSED()')
        self.assertIsNone(self.run_lua('return F.priceScan'))

    def test_external_search_cancels_our_scan(self):
        self.scanner()
        self.run_lua('F.InstallPriceHooks(); F.StartPrices("all"); F.PriceTick()')
        self.assertIsNotNone(self.run_lua('return F.priceScan'))
        self.run_lua('C_AuctionHouse.SendSearchQuery({itemID=1})')
        self.assertIsNone(self.run_lua('return F.priceScan'))

    def test_legacy_scan_pages_and_matches_item_not_name(self):
        self.scanner(legacy=True)
        self.run_lua('''
        F.StartPrices("all"); F.PriceTick(); TOTAL=51
        RESULTS={{id=2770,quantity=5,price=500,loaded=true},{id=999,quantity=1,price=1,loaded=true}}
        F.PriceResults("legacy"); CLOCK=2; F.PriceTick()
        ''')
        self.assertEqual(self.kind('price'),[])
        self.assertEqual(self.run_lua('return SENT[2].page'),1)
        self.run_lua('RESULTS={{id=2770,quantity=10,price=800,loaded=true}}; F.PriceResults("legacy")')
        self.assertEqual(self.kind('price')[0]['quote']['price'],80)

    def test_legacy_incomplete_item_cache_waits(self):
        self.scanner(legacy=True)
        self.run_lua('F.StartPrices("all"); F.PriceTick(); RESULTS={{id=2770,quantity=1,price=100,loaded=false}}; F.PriceResults("legacy")')
        self.assertEqual(self.kind('price'),[])
        self.run_lua('RESULTS[1].loaded=true; F.PriceResults("legacy")')
        self.assertEqual(self.kind('price')[0]['quote']['price'],100)

    def test_suffix_variants_have_separate_prices(self):
        self.assertNotEqual(self.run_lua('return F.PriceKey({id=1,link="item:1:0:0:0:0:0:123:0"})'),
                            self.run_lua('return F.PriceKey({id=1,link="item:1:0:0:0:0:0:124:0"})'))

    def test_tbc_flavor_detected_and_unsupported_de_is_not_guessed(self):
        self.run_lua('GetBuildInfo=function() return "2.5.6" end; F.InitValuation()')
        self.assertTrue(self.run_lua('return F.isTBC and F.LegacyAH()'))
        self.assertIsNone(self.run_lua('return F.DEOutcomes({quality=2,level=100,classID=4,expansionID=1})'))

    def test_valuation_export_sql_views(self):
        self.gear()
        self.run_lua('F.Snapshot("bags",{row},true); F.RecordValue()')
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'ledger.json'
            path.write_text(self.run_lua('return F.Export(1,10000)'),encoding='utf-8')
            db=base.ledger.connect(':memory:')
            base.ledger.import_file(db,path)
            self.assertEqual(db.execute('SELECT total FROM valuations').fetchone()[0],109500)
            report=base.ledger.report(db)
            self.assertEqual(report['latest_valuations'][0]['assets'],9500)
            self.assertEqual(report['latest_snapshots'][0]['estimated_net_value'],9500)
            base.ledger.export_csv(db,folder)
            self.assertTrue((Path(folder)/'valuations.csv').exists())
            db.close()

    def test_native_menu_wiring_and_stacked_geometry(self):
        self.run_lua(r'''
        WIDGETS={}; function date(fmt,t) return os.date(fmt,t) end
        local function widget()
            local w={shown=true,scripts={},text=""}; WIDGETS[#WIDGETS+1]=w
            for _,method in ipairs({"SetPoint","SetAllPoints","SetColorTexture","SetThickness","SetWidth","SetHeight",
                "SetJustifyH","SetTextColor","SetMovable","EnableMouse","RegisterForDrag","SetFontObject","SetClampedToScreen",
                "SetMultiLine","SetAutoFocus","SetMaxLetters","SetScrollChild","SetCursorPosition","ClearAllPoints",
                "SetVerticalScroll","SetFocus","ClearFocus","HighlightText","StartMoving","StopMovingOrSizing"}) do
                w[method]=function() end
            end
            function w:SetText(text) self.text=text; if self.scripts.OnTextChanged then self.scripts.OnTextChanged(self) end end
            function w:SetSize(x,y) self.width=x; self.height=y end
            function w:SetScript(name,fn) self.scripts[name]=fn end
            function w:GetFont() return "mock",12 end
            function w:GetNumLines() return 20 end
            function w:SetShown(shown) self.shown=shown end
            function w:IsShown() return self.shown end
            function w:Hide() self.shown=false end
            function w:Show() self.shown=true end
            function w:SetChecked(v) self.checked=v end
            function w:GetChecked() return self.checked end
            function w:CreateFontString() return widget() end
            function w:CreateTexture() return widget() end
            function w:CreateLine() return widget() end
            function w:SetStartPoint(point,relative,x,y) assert(point=="BOTTOMLEFT" and type(relative)=="table"); self.start={x=x,y=y} end
            function w:SetEndPoint(point,relative,x,y) assert(point=="BOTTOMLEFT" and type(relative)=="table"); self.finish={x=x,y=y} end
            return w
        end
        function CreateFrame() local w=widget(); w.TitleText=widget(); return w end
        F.RecordValue(); NOW=NOW+10; F.ObserveBalance(110000); F.RecordValue()
        F.Show()
        assert(F.chart:IsShown() and F.scanControls:IsShown())
        assert(#F.chart.lines==3 and F.chart.lines[3].finish.y==230)
        F.chart.checks.assets:SetChecked(false); F.chart.checks.assets.scripts.OnClick(F.chart.checks.assets)
        assert(not F.db.settings.chart.assets and F.db.settings.chart.equipped)
        F.Show("export"); assert(not F.chart:IsShown() and not F.scanControls:IsShown())
        F.Show("journal"); F.Show("summary")
        assert(F.chart:IsShown() and F.window:IsShown())
        ''')

    def test_bag_and_equipment_events_capture_live_binding(self):
        self.gear()
        self.run_lua('''
        C_Item.GetItemInfo=function(link) return "Sword",link,2,10,1,"Weapon","Sword",1,"INVTYPE_WEAPON",1,100,2,7,2,0 end
        BAGS[0]={{hyperlink="item:999",itemID=999,stackCount=1,isBound=false}}
        F.ScanBags(true); F.ScanEquipment(); F.RecordValue()
        NOW=NOW+5; BAGS[0]={}; GetInventoryItemLink=function(_,slot) if slot==16 then return "item:999" end end
        F.events.PLAYER_EQUIPMENT_CHANGED(); F.RecordValue()
        CLOCK=1; F.bagDirty=nil; F.equipmentDirty=nil; F.ScanBags(); F.ScanEquipment(); F.RecordValue()
        ''')
        values=self.kind('valuation')
        self.assertEqual(len(values),2)
        self.assertEqual(values[0]['assets'],9500)
        self.assertEqual(values[1]['equipped'],100)
        self.assertEqual(values[1]['assets'],0)

    def test_schema_one_upgrade_preserves_existing_events(self):
        self.run_lua('''
        F.Emit("old",{amount=123}); local db=F.db
        db.markets=nil; db.history=nil; F.Init(db,F.identity)
        F.ObserveBalance(WALLET); F.RecordValue()
        ''')
        self.assertEqual(len(self.kind('old')),1)
        self.assertEqual(len(self.kind('valuation')),1)


if __name__ == '__main__':
    unittest.main()
