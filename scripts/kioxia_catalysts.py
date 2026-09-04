#!/usr/bin/env python3
"""Build a fail-closed Kioxia catalyst radar from primary-source facts."""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "kioxia_catalysts.json"
JST = ZoneInfo("Asia/Tokyo")
UA = "Mozilla/5.0 (compatible; TradeCockpit/1.0)"

# Facts are entered only after reading the primary release.  A daily HTTP check
# prevents an unavailable or moved source from silently remaining executable.
ITEMS = [
    {
        "date": "2026-08-27", "kind": "設備投資・国策", "stage": "事実確認",
        "title": "Kioxia・Sandiskが2032年までに国内5兆円超を投資",
        "fact": "政府支援を条件に、四日市・北上と関連設備へ総額310億ドル超を投資する計画。",
        "expectation": "AI向けNANDの中長期供給能力を強化。",
        "risk": "投資負担と市況次第。補助・装置発注・稼働時期が未確定の部分を残す。",
        "next_checkpoint": "政府支援、装置発注、投資額・JV負担の具体化",
        "impact": "中長期プラス／短期は織り込み・資本負担を両面評価",
        "lead_score": 61,
        "source_url": "https://www.kioxia.com/en-jp/about/news/2026/20260827-3.html",
    },
    {
        "date": "2026-08-27", "kind": "新工場", "stage": "事実確認",
        "title": "北上工場Fab3の建設準備を開始",
        "fact": "先端BiCS FLASH生産能力拡大へ敷地準備等を開始。稼働目標は2029年度。",
        "expectation": "agentic AI、physical AI、on-device AIによる需要拡大を取り込む計画。",
        "risk": "詳細な建設・設備投資は市場動向と政府支援が条件。短期業績寄与ではない。",
        "next_checkpoint": "着工、装置発注、政府支援、2029年度稼働計画の更新",
        "impact": "中長期プラス／短期は設備投資負担に注意",
        "lead_score": 58,
        "source_url": "https://www.kioxia.com/en-jp/about/news/2026/20260827-2.html",
    },
    {
        "date": "2026-08-12", "kind": "新技術", "stage": "期待形成中",
        "title": "AI向け第9世代2Tb QLC 3Dフラッシュ技術",
        "fact": "6-plane構成、4.8Gb/sインターフェースで第8世代比33%改善と発表。",
        "expectation": "AIインフラ、クラウド、データ集約用途への製品展開。",
        "risk": "技術発表段階。量産時期、採用顧客、受注額、売上寄与は未確認。",
        "next_checkpoint": "製品化、サンプル出荷、量産開始、顧客採用、業績寄与",
        "impact": "先回り監視／受注・量産確認前は単独で買わない",
        "lead_score": 72,
        "source_url": "https://www.kioxia.com/en-jp/about/news/2026/20260812-1.html",
    },
    {
        "date": "2026-06-02", "kind": "技術・経営説明会", "stage": "織り込み進行",
        "title": "Investor Day：AI推論時代の成長戦略",
        "fact": "会社がInvestor Dayを開催し、プレゼン資料・質疑応答を公開。",
        "expectation": "AI推論拡大によるストレージ需要と技術ロードマップ。",
        "risk": "既知材料。新しい数値目標・受注の更新がなければ再評価材料になりにくい。",
        "next_checkpoint": "次回決算、Investor Day目標の進捗、新製品・顧客採用",
        "impact": "既知材料／新情報との差分だけ評価",
        "lead_score": 38,
        "source_url": "https://www.kioxia-holdings.com/ja-jp/ir/library/event.html",
    },
    {
        "date": "2026-08-10", "kind": "自社株買い", "stage": "織り込み完了",
        "title": "自社株買い終了",
        "fact": "1,613万3,500株、約7,999.98億円の市場買付を完了。",
        "expectation": "実施期間中の需給下支え。",
        "risk": "取得は終了済み。継続的な買い需要として加点しない。",
        "next_checkpoint": "新たな取得決議の有無",
        "impact": "材料出尽くし警戒／買い支え終了",
        "lead_score": 15,
        "source_url": "https://ssl4.eir-parts.net/doc/285A/tdnet/2870702/00.pdf",
    },
]


def reachable(url: str) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=25) as res:
            return 200 <= int(res.status) < 400
    except Exception:
        return False


def main() -> None:
    rows = []
    for item in ITEMS:
        row = dict(item)
        row["verified"] = reachable(item["source_url"])
        row["trade_use"] = "参考可" if row["verified"] else "確認待ち・売買利用禁止"
        rows.append(row)
    payload = {
        "name": "キオクシアHD（285A）", "ticker": "285A.T",
        "updated_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST"),
        "policy": "公式IR・公式製品ニュースで確認できた事実だけ掲載。技術発表と売上寄与を分離し、リンク不達は売買利用禁止。",
        "items": rows,
        "verified_count": sum(bool(x["verified"]) for x in rows),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
