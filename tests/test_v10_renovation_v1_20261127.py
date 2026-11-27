"""OWNER 2026-11-27 「AIコクピットを一度整理して、100億プロジェクトのゴールに向けて全面改修」 版1（片づけ）.

One switch object (window.cockpitRenovation) moves the tabs without a passing record into the existing 「参考」 menu, folds or hides a few
panels, and mutes three voices. Nothing is deleted: the old code and its records stay, and taking an entry out of the lists undoes it.
"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")
MARK = "OWNER 2026-11-27 「AIコクピットを一度整理して、100億プロジェクトのゴールに向けて全面改修」 版1（片づけ）："


class RenovationV1(unittest.TestCase):
    def block(self):
        i = HTML.index(MARK)
        return HTML[i:HTML.index("</script>", i)]

    def test_switch_and_lists(self):
        b = self.block()
        self.assertIn('muteShortRebound:true,muteHoldVoice:true,noCloseTabSwitch:true', b)
        self.assertIn('refTabs:["pre-next","analysts","kioxia-calendar","swing","value","brain","closing-auction"]', b)
        self.assertIn('foldIds:["owner-brain-rules","trial-methods","virtual-trades"]', b)
        self.assertIn('hideIds:["trade-fx-link","owner-history-review"]', b)
        self.assertIn('wholeBox:["owner-brain-rules","owner-history-review"]', b)
        # audit 7d810e5: panels that are rebuilt by their own refresh are not folded
        self.assertNotIn('"ec-plan"', b)
        self.assertNotIn('"ec-past"', b)
        self.assertIn('f.style.order="999";f.style.gridColumn="1 / -1";', b)
        self.assertIn("window.cockpitRenovation=R;", b)

    def test_tabs_go_into_the_reference_menu_not_deleted(self):
        b = self.block()
        self.assertIn('const more=nav.querySelector(":scope > details.secondary-tabs")', b)
        self.assertIn("more.appendChild(b);", b)
        self.assertNotIn(".remove()", b)
        self.assertIn("new MutationObserver(run).observe(nav,{childList:true})", b)   # tabs added later are moved too

    def test_fold_keeps_the_panels(self):
        b = self.block()
        self.assertIn('f.className="ref-fold"', b)
        self.assertIn("参考（未検証・記録中）：合格していない欄です。記録は続いています", b)
        self.assertIn("f.appendChild(el);", b)

    def test_three_voices_are_guarded_by_the_switch(self):
        self.assertIn('const say=msg=>{if(window.cockpitRenovation&&window.cockpitRenovation.muteShortRebound)return;', HTML)
        i = HTML.index("const e=Object.values(mem.ev).find(x=>!x.spoken);")
        self.assertIn("if(window.cockpitRenovation&&window.cockpitRenovation.muteHoldVoice)return;", HTML[i:i + 300])
        i = HTML.index("function autoSwitch(){")
        self.assertIn("if(window.cockpitRenovation&&window.cockpitRenovation.noCloseTabSwitch)return;", HTML[i:i + 200])

    def test_the_old_voices_and_switch_code_stay(self):
        # 戻すときに使う元の文は残す
        self.assertIn('if(st.first.length<=8)say("ショートリバ初動。"+short(r.name)+"。まだショートしない。")', HTML)
        self.assertIn('"仮想で入りました、"+yenTxt:"仮想で出ました、"+e.how+"、"+yenTxt', HTML)
        self.assertIn('if(!m.ca)go("closing-auction","ca");', HTML)

    def test_gpt_cards_look_like_the_others(self):
        self.assertIn(".scalp-strip.gpt-cards{display:grid;", HTML)
        self.assertIn(".scalp-strip.gpt-cards .gpt-card{border-color:#2a2e35!important;box-shadow:none!important", HTML)


if __name__ == "__main__":
    unittest.main()
