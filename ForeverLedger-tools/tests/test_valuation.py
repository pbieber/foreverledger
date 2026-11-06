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

    def test_price_falls_back_to_the_latest_quote_from_another_hidden_realm(self):
        self.assertEqual(self.result('''(function()
            F.db.markets={
                ["forever:CAMWOWEU5Realm2PvP:Horde"]={catalog={},prices={["2770:0"]={price=50,retrievedAt=1}}},
                ["forever:CAMWOWEU5Realm6PvP:Horde"]={catalog={},prices={["2770:0"]={price=70,retrievedAt=2}}},
                ["forever:CAMWOWEU4Realm1PvP:Horde"]={catalog={},prices={["2770:0"]={price=999,retrievedAt=9}}},
                ["forever:CAMWOWEU5Realm5PvP:Horde"]={catalog={},prices={["2775:0"]={price=8,retrievedAt=0}}},
            }
            local here="forever:CAMWOWEU5Realm5PvP:Horde"
            return {(F.Price({id=2770},here)),(F.Price({id=2775},here)),
                (F.Price({id=2770},"forever:CAMWOWEU5Realm5PvP:Alliance")),(F.Price({id=1},here))}
        end)()'''), [70, 8])

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
        points=self.run_lua('local p=F.StackHistory(F.db.history,{gold=true,assets=true,equipped=true},F.marketScope,F.SelectedCharacters(),10,NOW); return F.JSON(p)')
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

    def install_widgets(self):
        self.run_lua(r'''
        WIDGETS={}; function date(fmt,t) return os.date(fmt,t) end
        local function widget()
            local w={shown=true,scripts={},text=""}; WIDGETS[#WIDGETS+1]=w
            for _,method in ipairs({"SetPoint","SetAllPoints","SetColorTexture","SetThickness","SetWidth","SetHeight",
                "SetJustifyH","SetTextColor","SetMovable","EnableMouse","RegisterForDrag","SetFontObject","SetClampedToScreen",
                "SetMultiLine","SetAutoFocus","SetMaxLetters","SetScrollChild","SetCursorPosition","ClearAllPoints",
                "SetVerticalScroll","SetFocus","ClearFocus","HighlightText","StartMoving","StopMovingOrSizing","SetFrameStrata","SetVertexColor",
                "SetStatusBarTexture","SetMinMaxValues","SetSnapToPixelGrid","SetTexelSnappingBias","SetWordWrap"}) do
                w[method]=function() end
            end
            function w:SetText(text) self.text=text; if self.scripts.OnTextChanged then self.scripts.OnTextChanged(self) end end
            function w:SetSize(x,y) self.width=x; self.height=y end
            function w:SetWidth(x) self.width=x end
            function w:SetColorTexture(r,g,b) self.color={r,g,b} end
            function w:SetScript(name,fn) self.scripts[name]=fn end
            function w:GetFont() return "mock",12 end
            function w:GetStringHeight() return 600 end
            function w:GetNumLines() return 20 end
            function w:SetShown(shown) self.shown=shown end
            function w:IsShown() return self.shown end
            function w:Hide() self.shown=false end
            function w:Show() self.shown=true end
            function w:SetChecked(v) self.checked=v end
            function w:SetValue(v) self.value=v end
            function w:SetStatusBarColor(r,g,b) self.color={r,g,b} end
            function w:GetChecked() return self.checked end
            function w:SetDrawLayer(_,sublevel) self.layer=sublevel end
            function w:SetTexture(path) self.texture=path end
            function w:SetTexCoord() end
            function w:SetVertexColor(r,g,b) self.color={r,g,b} end
            function w:LockHighlight() self.locked=true end
            function w:UnlockHighlight() self.locked=false end
            function w:SetVertexOffset(i,x,y) self.offsets=self.offsets or {}; self.offsets[i]={x=x,y=y} end
            function w:ClearAllPoints() self.anchors={} end
            function w:SetPoint(point,...)
                self.anchors=self.anchors or {}
                local n=select("#",...)
                if n>=2 then self.anchors[point]={x=select(n-1,...),y=select(n,...)} end
            end
            function w:CreateFontString() return widget() end
            function w:CreateTexture() return widget() end
            return w
        end
        UPPER_LEFT_VERTEX,LOWER_LEFT_VERTEX,UPPER_RIGHT_VERTEX,LOWER_RIGHT_VERTEX=1,2,3,4
        -- Where a drawn texture's four corners end up.
        function CORNERS(t)
            local box,top=t.anchors.BOTTOMLEFT,t.anchors.TOPRIGHT
            local function at(i,x,y) return {x=x+t.offsets[i].x,y=y+t.offsets[i].y} end
            return at(UPPER_LEFT_VERTEX,box.x,top.y),at(UPPER_RIGHT_VERTEX,top.x,top.y),
                at(LOWER_LEFT_VERTEX,box.x,box.y),at(LOWER_RIGHT_VERTEX,top.x,box.y)
        end
        function CreateFrame() local w=widget(); w.TitleText=widget(); return w end
        TIP={}
        GameTooltip={SetOwner=function() TIP={} end,AddLine=function(_,text) TIP[#TIP+1]=text end,
            AddDoubleLine=function(_,left) TIP[#TIP+1]=left end,Show=function() end,Hide=function() TIP={} end,
            IsOwned=function() return true end}
        ''')

    def test_native_menu_wiring_and_stacked_geometry(self):
        self.install_widgets()
        self.run_lua(r'''
        F.RecordValue(); NOW=NOW+10; F.ObserveBalance(110000); F.RecordValue()
        F.Show()
        assert(F.chart:IsShown() and F.scanControls:IsShown())
        local shownLines=0
        for _,line in ipairs(F.chart.lines) do if line:IsShown() then shownLines=shownLines+1 end end
        local upperLeft,upperRight,lowerLeft,lowerRight=CORNERS(F.chart.lines[shownLines])
        assert(math.abs((upperRight.y+lowerRight.y)/2-F.chart.points[#F.chart.points].values[3].value/F.chart.maximum*266)<0.001)
        assert(#F.chart.fills>0 and F.chart.maximum>F.chart.points[#F.chart.points].values[3].value)
        assert(not F.recordsBar:IsShown())
        for _,key in ipairs({"value","gold","gain"}) do assert(F.chart.stats[key].value.text:find("UI-GoldIcon",1,true)) end
        assert(F.mode=="overview" and not F.summaryScroll:IsShown() and not F.scroll:IsShown())
        assert(F.chart.selector.text=="Characters: 1/1")
        assert(F.chart.metric.text=="All value")
        F.chart.checks.assets:SetChecked(false); F.chart.checks.assets.scripts.OnClick(F.chart.checks.assets)
        assert(F.chart.metric.text=="Gold + Gear")
        assert(not F.db.settings.chart.assets and F.db.settings.chart.equipped)
        F.Show("export"); assert(not F.chart:IsShown() and not F.scanControls:IsShown() and F.recordsBar:IsShown())
        for i=1,120 do F.Emit("note",{}) end
        F.Show("journal",2); assert(F.page==2 and F.footer.text:find("Records page 2",1,true) and F.edit.text:find("note",1,true))
        F.Show("summary")
        assert(F.summaryScroll:IsShown() and not F.chart:IsShown() and not F.recordsBar:IsShown() and not F.scroll:IsShown())
        assert(F.summaryText.text:find("Recorded characters",1,true) and F.summaryText.text:find("UI-GoldIcon",1,true))
        F.Show("journal"); assert(F.scroll:IsShown() and not F.summaryScroll:IsShown()); F.Show()
        assert(F.chart:IsShown() and F.window:IsShown() and not F.summaryScroll:IsShown())
        local plot=F.chart.plot
        function plot:IsMouseOver() return true end
        function plot:GetLeft() return 0 end
        function plot:GetBottom() return 0 end
        function plot:GetEffectiveScale() return 1 end
        local last=F.chart.points[#F.chart.points]
        function GetCursorPosition() return 550,last.values[1].value/F.chart.maximum*266 end
        assert(F.chart.characters and last.totals.total>0)
        plot.scripts.OnUpdate(plot)
        assert(F.chart.cross:IsShown() and F.chart.total.text:find("Total",1,true))
        assert(TIP[1]=="Gold" and #TIP>1)
        plot.scripts.OnLeave()
        assert(not F.chart.cross:IsShown() and #TIP==0)
        ''')

    def test_window_is_thirty_percent_smaller_and_controls_fit(self):
        self.install_widgets()
        self.run_lua(r"""
        F.Show()
        assert(F.window.width==644 and F.window.height==532)
        local plot=F.chart.plot
        assert(plot.anchors.TOPLEFT.x+plot.width<=F.chart.width and -plot.anchors.TOPLEFT.y+plot.height<=F.chart.height)
        assert(16+F.chart.width<=F.window.width-16)
        assert(F.scanControls.anchors.TOPLEFT.y<=F.chart.anchors.TOPLEFT.y-F.chart.height+2)
        assert(-F.scanControls.anchors.TOPLEFT.y+F.scanControls.height<=F.window.height-17)
        for _,w in ipairs(WIDGETS) do
            local at=w.anchors and w.anchors.TOPLEFT
            if at and w.width and (w.text=="Sync" or w.text=="Set marker") then assert(at.x+w.width<=F.window.width-16) end
            if at and w.width==84 then assert(at.x%88==16%88) end
        end
        for _,key in ipairs({"gold","assets","equipped"}) do assert(F.chart.checks[key].anchors.TOPLEFT.x<F.chart.width) end
        """)

    def test_stats_stack_and_top_axis_label_clears_the_controls(self):
        self.install_widgets()
        self.run_lua(r"""
        F.RecordValue(); F.Show()
        local c=F.chart
        local value,gold,gain=c.stats.value,c.stats.gold,c.stats.gain
        assert(value.anchors.TOPLEFT.y>gold.anchors.TOPLEFT.y and gold.anchors.TOPLEFT.y>gain.anchors.TOPLEFT.y)
        assert(gold.anchors.TOPLEFT.y==value.anchors.TOPLEFT.y-value.height and value.anchors.TOPLEFT.x==gain.anchors.TOPLEFT.x)
        local controls=c.selector.anchors.TOPLEFT.y
        assert(gain.anchors.TOPLEFT.y-gain.height>=controls)
        local axisTop
        for _,axis in ipairs(c.axis) do
            if axis.shown then axisTop=math.max(axisTop or axis.anchors.TOPLEFT.y,axis.anchors.TOPLEFT.y) end
        end
        assert(axisTop<=controls-c.selector.height-2)
        assert(-c.hover.anchors.TOPLEFT.y+12<=c.height)
        for _,w in ipairs(WIDGETS) do assert(not tostring(w.text):find("Equal time steps",1,true)) end
        """)

    def test_highlights_are_their_own_records_numbered_per_marker(self):
        self.run_lua('date=os.date; F.Command("highlight  Big sale ")')
        before=len(self.events())
        self.run_lua('F.SetMarker("Episode 4"); NOW=NOW+75; F.MarkHighlight(); NOW=NOW+3725; F.Command("hl Crafted it")')
        self.run_lua('NOW=NOW+5; F.MarkHighlight(); F.Command("highlight undo")')
        first,*rest=self.result("F.Highlights()")
        self.assertEqual((first["number"],first["note"],first["zone"],first["subzone"]),(1,"Big sale","Elwynn","Goldshire"))
        self.assertNotIn("since",first)
        self.assertEqual([(h["number"],h["since"],h["marker"],h.get("note")) for h in rest],
                         [(1,75,"Episode 4",None),(2,3800,"Episode 4","Crafted it")])
        self.assertEqual(self.run_lua('return F.Duration(3800)'),"1:03:20")
        removed=self.kind("highlight_removed")
        self.assertEqual(len(removed),1)
        self.assertEqual(len(self.kind("highlight")),4)
        # Marking never moves gold or adds anything for the value figures to read.
        kinds={e["kind"] for e in self.events()[before:]}
        self.assertLessEqual(kinds,{"episode_start","valuation","highlight","highlight_removed"})
        self.assertEqual(self.kind("balance"),[])
        self.assertIn("(+1:03:20): Crafted it",self.run_lua('return MESSAGES[#MESSAGES-2][1]'))

    def test_highlights_sit_on_their_own_timeline_under_the_plot(self):
        self.install_widgets()
        self.run_lua(r"""
        F.RecordValue(); NOW=NOW+100; F.ObserveBalance(110000); F.RecordValue()
        F.Show()
        local c=F.chart
        assert(c.timelineEmpty:IsShown())
        NOW=NOW-50; F.MarkHighlight("Big sale"); F.MarkHighlight(); NOW=NOW+50
        F.ObserveBalance(120000); F.RecordValue(); F.RefreshChart()
        assert(not c.timelineEmpty:IsShown() and #c.highlightGroups==1 and #c.highlightGroups[1]==2)
        local plot,line=c.plot.anchors.TOPLEFT,c.timeline.anchors.TOPLEFT
        assert(line.x==plot.x and c.timeline.width==c.plot.width)
        assert(line.y<plot.y-c.plot.height and c.startTime.anchors.TOPLEFT.y<=line.y-c.timeline.height)
        assert(-c.hover.anchors.TOPLEFT.y+12<=c.height)
        local tick=c.ticks[1]
        local x=(NOW-50-c.first)/c.span*c.plot.width
        assert(tick.shown and math.abs(tick.x-x)<0.001)
        tick.scripts.OnEnter(tick)
        assert(TIP[1]=="Highlight 1" and TIP[2]=="Big sale" and c.cross:IsShown())
        local found
        for _,t in ipairs(TIP) do if t=="Highlight 2" then found=true end end
        assert(found)
        tick.scripts.OnLeave(tick); assert(not c.cross:IsShown())
        -- Only the selected characters' highlights show.
        F.db.settings.chartCharacters={}; F.RefreshChart()
        assert(not c.ticks[1].shown)
        """)

    def test_minimap_shift_click_and_the_window_button_mark_highlights(self):
        self.install_widgets()
        self.run_lua(r"""
        Minimap={GetWidth=function() return 140 end}; GetMinimapShape=nil
        local create=CreateFrame
        function CreateFrame(...)
            local w=create(...)
            for _,m in ipairs({"RegisterForClicks","SetFrameLevel","SetHighlightTexture"}) do w[m]=function() end end
            return w
        end
        F.InstallMinimap(); F.Show()
        SHIFT=true; function IsShiftKeyDown() return SHIFT end
        F.minimapButton.scripts.OnClick(); assert(#F.Highlights()==1)
        SHIFT=false; F.minimapButton.scripts.OnClick(); assert(#F.Highlights()==1 and not F.window:IsShown())
        F.Show()
        for _,w in ipairs(WIDGETS) do
            if w.text=="Mark highlight" then
                assert(w.anchors.TOPLEFT.x+w.width<=F.scanControls.width); w.scripts.OnClick()
            end
        end
        assert(#F.Highlights()==2)
        """)

    def listed(self):
        self.run_lua(r"""
        F.character.snapshots.auctions={data={rows={
            {status=0,auctionKey="Player-Main:7",quantity=1,totalBuyout=100000,item={id=7,vendorPrice=500}},
            {status=0,quantity=10,totalBuyout=200000,item={id=33872,vendorPrice=150}},
            {status=0,quantity=5,totalBuyout=50000,item={id=16023,vendorPrice=10000}},
            {status=0,quantity=1,totalBuyout=9000,item={id=4,vendorPrice=0}},
            {status=0,quantity=1,totalBuyout=0,bid=0,minBid=3000,item={id=5,vendorPrice=100}},
            {status=1,quantity=1,totalBuyout=777777,item={id=6,vendorPrice=100}},
        }}}
        F.db.auctions["Player-Main:7"]={deposit=1234}
        F.Claim("auction_deposit",-1800,{item={id=33872},quantity=20})
        """)

    def test_on_sale_sums_active_listings_and_prefers_recorded_deposits(self):
        self.listed()
        sale=self.result('F.OnSale({["Player-Main"]=true})')
        self.assertEqual(sale["count"],5)
        self.assertEqual(sale["total"],100000+200000+50000+9000+3000)
        # Recorded for the auction 1234, recorded per unit 900, vendor rate 30000 and 60.
        self.assertEqual(sale["deposit"],1234+900+30000+0+60)
        self.assertEqual(sale["estimated"],3)
        self.assertEqual(sale["cut"],18100)

    def test_on_sale_cut_follows_the_commission_setting(self):
        self.listed()
        self.run_lua('F.db.settings.commissionBps=1500')
        self.assertEqual(self.result('F.OnSale({["Player-Main"]=true})')["cut"],54300)

    def test_on_sale_follows_the_selected_characters(self):
        self.listed()
        self.run_lua('F.db.characters["Player-Alt"]={name="Alt-Realm",snapshots={},marketScope=F.marketScope}')
        self.assertEqual(self.result('F.OnSale({["Player-Alt"]=true})')["total"],0)
        self.assertEqual(self.result('F.OnSale({})')["cut"],0)

    def test_deposit_recorded_after_the_first_read_is_used(self):
        self.listed()
        self.result('F.OnSale({["Player-Main"]=true})')
        self.run_lua('F.Claim("auction_deposit",-5000,{item={id=16023},quantity=5})')
        sale=self.result('F.OnSale({["Player-Main"]=true})')
        self.assertEqual((sale["deposit"],sale["estimated"]),(1234+900+5000+0+60,2))

    def test_on_sale_and_cost_to_list_sit_right_aligned_beside_the_stats(self):
        self.install_widgets()
        self.listed()
        self.run_lua(r"""
        F.RecordValue(true); F.Show()
        local stats=F.chart.stats
        assert(stats.sale.anchors.TOPRIGHT.x==0 and stats.sale.anchors.TOPRIGHT.y==stats.value.anchors.TOPLEFT.y)
        assert(stats.listing.anchors.TOPRIGHT.x==0 and stats.listing.anchors.TOPRIGHT.y==stats.gold.anchors.TOPLEFT.y)
        assert(stats.sale.value.text==F.MoneyShort(362000) and stats.listing.value.text==F.MoneyShort(32194))
        local function tip(key) stats[key].scripts.OnEnter(stats[key]); return table.concat(TIP,"\n") end
        assert(tip("sale"):find("5 listings",1,true))
        local cost=tip("listing")
        assert(cost:find("Auction house cut if all sell",1,true) and cost:find("3 estimated",1,true))
        stats.listing.scripts.OnLeave(stats.listing); assert(#TIP==0)
        """)

    def test_stat_hovers_show_their_breakdowns(self):
        self.install_widgets()
        self.run_lua(r"""
        F.db.characters["Player-Alt"]={name="Alt-Realm",balance=5000,marketScope=F.marketScope,snapshots={}}
        F.RecordValue(true); F.db.history[#F.db.history].unpricedRows=3; F.Show()
        local stats=F.chart.stats
        local function tip(key) stats[key].scripts.OnEnter(stats[key]); return table.concat(TIP,"\n") end
        local value=tip("value")
        assert(value:find("Total Value",1,true) and value:find("Other assets",1,true) and value:find("Equipped Gear",1,true))
        assert(value:find("Alt",1,true) and value:find("3 partly valued rows",1,true))
        local gold=tip("gold")
        assert(gold:find("Alt",1,true) and not gold:find("Equipped Gear",1,true))
        assert(tip("gain"):find("Since",1,true))
        stats.gain.scripts.OnLeave(stats.gain); assert(#TIP==0)
        local series,people=F.ValueRows(F.chart.points[#F.chart.points],F.chart.characters)
        local sum=0
        for _,r in ipairs(series) do sum=sum+r.value end
        assert(sum==F.chart.points[#F.chart.points].totals.total)
        local byPerson=0
        for _,r in ipairs(people) do byPerson=byPerson+r.value end
        assert(byPerson==sum and #people==2)
        """)

    def breakdown(self):
        return json.loads(self.run_lua('''
        local gain,rows=F.GainBreakdown(F.SelectedCharacters(),NOW)
        local out={gain=gain}
        for _,r in ipairs(rows) do out[r.label]=r.value end
        return F.JSON(out)
        '''))

    def test_backfilled_gold_counts_when_it_happened(self):
        self.gain_setup()
        self.run_lua("""
        NOW=NOW+60
        local yesterday=F.Emit("activity",{category="auction_sale",amount=400,occurredAt=TODAY-3600,item={name="Ore"}})
        local today=F.Emit("activity",{category="auction_sale",amount=70,occurredAt=TODAY+700,item={name="Ore"}})
        F.character.balance=2500+1300; F.RecordValue(true)
        """)
        got=self.breakdown()
        self.assertEqual(got["Auction house sales"],70)
        self.assertEqual(got["gain"],sum(v for k,v in got.items() if k!="gain"))
        sold=self.result('(function() local _,t=F.CategoryProfit(F.SelectedCharacters(),TODAY); return t.sold end)()')
        self.assertEqual(sold,70)
        self.assertEqual(self.result('(function() local _,t=F.CategoryProfit(F.SelectedCharacters(),0); return t.sold end)()'),470)

    def test_postage_repair_shows_only_the_real_postage(self):
        self.gain_setup()
        self.run_lua("""
        NOW=NOW+60
        local bad=F.Emit("activity",{category="postage",amount=-10030})
        F.Emit("activity",{category="postage",amount=10030,occurredAt=bad.time,correctsActivityID=bad.id})
        F.Emit("activity",{category="postage",amount=-30,occurredAt=bad.time})
        F.Emit("activity",{category="mail_sent",amount=-10000})
        F.character.balance=2500-10030+1300; F.RecordValue(true)
        """)
        got=self.breakdown()
        self.assertEqual(got["Postage"],-30)
        self.assertEqual(got["Mail sent"],-10000)
        self.assertEqual(got["gain"],sum(v for k,v in got.items() if k!="gain"))

    def test_backfill_found_in_a_later_session_does_not_stop_older_counts(self):
        self.gain_setup()
        self.run_lua("""
        NOW=NOW+60
        F.Claim("loot",10,{}); F.Emit("activity",{category="loot",amount=5,occurredAt=TODAY-90000})
        F.Claim("loot",20,{})
        """)
        self.assertEqual(self.breakdown()["Loot"],30)

    def test_gain_breakdown_splits_by_cause_and_adds_up(self):
        self.gain_setup()
        self.run_lua('''
        NOW=NOW+60; F.Claim("loot",300,{})
        F.Claim("quest",200,{})
        F.Claim("repair",-150,{})
        F.Claim("auction_sale",1000,{})
        F.Claim("auction_deposit",-40,{}); F.Claim("auction_cancel_fee",-10,{})
        F.Claim("quest",0,{})
        F.Intent("flight",-999,{})
        F.character.balance=2500+1300+25; F.RecordValue(true)
        ''')
        got=self.breakdown()
        self.assertEqual(got,{"gain":1825,"Auction house sales":1000,"Loot":300,"Quest rewards":200,
            "Repair costs":-150,"Auction house fees":-50,"Not identified":525})
        self.assertEqual(got["gain"],sum(v for k,v in got.items() if k!="gain"))

    def test_gain_breakdown_ignores_records_before_it_starts_counting(self):
        self.gain_setup()
        self.run_lua('''
        local yesterday=F.Claim("loot",7777,{}); yesterday.time=TODAY-3600
        table.remove(F.db.events); table.insert(F.db.events,1,yesterday)
        NOW=NOW+60; F.Claim("loot",100,{}); F.character.balance=2600; F.RecordValue(true)
        ''')
        got=self.breakdown()
        self.assertEqual(got["Loot"],100)
        self.assertEqual(got["gain"],600)
        self.assertEqual(got["Not identified"],500)

    def test_gain_breakdown_starts_new_character_at_its_first_sample(self):
        self.gain_setup()
        self.run_lua('''
        F.Claim("loot",40,{}).character="Player-New"
        NOW=NOW+60
        F.db.characters["Player-New"]={name="New-Realm",balance=1000,marketScope=F.marketScope,snapshots={}}
        F.RecordValue(true)
        NOW=NOW+60; F.Claim("quest",50,{}).character="Player-New"
        F.db.characters["Player-New"].balance=1050; F.RecordValue(true)
        ''')
        got=self.breakdown()
        self.assertEqual(got.get("Quest rewards"),50)
        self.assertNotIn("Loot",got)
        self.assertEqual(got["gain"],sum(v for k,v in got.items() if k!="gain"))

    def test_gain_breakdown_keeps_linked_accounts_as_one_row(self):
        self.gain_setup()
        self.run_lua('''
        F.db.peers.other={label="Bank",key="k",names={},characters={Bank={name="Bank-Realm",marketScope=F.marketScope}},
            history={{time=TODAY+100,scope=F.marketScope,chars={Bank={gold=1000}}},
                     {time=TODAY+200,scope=F.marketScope,chars={Bank={gold=1800}}}}}
        NOW=NOW+60; F.Claim("loot",100,{}); F.character.balance=2600; F.RecordValue(true)
        ''')
        got=self.breakdown()
        self.assertEqual(got["Linked accounts"],800)
        self.assertEqual(got["Loot"],100)
        self.assertEqual(got["gain"],sum(v for k,v in got.items() if k!="gain"))

    def test_legacy_auction_bid_is_recorded_as_a_purchase(self):
        self.run_lua('''
        local hooks={}
        function hooksecurefunc(name,fn) hooks[name]=fn end
        function PlaceAuctionBid() end
        function GetAuctionItemLink() return "item:5" end
        function GetAuctionItemInfo() return "Ore",nil,20 end
        F.InstallHooks()
        hooks.PlaceAuctionBid("list",1,500)
        ''')
        self.assertEqual(self.run_lua('return F.intents[#F.intents].event.data.category'),"auction_purchase_or_bid")
        self.assertEqual(self.run_lua('return F.intents[#F.intents].event.data.amount'),-500)
        self.assertEqual(self.run_lua('return F.intents[#F.intents].event.data.details.quantity'),20)

    def post_setup(self,deposit=30):
        self.run_lua('''
        HOOKS={}
        function hooksecurefunc(name,fn) HOOKS[name]=fn end
        function PostAuction() end
        DEPOSITS={}
        function GetAuctionDeposit(runTime,bid,buyout,stackSize,numStacks)
            DEPOSITS[#DEPOSITS+1]={runTime=runTime,stackSize=stackSize,numStacks=numStacks}
            return DEPOSIT*stackSize*numStacks
        end
        function GetAuctionSellItemInfo() return "Linen",1,5,1,true,10,2,5,5,2589 end
        F.isTBC=true
        DEPOSIT=%d
        F.InstallHooks()
        F.ObserveBalance(100000); F.Flush()
        function charge(amount) F.ObserveBalance(F.character.balance-amount); F.Flush() end
        function deposits()
            local sum,count=0,0
            for _,e in ipairs(F.db.events) do
                if e.kind=="activity" and e.data.category=="auction_deposit" then sum=sum+e.data.amount; count=count+1 end
            end
            return F.JSON({sum=sum,count=count,unresolved=F.db.events[#F.db.events].data.residual})
        end
        ''' % deposit)

    def test_legacy_post_records_its_deposit(self):
        self.post_setup()
        self.run_lua('HOOKS.PostAuction(100,200,2,5,1,false); charge(150)')
        self.assertEqual(json.loads(self.run_lua('return deposits()')),{"sum":-150,"count":1,"unresolved":0})
        self.assertEqual(json.loads(self.run_lua('return F.JSON(DEPOSITS[1])')),{"runTime":2,"stackSize":5,"numStacks":1})
        item=json.loads(self.run_lua('for i=#F.db.events,1,-1 do local e=F.db.events[i]; if e.kind=="activity" then return F.JSON({id=e.data.item.id,name=e.data.item.name}) end end'))
        self.assertEqual(item,{"id":2589,"name":"Linen"})

    def test_multi_stack_deposit_flushed_in_parts_is_fully_recorded(self):
        self.post_setup()
        self.run_lua('HOOKS.PostAuction(100,200,1,5,4,false); charge(150)')
        self.assertEqual(json.loads(self.run_lua('return deposits()')),{"sum":-150,"count":1,"unresolved":0})
        self.run_lua('charge(300)')
        self.assertEqual(json.loads(self.run_lua('return deposits()')),{"sum":-450,"count":3,"unresolved":0})
        self.run_lua('charge(150)')
        self.assertEqual(json.loads(self.run_lua('return deposits()')),{"sum":-600,"count":4,"unresolved":0})

    def test_long_multi_stack_post_stays_recognised_past_the_usual_window(self):
        self.post_setup()
        self.run_lua('HOOKS.PostAuction(100,200,1,5,10,false); CLOCK=(CLOCK or 0)+30; F.ObserveBalance(F.character.balance-1500); F.Flush()')
        self.assertEqual(json.loads(self.run_lua('return deposits()')),{"sum":-1500,"count":10,"unresolved":0})

    def test_quick_posts_of_different_items_are_recorded_in_order(self):
        self.post_setup()
        self.run_lua('HOOKS.PostAuction(100,200,1,5,1,false); HOOKS.PostAuction(100,200,1,2,1,false); charge(150)')
        self.assertEqual(json.loads(self.run_lua('return deposits()')),{"sum":-150,"count":1,"unresolved":0})
        self.run_lua('charge(60)')
        self.assertEqual(json.loads(self.run_lua('return deposits()')),{"sum":-210,"count":2,"unresolved":0})

    def test_post_confirmed_after_warning_records_one_deposit(self):
        self.post_setup()
        self.run_lua('HOOKS.PostAuction(100,200,1,5,1,false); HOOKS.PostAuction(100,200,1,5,1,true); charge(150)')
        self.assertEqual(json.loads(self.run_lua('return deposits()')),{"sum":-150,"count":1,"unresolved":0})

    def test_spend_not_matching_a_pending_deposit_stays_unresolved(self):
        self.post_setup()
        self.run_lua('HOOKS.PostAuction(100,200,1,5,2,false); charge(100)')
        self.assertEqual(json.loads(self.run_lua('return deposits()')),{"sum":0,"count":0,"unresolved":-100})

    def test_deposit_is_not_guessed_when_the_client_gives_none(self):
        self.post_setup()
        self.run_lua('function GetAuctionDeposit() return nil end; HOOKS.PostAuction(100,200,1,5,1,false); charge(150)')
        self.assertEqual(json.loads(self.run_lua('return deposits()')),{"sum":0,"count":0,"unresolved":-150})

    def test_modern_client_does_not_record_legacy_deposits(self):
        self.post_setup()
        self.run_lua('F.isTBC=false; C_AuctionHouse=C_AuctionHouse or {}; C_AuctionHouse.SendSearchQuery=function() end')
        self.run_lua('HOOKS.PostAuction(100,200,1,5,1,false); charge(150)')
        self.assertEqual(json.loads(self.run_lua('return deposits()')),{"sum":0,"count":0,"unresolved":-150})

    def test_deposit_appears_under_auction_house_fees_in_gain_breakdown(self):
        self.gain_setup()
        self.post_setup()
        self.run_lua('''
        HOOKS.PostAuction(100,200,1,5,1,false); charge(150)
        NOW=NOW+5; F.RecordValue(true)
        ''')
        got=self.breakdown()
        self.assertEqual(got["Auction house fees"],-150)
        self.assertEqual(got["gain"],sum(v for k,v in got.items() if k!="gain"))

    def test_item_categories_follow_recorded_classes(self):
        cases={"Cloth":(7,5),"Leather":(7,6),"Mining":(7,7),"Cooking":(7,8),"Herbs":(7,9),"Elemental":(7,10),
            "Enchanting":(7,12),"Engineering":(7,3),"Other materials":(7,13),"Gear":(4,1),"Consumables":(0,1),
            "Gems":(3,0),"Recipes":(9,4),"Bags":(1,0),"Quest items":(12,0),"Mounts":(15,5),"Miscellaneous":(15,0)}
        for expected,(cls,sub) in cases.items():
            self.assertEqual(self.run_lua('return F.ItemCategory({classID=%d,subclassID=%d})'%(cls,sub)),expected)
        self.assertEqual(self.run_lua('return F.ItemCategory({classID=2,subclassID=7})'),"Gear")
        self.assertEqual(self.run_lua('return F.ItemCategory(nil)'),"Unknown")
        self.assertEqual(self.run_lua('return F.ItemCategory({classID=99})'),"Miscellaneous")

    def test_item_details_are_found_for_an_invoice_that_only_names_its_item(self):
        self.assertEqual(self.run_lua('''
        local catalog={["5:0"]={name="Thorium Ore",classID=7,subclassID=7}}
        return F.ItemCategory({name="Thorium Ore"},catalog,{["Thorium Ore"]=catalog["5:0"]})
        '''),"Mining")
        self.assertEqual(self.run_lua('return F.ItemCategory({name="Unseen"},{},{})'),"Unknown")
        self.assertEqual(self.run_lua('''
        return F.ItemCategory({id=5},{["5:0"]={classID=7,subclassID=9}})
        '''),"Herbs")

    def profit_setup(self):
        self.run_lua('''
        INFO={[1]={"Ore",7,7,50},[2]={"Silk",7,5,10},[3]={"Sword",2,7,400}}
        C_Item.GetItemInfo=function(link)
            local id=type(link)=="number" and link or tonumber(tostring(link):match("item:(%d+)"))
            local i=INFO[id]
            if i then return i[1],link,1,10,1,"t","s",20,"INVTYPE_NON_EQUIP",1,i[4],i[2],i[3],0,0 end
        end
        function hold(rows)
            BAGS[0]={}
            for _,r in ipairs(rows) do BAGS[0][#BAGS[0]+1]={hyperlink="item:"..r[1],itemID=r[1],stackCount=r[2],isBound=false} end
            F.ScanBags(true); F.bagDirty=nil; F.equipmentDirty=nil; F.RecordValue(true)
        end
        function profit(since)
            local list,total=F.CategoryProfit(F.SelectedCharacters(),since or 0)
            local out={total=total}
            for _,r in ipairs(list) do out[r.category]=r end
            return F.JSON(out)
        end
        ''')

    def test_profit_counts_sales_spending_and_stock_by_category(self):
        self.profit_setup()
        self.run_lua('''
        hold({{1,10},{2,5}})
        NOW=NOW+60
        F.Claim("auction_sale",1200,{item={name="Ore"}})
        F.Claim("auction_deposit",-30,{item=F.Item("item:1")})
        F.Claim("vendor_purchase",-100,{item=F.Item("item:2")})
        F.Claim("repair",-999,{})
        F.Claim("loot",777,{})
        hold({{1,4},{2,15}})
        ''')
        got=json.loads(self.run_lua('return profit()'))
        self.assertEqual(got["Mining"],{"category":"Mining","held":200,"sold":1200,"spent":-30,"change":-300,"profit":870})
        self.assertEqual(got["Cloth"],{"category":"Cloth","held":150,"sold":0,"spent":-100,"change":100,"profit":0})
        self.assertEqual(got["total"]["profit"],870)
        self.assertEqual(set(got),{"Mining","Cloth","total"})

    def test_profit_rows_run_from_most_to_least_profitable(self):
        self.profit_setup()
        self.run_lua('''
        hold({})
        F.Claim("vendor_purchase",-100,{item=F.Item("item:2")})
        F.Claim("vendor_sale",300,{item=F.Item("item:1")})
        F.Claim("vendor_sale",50,{item=F.Item("item:3")})
        ''')
        names=json.loads(self.run_lua('''
        local list=F.CategoryProfit(F.SelectedCharacters(),0)
        local out={}
        for i,r in ipairs(list) do out[i]=r.category end
        return F.JSON(out)
        '''))
        self.assertEqual(names,["Mining","Gear","Cloth"])

    def test_profit_period_counts_only_what_happened_since_then(self):
        self.profit_setup()
        self.run_lua('''
        hold({{1,10}})
        F.Claim("vendor_sale",100,{item=F.Item("item:1")})
        NOW=NOW+1000; START=NOW
        hold({{1,12}})
        F.Claim("vendor_sale",40,{item=F.Item("item:1")})
        NOW=NOW+60
        hold({{1,13}})
        ''')
        today=json.loads(self.run_lua('return profit(START)'))["Mining"]
        self.assertEqual((today["sold"],today["change"],today["held"]),(40,50,650))
        always=json.loads(self.run_lua('return profit(0)'))["Mining"]
        self.assertEqual((always["sold"],always["change"],always["held"]),(140,150,650))

    def test_sell_junk_is_split_across_its_item_categories(self):
        self.profit_setup()
        self.run_lua('''
        hold({})
        F.Claim("vendor_sale",130,{method="sell_junk",items={{item=F.Item("item:1"),quantity=2},{item=F.Item("item:2"),quantity=3}}})
        ''')
        got=json.loads(self.run_lua('return profit()'))
        self.assertEqual(got["Mining"]["sold"],100)
        self.assertEqual(got["Cloth"]["sold"],30)

    def test_stock_counts_each_place_items_are_kept_in_one_category(self):
        self.profit_setup()
        self.run_lua('''
        hold({{1,1}})
        local c=F.character
        c.snapshots.mail={time=NOW,data={complete=true,rows={{money=5000,cod=0,items={{item=F.Item("item:1"),quantity=2}}}}}}
        c.snapshots.auctions={time=NOW,data={complete=true,rows={{status=0,item=F.Item("item:1"),quantity=3}}}}
        c.snapshots.equipment={time=NOW,data={complete=true,rows={{item=F.Item("item:3"),quantity=1,bound=true,equipped=true}}}}
        F.RecordValue(true)
        ''')
        got=json.loads(self.run_lua('return profit()'))
        self.assertEqual(got["Mining"]["held"],300)
        self.assertEqual(got["Gear"]["held"],400)
        self.assertNotIn("Unknown",got)

    def test_first_look_in_a_bank_is_not_a_profit(self):
        self.profit_setup()
        self.run_lua('''
        hold({{1,2}})
        NOW=NOW+60
        F.character.snapshots.bank={time=NOW,data={complete=true,rows={{item=F.Item("item:1"),quantity=100,bound=false}}}}
        F.RecordValue(true)
        ''')
        got=json.loads(self.run_lua('return profit()'))["Mining"]
        self.assertEqual((got["held"],got["change"],got["profit"]),(5100,0,0))
        self.run_lua('''
        NOW=NOW+60
        F.character.snapshots.bank.data.rows[1].quantity=110
        F.RecordValue(true)
        ''')
        got=json.loads(self.run_lua('return profit()'))["Mining"]
        self.assertEqual((got["held"],got["change"],got["profit"]),(5600,500,500))

    def test_stock_from_before_places_were_tracked_is_not_inflated(self):
        self.profit_setup()
        self.run_lua('''
        hold({{1,2}})
        F.character.stockSeen=nil
        NOW=NOW+60
        hold({{1,3}})
        ''')
        got=json.loads(self.run_lua('return profit()'))["Mining"]
        self.assertEqual((got["held"],got["change"]),(150,50))

    def test_stock_history_only_grows_on_change_and_keeps_its_first_entry(self):
        self.profit_setup()
        self.run_lua('''
        hold({{1,1}}); FIRST=F.character.stock[1].time
        local before=#F.character.stock
        F.RecordValue(true)
        assert(#F.character.stock==before)
        for i=1,450 do NOW=NOW+1; F.RememberStock(F.character,NOW,{Mining=i}) end
        ''')
        self.assertEqual(self.run_lua('return #F.character.stock'),400)
        self.assertEqual(self.run_lua('return F.character.stock[1].time'),self.run_lua('return FIRST'))
        self.assertEqual(self.run_lua('return F.character.stock[400].values.Mining'),450)

    def test_stock_at_uses_the_latest_entry_and_later_characters_start_at_their_first(self):
        self.run_lua('C={stock={{time=100,values={a=1}},{time=200,values={a=2}}}}')
        self.assertEqual(self.run_lua('return F.StockAt(C,50).a'),1)
        self.assertEqual(self.run_lua('return F.StockAt(C,150).a'),1)
        self.assertEqual(self.run_lua('return F.StockAt(C,200).a'),2)
        self.assertEqual(self.run_lua('return next(F.StockAt({},50))'),None)

    def test_profit_leaves_out_unselected_characters_and_flags_missing_linked_data(self):
        self.profit_setup()
        self.run_lua('''
        hold({{1,1}})
        F.Claim("vendor_sale",100,{item=F.Item("item:1")})
        F.db.peers.other={label="Bank",key="k",names={},history={},characters={Bank={name="Bank-Realm",marketScope=F.marketScope,stock={{time=NOW,values={Mining=999}}}}}}
        ''')
        got=json.loads(self.run_lua('return profit()'))
        self.assertEqual(got["Mining"]["sold"],100)
        self.assertEqual(got["Mining"]["held"],50)
        self.assertEqual(json.loads(self.run_lua('local list,total=F.CategoryProfit({},0); return F.JSON({n=#list,p=total.profit})')),{"n":0,"p":0})
        self.assertTrue(self.run_lua('local _,_,linked=F.CategoryProfit(F.SelectedCharacters(),0); return linked.missing'))
        self.assertIsNone(self.run_lua('local _,_,linked=F.CategoryProfit({},0); return linked.missing'))

    def test_profit_view_wiring(self):
        self.install_widgets()
        self.profit_setup()
        self.run_lua(r"""
        hold({{1,10},{2,5}})
        F.Claim("vendor_sale",100,{item=F.Item("item:1")})
        F.Show("profit")
        local p=F.profitPanel
        assert(p:IsShown() and not F.chart:IsShown() and not F.scanControls:IsShown() and not F.recordsBar:IsShown() and not F.scroll:IsShown() and not F.syncPanel:IsShown())
        assert(p.rows[1][1].text=="Mining" and p.rows[2][1].text=="Cloth")
        assert(p.total[1].text=="Total" and p.total[1].shown and not p.empty.shown)
        assert(p.rows[1][3].text:find("UI-GoldIcon",1,true))
        assert(p.scope.text:find("Since",1,true) and p.scope.text:find("1 character",1,true) and not p.scope.text:find("linked",1,true))
        assert(p.linked.text=="")
        for _,w in ipairs(WIDGETS) do
            if w.text=="All time" then w.scripts.OnClick() end
        end
        assert(F.db.settings.profitPeriod=="all" and p.scope.text:find("All time",1,true))
        F.character.stock=nil; F.db.events={}; F.RefreshProfit()
        assert(p.empty.shown and not p.rows[1][1].shown and not p.total[1].shown)
        F.Command("profit"); assert(F.mode=="profit")
        F.Show(); assert(F.chart:IsShown() and not p:IsShown())
        F.db.peers.other={label="Bank",key="k",names={},history={},characters={Bank={name="Bank-Realm",marketScope=F.marketScope}}}
        F.db.settings.chartCharacters=nil; F.Show("profit")
        assert(p.scope.text:find("2 characters, 1 on linked accounts",1,true) and p.linked.text:find("once it is online",1,true))
        F.db.peers.other.profit={since=0,at=NOW,rows={Bank={Herbs={70,0,0,0,300,-100,20}}}}
        F.db.settings.profitPeriod="all"; F.RefreshProfit()
        assert(p.linked.text:find("figures from",1,true) and p.rows[1][1].text=="Herbs")
        F.db.peers.other=nil; F.Show()
        assert(-p.note.anchors.TOPLEFT.y<p.height)
        assert(34+18*14+18<370)
        """)

    def test_sync_view_wiring(self):
        self.install_widgets()
        self.run_lua(r"""
        date=date or function(format,t) return os.date(format,t) end
        F.Show("sync")
        assert(F.syncPanel:IsShown() and not F.chart:IsShown() and not F.scanControls:IsShown() and not F.recordsBar:IsShown() and not F.scroll:IsShown())
        assert(F.syncPanel.empty.shown)
        F.db.peers.other={label="Bank",key="k",names={["Bank-Realm"]=true},lastName="Bank-Realm",characters={Bank={name="Bank-Realm"}},history={}}
        F.RefreshSyncPanel()
        assert(not F.syncPanel.empty.shown and F.syncPanel.rows[1].text.text:find("Bank",1,true))
        assert(F.syncPanel.rows[1].unlink.source=="other")
        local bar=F.syncPanel.rows[1].bar
        assert(bar.value==0 and bar.label.text=="Not connected")
        F.db.peers.other.total=4; F.db.peers.other.history={{},{},{}}; F.RefreshSyncPanel()
        assert(bar.value==0.75 and bar.label.text:find("Paused at 75%",1,true))
        F.db.peers.other.history[4]={}; F.db.peers.other.lastSync=NOW; F.RefreshSyncPanel()
        assert(bar.value==1 and bar.label.text=="Complete" and bar.color[2]>bar.color[1])
        F.Show(); assert(F.chart:IsShown() and not F.syncPanel:IsShown())
        """)

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

    def test_unchanged_rescans_record_nothing(self):
        self.run_lua('''
        GetInventoryItemLink=function(_,slot) if slot==16 then return "item:999" end end
        F.ScanEquipment(); F.ScanBags(); F.RecordValue(true)
        F.events.GET_ITEM_INFO_RECEIVED(); FIRST=F.bagDirty; CLOCK=0.4; F.events.GET_ITEM_INFO_RECEIVED(); SECOND=F.bagDirty
        NOW=NOW+10; F.ScanEquipment(); F.ScanBags(); F.ScanBags(true); F.bagDirty=nil; F.equipmentDirty=nil; F.RecordValue()
        ''')
        self.assertEqual(self.run_lua('return SECOND'),0)
        locations=[s["location"] for s in self.kind("snapshot")]
        self.assertEqual(locations.count("equipment"),1)
        self.assertEqual(locations.count("bags"),2)
        self.assertEqual(len(self.kind("valuation")),1)

    def test_partial_commodity_results_priced_without_paging(self):
        self.scanner()
        self.run_lua('FULL=false; RESULTS={{unitPrice=200},{unitPrice=300}}; F.StartPrices("all"); F.PriceTick(); F.PriceResults("commodity",2770)')
        self.assertEqual(self.kind('price')[0]['quote']['price'],200)
        self.assertEqual(self.run_lua('return #SENT'),1)

    def test_price_queue_skips_unlistable_items(self):
        self.run_lua('F.TrackItem({id=5000,name="Quest Thing",link="item:5000",bindType=4}); F.TrackItem({id=5001,name="Ore",link="item:5001",bindType=0})')
        keys=[e["key"] for e in self.result('F.PriceQueue("all")')]
        self.assertIn("5001:0",keys)
        self.assertNotIn("5000:0",keys)

    def test_schema_one_upgrade_preserves_existing_events(self):
        self.run_lua('''
        F.Emit("old",{amount=123}); local db=F.db
        db.markets=nil; db.history=nil; F.Init(db,F.identity)
        F.ObserveBalance(WALLET); F.RecordValue()
        ''')
        self.assertEqual(len(self.kind('old')),1)
        self.assertEqual(len(self.kind('valuation')),1)

    def switch_to_alt_with_old_logout(self):
        # An alt saved by the old code: the logout read 0 and stored it.
        self.run_lua('''
        DB=F.db
        F.Init(DB,{guid="Player-Alt",name="Alt-Realm",realm="Realm",build="test"})
        F.ObserveBalance(5000); F.RecordValue(true)
        F.ObserveBalance(0); F.Flush(); F.RecordValue(true); F.Emit("logout",{})
        ZEROED=DB.history[#DB.history]
        DB.logoutBalancesRepaired=nil
        F.Init(DB,{guid="Player-Main",name="Main-Realm",realm="Realm",build="test"})
        F.ObserveBalance(WALLET)
        ''')

    def test_old_logout_zero_is_repaired_once(self):
        self.switch_to_alt_with_old_logout()
        self.assertEqual(self.run_lua('return DB.characters["Player-Alt"].balance'),5000)
        self.assertEqual(self.run_lua('return ZEROED.chars["Player-Alt"].gold'),5000)
        self.assertEqual(self.run_lua('return ZEROED.gold'),self.run_lua('return ZEROED.total-ZEROED.assets-ZEROED.equipped'))
        self.assertEqual([c['amount'] for c in self.kind('balance_correction')],[5000])
        self.run_lua('F.Init(DB,{guid="Player-Main",name="Main-Realm",realm="Realm",build="test"})')
        self.assertEqual(len(self.kind('balance_correction')),1)

    def test_switching_character_keeps_previous_gold(self):
        self.switch_to_alt_with_old_logout()
        self.run_lua('F.RecordValue(true)')
        wallet=self.run_lua('return WALLET')
        self.assertEqual(self.kind('valuation')[-1]['gold'],wallet+5000)

    def test_real_balance_drop_without_logout_is_not_repaired(self):
        self.run_lua('''
        DB=F.db; F.ObserveBalance(0); F.Flush(); F.Emit("note",{}); F.Emit("note",{}); F.Emit("note",{}); F.Emit("logout",{})
        DB.logoutBalancesRepaired=nil
        F.Init(DB,{guid="Player-Alt",name="Alt-Realm",realm="Realm",build="test"})
        ''')
        self.assertEqual(self.kind('balance_correction'),[])

    def alt_with_items(self):
        # A second character on this realm, with a stack worth more than the first's.
        self.run_lua('''
        DB=F.db
        ALL={gold=true,assets=true,equipped=true}
        F.db.characters["Player-Alt"]={name="Alt-Realm",class="MAGE",balance=5000,marketScope=F.marketScope,snapshots={
            bags={time=NOW,data={complete=true,rows={{item={id=7,name="Ore",quality=2,vendorPrice=100},quantity=4,bound=false}}}}}}
        F.Snapshot("bags",{{item={id=8,name="Ore",vendorPrice=10},quantity=2,bound=false}},true)
        F.Snapshot("equipment",{},true)
        F.TrackItem({id=7,name="Ore",quality=2,vendorPrice=100})
        F.RecordValue(true)
        function last(characters) local p=F.StackHistory(F.db.history,ALL,F.marketScope,characters,1,NOW); return p[#p] end
        ''')

    def test_gold_breakdown_uses_class_color_and_short_name(self):
        self.alt_with_items()
        self.run_lua('''
        RAID_CLASS_COLORS={MAGE={r=0.2,g=0.8,b=0.9}}
        ROWS=F.BreakdownRows(last(F.SelectedCharacters()),"gold",F.SelectedCharacters())
        ''')
        wallet=self.run_lua('return WALLET')
        self.assertEqual(self.run_lua('return #ROWS'),2)
        self.assertEqual(self.run_lua('return ROWS[1].value'),wallet)
        self.assertEqual(self.run_lua('return ROWS[2].value'),5000)
        self.assertEqual(self.run_lua('return ROWS[2].label'),"|cff33cce5Alt|r")

    def test_asset_row_shows_neutral_amount_then_item_then_character(self):
        self.alt_with_items()
        self.run_lua('''
        RAID_CLASS_COLORS={MAGE={r=0.2,g=0.8,b=0.9}}
        ITEM_QUALITY_COLORS={[2]={r=0,g=1,b=0}}
        ROWS=F.BreakdownRows(last(F.SelectedCharacters()),"assets",F.SelectedCharacters())
        ''')
        self.assertEqual(self.run_lua('return ROWS[1].value'),400)
        self.assertEqual(self.run_lua('return ROWS[1].label'),"|cffc8c8c84x|r |cff00ff00Ore|r |cff33cce5Alt|r")

    def test_asset_rows_are_top_ten_across_characters(self):
        self.alt_with_items()
        self.run_lua('''
        local rows={}
        for i=1,12 do rows[i]={item={id=100+i,name="Item"..i,vendorPrice=i*100},quantity=1,bound=false} end
        F.Snapshot("bags",rows,true); F.RecordValue(true)
        ROWS=F.BreakdownRows(last(F.SelectedCharacters()),"assets",F.SelectedCharacters())
        ''')
        self.assertEqual(self.run_lua('return #ROWS'),10)
        self.assertEqual(self.run_lua('return ROWS[1].value'),1200)
        self.assertEqual(self.run_lua('return ROWS[10].value'),400)
        self.assertEqual(self.run_lua('local n=0; for _,r in ipairs(ROWS) do if r.label:find("Alt",1,true) then n=n+1 end end; return n'),1)

    def test_character_selection_changes_totals(self):
        self.alt_with_items()
        wallet=self.run_lua('return WALLET')
        gold=lambda: self.run_lua('return last(F.SelectedCharacters()).totals.gold')
        self.assertEqual(gold(),wallet+5000)
        self.run_lua('F.db.settings.chartCharacters="this"')
        self.assertEqual(gold(),wallet)
        self.run_lua('F.db.settings.chartCharacters=nil; F.ToggleChartCharacter(F.identity.guid)')
        self.assertEqual(gold(),5000)
        self.run_lua('F.ToggleChartCharacter(F.identity.guid)')
        self.assertEqual(gold(),wallet+5000)

    def test_chart_points_are_equal_steps_holding_latest_sample(self):
        self.run_lua('''
        START=NOW
        for i=1,20 do NOW=NOW+1; F.character.balance=i; F.RecordValue(true) end
        NOW=START+1000; F.character.balance=777; F.RecordValue(true)
        NOW=START+2000
        P=F.StackHistory(F.db.history,{gold=true},F.marketScope,F.SelectedCharacters(),10,NOW)
        ''')
        self.assertEqual(self.run_lua('return #P'),11)
        steps=self.run_lua('local out={}; for i=2,#P do out[#out+1]=P[i].time-P[i-1].time end; return F.JSON(out)')
        steps=json.loads(steps)
        self.assertAlmostEqual(min(steps),max(steps),places=3)
        self.assertEqual(self.run_lua('return P[#P].values[1].value'),777)
        self.assertEqual(self.run_lua('return P[#P].time'),self.run_lua('return NOW'))
        self.assertEqual(self.run_lua('return P[5].values[1].value'),20)

    def test_price_scan_records_one_sample_when_it_ends(self):
        self.run_lua('''
        BEFORE=#F.db.history
        F.priceScan={queue={},index=1,mode="all"}
        for i=1,5 do NOW=NOW+1; F.character.balance=i; F.historyDirty=true; F.RecordValue() end
        DURING=#F.db.history
        F.priceScan=nil; F.RecordValue()
        ''')
        self.assertEqual(self.run_lua('return DURING'),self.run_lua('return BEFORE'))
        self.assertEqual(self.run_lua('return #F.db.history'),self.run_lua('return BEFORE+1'))

    def test_episode_end_overlapping_next_start_shows_start_only(self):
        self.run_lua('''
        local function at(kind,t,name) local e=F.Emit(kind,{name=name}); e.time=t end
        at("episode_start",1000,"One"); at("episode_end",2000); at("episode_start",2005,"Two")
        at("episode_end",3000); at("episode_start",4000,"Three"); at("episode_start",9000,"Late")
        M=F.EpisodeMarkers(1000,5000,10)
        ''')
        got=json.loads(self.run_lua('return F.JSON(M)'))
        self.assertEqual([(m['time'],m.get('name')) for m in got],[(1000,"One"),(2005,"Two"),(3000,None),(4000,"Three")])

    def test_mail_items_and_money_count_unless_cod(self):
        self.gear()
        self.run_lua('''
        F.Snapshot("bags",{},true); F.Snapshot("equipment",{},true)
        F.Snapshot("mail",{{money=500,cod=0,items={{item=gear,quantity=1}}},
            {money=0,cod=100,items={{item=gear,quantity=1}}}},true)
        F.RecordValue(true)
        ''')
        self.assertEqual(self.kind('valuation')[-1]['assets'],9500+500)

    def test_old_samples_migrate_to_character_values(self):
        self.run_lua('''
        F.character.balance=300; F.RecordValue(true)
        OLD=F.db.history[#F.db.history]
        OLD.chars=nil; OLD.top={}; OLD.goldBy={["Player-Main"]=999}
        F.Init(F.db,F.identity)
        ''')
        self.assertEqual(self.run_lua('return OLD.chars["Player-Main"].gold'),999)
        self.assertIsNone(self.run_lua('return OLD.goldBy'))
        self.assertIsNone(self.run_lua('return OLD.top'))

    def test_item_breakdown_recorded_only_on_change_and_read_by_time(self):
        self.alt_with_items()
        self.run_lua('''
        COUNT=#F.character.tops; T=NOW
        NOW=NOW+10; F.RecordValue(true); SAME=#F.character.tops
        NOW=NOW+10; F.Snapshot("bags",{{item={id=9,name="Gem",vendorPrice=50},quantity=1,bound=false}},true); F.RecordValue(true)
        OLDROW=F.TopAt(F.identity.guid,T,"assets")[1].key
        NEWROW=F.TopAt(F.identity.guid,NOW,"assets")[1].key
        NONE=#F.TopAt(F.identity.guid,T-100,"assets")
        ''')
        self.assertEqual(self.run_lua('return SAME'),self.run_lua('return COUNT'))
        self.assertEqual(self.run_lua('return OLDROW'),"8:0")
        self.assertEqual(self.run_lua('return NEWROW'),"9:0")
        self.assertEqual(self.run_lua('return NONE'),0)

    def test_money_uses_coin_icons(self):
        text=self.run_lua('return F.Money(1234567)')
        self.assertEqual(text.replace("|TInterface\\MoneyFrame\\UI-GoldIcon:0:0:2:0|t","G").replace("|TInterface\\MoneyFrame\\UI-SilverIcon:0:0:2:0|t","S").replace("|TInterface\\MoneyFrame\\UI-CopperIcon:0:0:2:0|t","C"),"123G 45S 67C")
        self.assertTrue(self.run_lua('return F.MoneyShort(-1234567)').startswith("-123|T"))

    def gain_setup(self):
        # Yesterday's samples, then today's first login at 10:00 local time.
        self.run_lua('''
        date=os.date
        local t=os.date("*t",NOW); t.hour,t.min,t.sec=10,0,0
        TODAY=os.time(t)
        DB=F.db
        NOW=TODAY-86400; F.Init(DB,F.identity); F.character.balance=1000; F.RecordValue(true)
        NOW=TODAY; F.Init(DB,F.identity); F.character.balance=2000; F.RecordValue(true)
        NOW=TODAY+600; F.Init(DB,F.identity); F.character.balance=2500; F.RecordValue(true)
        ''')

    def test_gain_counts_from_first_login_of_the_day(self):
        self.gain_setup()
        self.assertEqual(self.run_lua('return F.GoldGain(F.SelectedCharacters(),NOW)'),500)

    def test_gain_counts_from_active_marker(self):
        self.gain_setup()
        self.run_lua('''
        NOW=NOW+60; F.SetMarker("Run")
        NOW=NOW+60; F.character.balance=2100; F.RecordValue(true)
        ''')
        self.assertEqual(self.run_lua('return F.GoldGain(F.SelectedCharacters(),NOW)'),-400)
        self.run_lua('F.db.episode=nil')
        self.assertEqual(self.run_lua('return F.GoldGain(F.SelectedCharacters(),NOW)'),100)

    def test_gain_counts_character_first_seen_after_start_from_its_first_balance(self):
        self.gain_setup()
        self.run_lua('''
        F.db.characters["Player-New"]={name="New-Realm",balance=99999,marketScope=F.marketScope,snapshots={}}
        NOW=NOW+60; F.character.balance=2600; F.RecordValue(true)
        ''')
        self.assertEqual(self.run_lua('return F.GoldGain(F.SelectedCharacters(),NOW)'),600)
        self.run_lua('''
        F.db.characters["Player-New"].balance=100049
        NOW=NOW+60; F.RecordValue(true)
        ''')
        self.assertEqual(self.run_lua('return F.GoldGain(F.SelectedCharacters(),NOW)'),650)

    def test_gain_of_session_running_past_midnight_counts_from_midnight(self):
        self.gain_setup()
        self.run_lua('''
        F.db.events={}
        NOW=TODAY+3600; F.character.balance=2700; F.RecordValue(true)
        NOW=NOW+60; F.character.balance=2750; F.RecordValue(true)
        ''')
        # The first sample since midnight is the 10:00 login at 2000.
        self.assertEqual(self.run_lua('return F.GoldGain(F.SelectedCharacters(),NOW)'),750)

    def test_gain_follows_selected_characters(self):
        self.gain_setup()
        self.assertEqual(self.run_lua('return F.GoldGain({},NOW)'),0)

    def test_smoothing_spreads_a_jump_and_keeps_both_ends(self):
        self.run_lua('''
        P={}
        for i=1,11 do P[i]={time=i,totals={total=i>6 and 900 or 0},values={{key="gold",value=i>6 and 900 or 0}}} end
        F.SmoothHistory(P,2)
        V={}
        for i=1,11 do V[i]=P[i].values[1].value end
        ''')
        values=[self.run_lua('return V[%d]'%i) for i in range(1,12)]
        self.assertEqual(values[0],0)
        self.assertEqual(values[10],900)
        self.assertEqual(values,sorted(values))
        self.assertEqual(self.run_lua('return P[7].totals.total'),900)
        self.assertGreater(values[4],0)
        self.assertLess(values[7],900)

    def test_axis_steps_are_powers_of_ten_in_gold_with_headroom(self):
        gold=10000
        for peak,top,step in [(18590,20000,10000),(162,200,100),(52,60,10),(1000,1100,100),
                              (14000,15000,1000),(9500,10000,1000),(5,6,1),(0.5,1,1)]:
            self.assertEqual(self.run_lua('return F.AxisScale(%d)'%(peak*gold)),(top*gold,step*gold))

    def test_axis_labels_redraw_at_round_steps(self):
        self.install_widgets()
        self.run_lua('''
        F.ObserveBalance(52*10000); F.RecordValue(true); F.Show()
        F.Snapshot("bags",{},true); F.Snapshot("equipment",{},true); F.RecordValue(true); F.RefreshChart()
        local function labels()
            local out={}
            for i=1,#F.chart.axis do
                if F.chart.axis[i]:IsShown() then out[#out+1]=F.chart.axis[i].text:match("^%d+") end
            end
            return table.concat(out,",")
        end
        SMALL=labels()
        F.ObserveBalance(1200*10000); F.RecordValue(true); F.RefreshChart()
        LARGE=labels()
        ''')
        self.assertEqual(self.run_lua('return SMALL'),"0,10,20,30,40,50,60")
        self.assertEqual(self.run_lua('return LARGE'),"0,100,200,300,400,500,600,700,800,900,1000,1100,1200,1300")

    def test_fill_follows_the_line_with_no_gaps(self):
        self.install_widgets()
        self.run_lua('''
        for _,balance in ipairs({5000,900000,120000,120000,700000}) do
            NOW=NOW+3000; F.ObserveBalance(balance); F.RecordValue(true)
        end
        F.db.settings.chart={gold=true}
        F.Show()
        local c=F.chart
        local function shown(pool)
            local out={}
            for _,t in ipairs(pool) do if t.shown then out[#out+1]=t end end
            return out
        end
        FILLS,LINES=shown(c.fills),shown(c.lines)
        local function near(a,b) return math.abs(a.x-b.x)<0.0001 and math.abs(a.y-b.y)<0.0001 end
        local function mid(a,b) return {x=(a.x+b.x)/2,y=(a.y+b.y)/2} end
        for i=2,#LINES do
            -- Neighbouring pieces of the line share corners, so no notch can open.
            local _,upperRight,_,lowerRight=CORNERS(LINES[i-1])
            local upperLeft,_,lowerLeft=CORNERS(LINES[i])
            assert(near(upperRight,upperLeft) and near(lowerRight,lowerLeft))
        end
        assert(#FILLS==#LINES)
        for i,fill in ipairs(FILLS) do
            local upperLeft,upperRight,lowerLeft,lowerRight=CORNERS(fill)
            -- Each area runs from the baseline up to the middle of its piece of line.
            assert(lowerLeft.y==0 and lowerRight.y==0 and lowerLeft.x==upperLeft.x and lowerRight.x==upperRight.x)
            local a,b,e,f=CORNERS(LINES[i])
            assert(near(upperLeft,mid(a,e)) and near(upperRight,mid(b,f)))
            -- Neighbouring areas share the exact same edge.
            if i>1 then local _,previous=CORNERS(FILLS[i-1]); assert(near(previous,upperLeft)) end
            assert(fill.texture:find("WHITE8X8",1,true))
            assert(LINES[i].texture:find("line-soft",1,true))
        end
        -- A flat stretch of history takes fewer pieces than steps.
        assert(#LINES<275)
        ''')
        self.assertGreater(self.run_lua('return #FILLS'),0)

    def test_lower_band_paints_over_the_higher_ones(self):
        self.install_widgets()
        self.run_lua('''
        F.ObserveBalance(900000); F.RecordValue(true); F.Show()
        local layers={}
        for _,t in ipairs(F.chart.fills) do if t.shown then layers[t.layer]=true end end
        assert(layers[2] and F.chart.fills[1].layer==2)
        ''')

    def test_curve_edges_keep_their_width_and_meet_on_the_bisector(self):
        self.run_lua('''
        local UP,DOWN=F.CurveEdges({{x=0,y=0},{x=10,y=0},{x=20,y=0}},2)
        assert(UP[2].y==2 and DOWN[2].y==-2 and UP[1].x==0)
        -- A right-angle turn reaches past the plain width, up to the limit.
        UP,DOWN=F.CurveEdges({{x=0,y=0},{x=10,y=0},{x=10.0001,y=10}},2)
        WIDE=math.sqrt((UP[2].x-10)^2+UP[2].y^2)
        -- A narrow spike stops short of the long corner it would otherwise reach.
        UP,DOWN=F.CurveEdges({{x=0,y=0},{x=2,y=200},{x=4,y=0}},2)
        SPIKE=UP[2].y-200
        ''')
        self.assertAlmostEqual(self.run_lua('return WIDE'),2*1.4,places=2)
        self.assertLessEqual(self.run_lua('return SPIKE'),2*1.4+0.0001)

    def test_simplify_keeps_every_turn_and_both_ends(self):
        self.run_lua('''
        CURVE={}
        for i=0,100 do CURVE[#CURVE+1]={x=i,y=0} end
        for i=101,110 do CURVE[#CURVE+1]={x=i,y=(i-100)*5} end
        for i=111,200 do CURVE[#CURVE+1]={x=i,y=50} end
        KEPT=F.SimplifyCurve(CURVE,0.05)
        ONE=#F.SimplifyCurve({{x=0,y=0}},0.05)
        ''')
        self.assertEqual(self.run_lua('return #KEPT'),4)
        self.assertEqual(self.run_lua('return KEPT[2].x'),100)
        self.assertEqual(self.run_lua('return KEPT[3].x'),110)
        self.assertEqual(self.run_lua('return KEPT[4].x'),200)
        self.assertEqual(self.run_lua('return ONE'),1)

    def bands(self):
        self.run_lua('''
        ALL={gold=true,assets=true,equipped=true}
        T1=NOW; T2=NOW+1000
        F.db.history={
            {time=T1,scope=F.marketScope,chars={["Player-Main"]={gold=100,assets=1000,equipped=50},["Player-Alt"]={gold=7,assets=70,equipped=0}}},
            {time=T2,scope=F.marketScope,chars={["Player-Main"]={gold=200,assets=2000,equipped=50},["Player-Alt"]={gold=7,assets=70,equipped=0}}},
        }
        F.db.characters["Player-Main"].stock={{time=T1,values={Cloth=750,Gear=300}},{time=T2,values={Cloth=500,Gear=50,Herbs=1500}}}
        F.db.characters["Player-Alt"]={name="Alt-Realm",snapshots={},marketScope=F.marketScope,stock={}}
        TWO={["Player-Main"]=true,["Player-Alt"]=true}
        function STACK(selected,breakdown,characters)
            local points=F.StackHistory(F.db.history,selected,F.marketScope,characters or TWO,2,T2,breakdown)
            return points
        end
        function BAND(point,key)
            local below=0
            for _,v in ipairs(point.values) do
                if v.key==key then return v.value-below end
                below=v.value
            end
        end
        ''')

    def test_category_bands_add_up_to_the_exact_total(self):
        self.bands()
        self.run_lua('''
        P=STACK(ALL,"category"); LAST=P[#P]; FIRST=P[1]
        ''')
        self.assertEqual(self.run_lua('return LAST.values[#LAST.values].value'),2327)
        self.assertEqual(self.run_lua('return LAST.totals.total'),2327)
        self.assertEqual(self.run_lua('return BAND(LAST,"gold")'),207)
        # Equipped Gear is Gear. Other assets split by the recorded mix, without the worn part.
        self.assertEqual(self.run_lua('return BAND(LAST,"Gear")'),50)
        self.assertEqual(self.run_lua('return BAND(LAST,"Herbs")'),1500)
        self.assertEqual(self.run_lua('return BAND(LAST,"Cloth")'),500)
        # Asset value of a character with no recorded items has no category.
        self.assertEqual(self.run_lua('return BAND(LAST,F.OTHER_BAND)'),70)
        self.assertEqual(self.run_lua('return BAND(FIRST,"Cloth")'),750)
        self.assertEqual(self.run_lua('return BAND(FIRST,"Gear")'),300)

    def test_category_bands_follow_the_selected_types(self):
        self.bands()
        self.run_lua('P=STACK({assets=true},"category"); LAST=P[#P]')
        self.assertEqual(self.run_lua('return BAND(LAST,"gold")'),None)
        self.assertEqual(self.run_lua('return BAND(LAST,"Gear")'),0)
        self.assertEqual(self.run_lua('return LAST.values[#LAST.values].value'),2070)
        self.run_lua('P=STACK({equipped=true},"category"); LAST=P[#P]')
        self.assertEqual(self.run_lua('return #LAST.values'),1)
        self.assertEqual(self.run_lua('return BAND(LAST,"Gear")'),50)

    def test_linked_character_categories_use_what_its_account_last_sent(self):
        self.bands()
        self.run_lua('''
        F.db.characters["Player-Alt"]=nil
        F.db.peers.bank={characters={["Player-Alt"]={name="Alt-Realm"}},history={},names={},
            profit={since=0,at=T2,key="x",rows={["Player-Alt"]={Mining={35,0,0,0,0,0,0},Cloth={105,0,0,0,0,0,0}}}}}
        P=STACK({assets=true},"category",{["Player-Alt"]=true}); LAST=P[#P]
        ''')
        # 70 in value, split 1:3 by what it last sent.
        self.assertEqual(self.run_lua('return BAND(LAST,"Mining")'),17.5)
        self.assertEqual(self.run_lua('return BAND(LAST,"Cloth")'),52.5)

    def test_character_bands_stack_the_selected_types_biggest_lowest(self):
        self.bands()
        self.run_lua('P=STACK({gold=true,equipped=true},"character"); LAST=P[#P]')
        self.assertEqual(self.run_lua('return LAST.values[1].key'),"Player-Main")
        self.assertEqual(self.run_lua('return BAND(LAST,"Player-Main")'),250)
        self.assertEqual(self.run_lua('return BAND(LAST,"Player-Alt")'),7)
        self.assertEqual(self.run_lua('return LAST.values[#LAST.values].value'),257)

    def test_small_bands_fold_into_other_and_the_total_stays_exact(self):
        self.bands()
        self.run_lua('''
        local chars,set,sum={},{},0
        for i=1,12 do chars["G"..i]={gold=i*100}; set["G"..i]=true; sum=sum+i*100 end
        F.db.history={{time=T1,scope=F.marketScope,chars=chars}}
        P=STACK({gold=true},"character",set); LAST=P[#P]; SUM=sum
        ''')
        self.assertEqual(self.run_lua('return #LAST.values'),8)
        self.assertEqual(self.run_lua('return LAST.values[8].key'),"other")
        self.assertEqual(self.run_lua('return LAST.values[1].key'),"G12")
        self.assertEqual(self.run_lua('return LAST.values[8].value==SUM'),True)
        self.assertEqual(self.run_lua('return LAST.other.G1'),True)
        self.assertEqual(self.run_lua('return LAST.other.G12'),None)
        self.assertEqual(self.run_lua('return BAND(LAST,"other")'),100+200+300+400+500)

    def test_breakdown_switch_and_dropdown_redraw_with_a_legend(self):
        self.install_widgets()
        self.bands()
        self.run_lua('''
        F.Show()
        local c=F.chart
        assert(c.switch.type.locked and not c.switch.category.locked)
        local function legend()
            local out={}
            for _,entry in ipairs(c.legend) do if entry.name.shown then out[#out+1]=entry.name.text end end
            return table.concat(out,",")
        end
        assert(legend()=="Equipped Gear,Other assets,Gold")
        c.switch.category.scripts.OnClick(c.switch.category)
        assert(F.db.settings.chartBreakdown=="category" and c.switch.category.locked and not c.switch.type.locked)
        LEGEND=legend()
        c.switch.character.scripts.OnClick(c.switch.character)
        CHARACTERS=legend()
        -- Only one type and one character leaves one band, which needs no legend.
        F.db.settings.chart={gold=true}; F.db.settings.chartCharacters={["Player-Main"]=true}; F.RefreshChart()
        assert(legend()=="" and c.metric.text=="Gold")
        -- One open list closes the other.
        c.metric.scripts.OnClick(c.metric); assert(c.checks.gold:GetChecked() and c.panels[2]:IsShown())
        c.selector.scripts.OnClick(c.selector); assert(c.panels[1]:IsShown() and not c.panels[2]:IsShown())
        c.selector.scripts.OnClick(c.selector); assert(not c.panels[1]:IsShown())
        ''')
        self.assertEqual(self.run_lua('return LEGEND'),"Other,Gear,Cloth,Herbs,Gold")
        self.assertEqual(self.run_lua('return CHARACTERS'),"Alt,Main")

    def test_legend_and_switch_fit_between_the_stats_and_the_edge(self):
        self.install_widgets()
        self.bands()
        self.run_lua('''
        local chars,set={},{}
        for i=1,12 do
            local guid="G"..i
            chars[guid]={gold=i*100}; set[guid]=true
            F.db.characters[guid]={name=guid,snapshots={},marketScope=F.marketScope}
        end
        F.db.history={{time=T1,scope=F.marketScope,chars=chars}}
        F.db.settings.chartBreakdown="character"; F.db.settings.chartCharacters=set
        F.db.settings.chart={gold=true}
        F.Show()
        local c=F.chart
        assert(#c.legend==8)
        local sale=c.stats.sale
        for _,entry in ipairs(c.legend) do
            local name=entry.name
            assert(entry.swatch.anchors.TOPLEFT.x>=c.stats.value.width)
            assert(name.anchors.TOPLEFT.x+name.width<=c.width-sale.width)
            assert(name.anchors.TOPLEFT.y>=c.selector.anchors.TOPLEFT.y)
        end
        local last=c.switch.character
        assert(last.anchors.TOPLEFT.x+last.width<=c.width)
        assert(c.metric.anchors.TOPLEFT.x+c.metric.width<=c.switch.type.anchors.TOPLEFT.x)
        ''')

    def test_band_hover_lists_what_the_band_holds(self):
        self.install_widgets()
        self.bands()
        self.run_lua('''
        F.db.settings.chartBreakdown="category"; F.Show()
        local c=F.chart
        local last=c.points[#c.points]
        ROWS=F.BandRows(last,"Cloth",c.characters,c.selected,"category")
        OTHER=F.BandRows(last,F.OTHER_BAND,c.characters,c.selected,"category")
        BY=F.BandRows(last,"Player-Main",c.characters,c.selected,"character")
        ''')
        self.assertEqual(self.run_lua('return #ROWS'),1)
        self.assertEqual(self.run_lua('return ROWS[1].value'),500)
        self.assertIn("Main",self.run_lua('return ROWS[1].label'))
        self.assertEqual(self.run_lua('return OTHER[1].label'),"Not categorised")
        self.assertEqual(self.run_lua('return OTHER[1].value'),70)
        self.assertEqual(self.run_lua('return #BY'),3)
        self.assertEqual(self.run_lua('return BY[1].value'),2000)

    def test_a_band_keeps_its_color_when_others_come_and_go(self):
        self.install_widgets()
        self.bands()
        self.run_lua('''
        F.db.settings.chartBreakdown="category"; F.Show()
        local c=F.chart
        local function colorOf(name)
            for _,entry in ipairs(c.legend) do
                if entry.name.shown and entry.name.text==name then return entry.swatch end
            end
        end
        local before=colorOf("Cloth").color
        F.db.settings.chart={assets=true}; F.RefreshChart()
        local after=colorOf("Cloth").color
        assert(before[1]==after[1] and before[2]==after[2] and before[3]==after[3])
        ''')

    def test_history_at_finds_nearest_sample_and_line(self):
        self.run_lua('''
        P={{time=0,values={{key="gold",value=100},{key="assets",value=300}},raw={}},
           {time=10,values={{key="gold",value=200},{key="assets",value=500}},raw={}}}
        NEAR,HIT=F.HistoryAt(P,8,178,5)
        _,HIT2=F.HistoryAt(P,5,400,5)
        _,MISS=F.HistoryAt(P,5,250,5)
        _,CLAMPED=F.HistoryAt(P,-5,100,1)
        ''')
        self.assertEqual(self.run_lua('return NEAR.time'),10)
        self.assertEqual(self.run_lua('return HIT'),"gold")
        self.assertEqual(self.run_lua('return HIT2'),"assets")
        self.assertEqual(self.run_lua('return MISS'),None)
        self.assertEqual(self.run_lua('return CLAMPED'),"gold")

    def test_summary_has_no_change_history(self):
        summary=self.run_lua('return F.Summary()')
        self.assertNotIn("net gold change",summary)
        self.assertNotIn("reconciliation windows",summary)
        self.assertIn("Equipped Gear",summary)

    def test_minimap_position_and_assets(self):
        self.assertAlmostEqual(self.run_lua('local x,y=F.MinimapPosition(0,80); return x'),80)
        self.assertAlmostEqual(self.run_lua('local x,y=F.MinimapPosition(45,80,true); return y'),80)
        for toc in ("ForeverLedger.toc","ForeverLedger_TBC.toc"):
            self.assertIn("Minimap.lua",(base.ROOT/"ForeverLedger"/toc).read_text())
        header=(base.ROOT/"ForeverLedger"/"Media"/"monkey-stamp.tga").read_bytes()[:18]
        self.assertEqual((header[2],header[12],header[14],header[16]),(2,64,64,32))


if __name__ == '__main__':
    unittest.main()
