import { chromium } from "playwright";
import fs from "node:fs";

const browser = await chromium.launch({headless:true});
const cases = [
  {name:"desktop", width:1440, height:900},
  {name:"mobile", width:375, height:812},
];

try {
  for (const c of cases) {
    const page = await browser.newPage({viewport:{width:c.width,height:c.height}});
    await page.goto("http://127.0.0.1:8765/index.html?live=1", {waitUntil:"domcontentloaded", timeout:30000});
    await page.waitForFunction(() => document.documentElement.classList.contains("cc-all-cards-ready"), null, {timeout:10000});
    await page.waitForFunction(() => {
      const panes=document.querySelectorAll(".tab-pane").length;
      return panes>0 &&
        document.querySelectorAll(".cc-tab-owner-summary").length===panes &&
        !!document.querySelector("#weekly-review .cc-grid .cc-card");
    }, null, {timeout:10000});
    await page.waitForTimeout(200);

    const state = await page.evaluate(() => {
      const visible = el => {
        const s=getComputedStyle(el);
        return !el.hidden && s.display!=="none" && s.visibility!=="hidden";
      };
      const visibleTables=[...document.querySelectorAll("main table")].filter(visible);
      const cards=[...document.querySelectorAll(".cc-data-card")].filter(visible);
      const main=document.querySelector("main");
      const badCardOverflow=cards.filter(el=>el.scrollWidth>el.clientWidth+2).length;
      return {
        visibleTables:visibleTables.length,
        cards:cards.length,
        hasTradeDrawer:!!document.querySelector("#trade-drawer"),
        hasKioxiaChart:!!document.querySelector("#kio-best-path"),
        mainOverflow:main ? Math.max(0,main.scrollWidth-main.clientWidth) : 0,
        badCardOverflow,
        speechSynthesisSource:document.documentElement.innerHTML.includes("SpeechSynthesisUtterance"),
        hasControlTab:!!document.querySelector('.cockpit-tab[data-tab="control"]'),
        ownerSummaries:document.querySelectorAll(".cc-tab-owner-summary").length,
        paneCount:document.querySelectorAll(".tab-pane").length,
        hasPtsVoiceSwitch:!!document.querySelector(".pts-section-head [data-voice-toggle]"),
        legacyScalpCards:document.querySelectorAll("article.scalp-card").length,
        weeklyUsesSharedCards:!!document.querySelector("#weekly-review .cc-grid .cc-card"),
      };
    });

    if (state.visibleTables !== 0) throw new Error(c.name+": visible raw tables="+state.visibleTables);
    if (state.cards < 20) throw new Error(c.name+": too few converted cards="+state.cards);
    if (state.hasTradeDrawer) throw new Error(c.name+": non-Kioxia trade drawer still exists");
    if (!state.hasKioxiaChart) throw new Error(c.name+": Kioxia chart container missing");
    if (state.mainOverflow > 3) throw new Error(c.name+": main horizontal overflow="+state.mainOverflow);
    if (state.badCardOverflow > 0) throw new Error(c.name+": overflowing cards="+state.badCardOverflow);
    if (state.speechSynthesisSource) throw new Error(c.name+": legacy browser TTS source still present");
    if (!state.hasControlTab) throw new Error(c.name+": CONTROL tab missing");
    if (state.ownerSummaries !== state.paneCount) throw new Error(c.name+": not every tab has owner summary "+state.ownerSummaries+"/"+state.paneCount);
    if (!state.hasPtsVoiceSwitch) throw new Error(c.name+": PTS voice switch missing");
    if (state.legacyScalpCards !== 0) throw new Error(c.name+": legacy scalp cards remain="+state.legacyScalpCards);
    if (!state.weeklyUsesSharedCards) throw new Error(c.name+": weekly review is not Card System");

    await page.screenshot({path:"v9-"+c.name+".png",fullPage:true});
    await page.close();
  }
} finally {
  await browser.close();
}
