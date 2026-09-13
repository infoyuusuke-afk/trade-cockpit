"""
mention_tracker.py
SNS/メディアで話題化する銘柄を監視する仕組みの一部。
YouTube側は「複数チャンネルを横断監視」できるよう一般化してある
（Jumping Point!! はその一例であり、これに固執しない設計）。
チャンネルの追加は WATCHED_CHANNELS に1行足すだけでよい。

各チャンネルの新着動画を、YouTube公式のチャンネルRSS（認証不要）で検知し、
mentions.json に追記する。

重要な設計方針（未来データ混入を防ぐため）:
  - このスクリプトはGitHub Actionsで定期実行し、
    「実行した瞬間にRSSに存在した動画」だけを記録する。
  - 各レコードには published_at（動画側のタイムスタンプ）と
    detected_at（このスクリプトが検知した時刻）の両方を残す。
  - タイトル・説明欄からの銘柄コード自動抽出はベストエフォート。
    confirmed_tickers へ手動で転記してから分析に使うこと。

制約:
  - 開発時のサンドボックス環境からはYouTubeへのアクセスが許可されておらず、
    実地テストはできていない。初回導入時は workflow_dispatch で手動実行し、
    mentions.json の中身を必ず確認すること。
"""
import json
import re
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from xml.etree import ElementTree

JST = timezone(timedelta(hours=9))

# 監視対象チャンネル一覧。ここに追加していく（Jumping Pointは一例に過ぎない）。
WATCHED_CHANNELS = [
    {"id": "UCgDa6dxD3jPElw6eCvL1T2g", "label": "Jumping Point!! の株Tube"},
    {"id": "UCOfzLmXpI3qmZfV7_Cs1sYA", "label": "暁投資顧問"},
    {"id": "UCOX7X_ddhi1oXurSbJsk45Q", "label": "NOBU塾"},
    {"id": "UCy_ybB4lQ3HwwYfTkvRNJLg", "label": "1UP投資部屋"},
    {"id": "UC5Qgc-tEFmm5iQX5tUy6TyA", "label": "株リアルライブ"},
    {"id": "UCLd1GI9tIzrxy-3C4undbUw", "label": "億万株姫☆あばねちゃん"},
    {"id": "UCfJEDCUlzQl4-atLp6Z9DcQ", "label": "テスタ（公式テスタの部屋）"},
    {"id": "UCKgYBpx2O-LpvvrxulnoRjA", "label": "マステアのデイトレ配信"},
    {"id": "UCxcgtAiWkiSm9BW_u_5OhQA", "label": "イズミダイズム（泉田良輔）"},
    {"id": "UCo6dMRnCsGl76JK_BnC0W-Q", "label": "パラディン森永（森永康平のリアル経済学）"},
    {"id": "UCmvEkXw4pLZsOlDxCOwEWIw", "label": "【株Biz】勉強会TV"},
    {"id": "UCdQdRRLoajrt-5TEaAxslxA", "label": "トレーダーTOMO"},
    # CIS: YouTubeチャンネルを持たずX(@cissan_9984)中心のため対象外
]
STORE = Path("mentions.json")

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "media": "http://search.yahoo.com/mrss/",
    "yt": "http://www.youtube.com/xml/schemas/2015",
}

TICKER_PATTERN = re.compile(r"([ぁ-んァ-ヶー一-龠a-zA-Zａ-ｚＡ-Ｚ0-9０-９・&＆\.\-]{2,20}?)[（(](\d{3,4}[A-Z]?)[）)]")


def fetch_feed(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "trade-cockpit-mention-tracker/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read()


def extract_tickers(text: str) -> list[dict]:
    if not text:
        return []
    seen = {}
    for m in TICKER_PATTERN.finditer(text):
        name, code = m.group(1).strip(), m.group(2)
        seen[code] = name
    return [{"code": code, "name": name} for code, name in seen.items()]


def load_store() -> dict:
    if STORE.exists():
        return json.loads(STORE.read_text(encoding="utf-8"))
    return {"channels": WATCHED_CHANNELS, "videos": []}


def save_store(data: dict) -> None:
    STORE.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch_channel(channel: dict, known_ids: set, now: datetime) -> list[dict]:
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel['id']}"
    try:
        xml_bytes = fetch_feed(url)
    except Exception as e:  # noqa: BLE001
        print(f"[{channel['label']}] RSS取得失敗: {e}")
        return []

    root = ElementTree.fromstring(xml_bytes)
    new_records = []
    for entry in root.findall("atom:entry", NS):
        video_id_el = entry.find("yt:videoId", NS)
        if video_id_el is None or video_id_el.text in known_ids:
            continue
        title = (entry.findtext("atom:title", default="", namespaces=NS) or "").strip()
        published = entry.findtext("atom:published", default="", namespaces=NS)
        group = entry.find("media:group", NS)
        description = ""
        if group is not None:
            description = group.findtext("media:description", default="", namespaces=NS) or ""

        tickers = extract_tickers(title) + extract_tickers(description)
        uniq = {t["code"]: t for t in tickers}

        new_records.append({
            "channel_id": channel["id"],
            "channel_label": channel["label"],
            "video_id": video_id_el.text,
            "title": title,
            "published_at": published,  # YouTube側のタイムスタンプ（UTC/ISO8601）
            "detected_at": now.strftime("%Y-%m-%d %H:%M:%S JST"),
            "auto_extracted_tickers": list(uniq.values()),
            "confirmed_tickers": [],  # 手動確認後にここへ転記する（自動抽出は信用しすぎない）
            "note": "自動抽出は誤検出の可能性あり。confirmed_tickersへ手動で確定させてから分析に使うこと。",
        })
    return new_records


def main():
    store = load_store()
    store["channels"] = WATCHED_CHANNELS  # 監視対象リストは常に最新の設定で上書き
    known_ids = {v["video_id"] for v in store["videos"]}
    now = datetime.now(JST)

    total_new = 0
    for channel in WATCHED_CHANNELS:
        new_records = fetch_channel(channel, known_ids, now)
        store["videos"].extend(new_records)
        known_ids.update(r["video_id"] for r in new_records)
        total_new += len(new_records)
        print(f"[{channel['label']}] 新着{len(new_records)}件")

    if total_new:
        save_store(store)
    print(f"合計新着: {total_new}件（累計{len(store['videos'])}件）")


if __name__ == "__main__":
    main()
