"""
board_buzz_ranking.py
「SNS全般のあおり銘柄を監視したい」という要件の中核になるスクリプト。

Jumping Point!! のような特定チャンネルに依存せず、Yahoo!ファイナンスが公式に
毎日発表している「掲示板投稿数ランキング」（全市場・日次）を取得する。
これは特定の1配信者ではなく、Yahoo!ファイナンス掲示板全体での書き込み量を
集計した公開ランキングであり、"次のキオクシア"を探すための
一般的なSNS/メディア注目度シグナルとして最も入手性が良い情報源。

出典: https://finance.yahoo.co.jp/stocks/ranking/bbs?market=all
      （認証不要・日次更新。更新頻度や表示件数は先方都合で変わりうる）

設計方針（未来データ混入を防ぐため）:
  - 取得した瞬間のランキングだけを記録し、retrieved_at を必ず残す。
  - 前回保存分との差分から「新規ランクイン」「順位急上昇」を検知するが、
    これは観測用のフラグに過ぎず、単独で売買判断に使わない
    （watch_top5.py 同様、スコアには一切混ぜない）。

重要な制約（正直な申告）:
  - このページのHTML構造は実際に取得して確認したが、開発環境からは
    実際のスクレイピング処理を最後まで動作確認できていない
    （サンドボックス環境からYahoo!ファイナンスへの接続が許可されていないため）。
  - Yahoo側のマークアップ変更で正規表現が効かなくなる可能性は
    mention_tracker.py のRSS方式より高い。導入後、最初の数回は
    GitHub Actionsの実行ログと board_buzz_history.json の中身を
    必ず目視で確認すること。抽出0件が続く場合はHTML構造の変更を疑う。
"""
import re
import json
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

JST = timezone(timedelta(hours=9))
URL = "https://finance.yahoo.co.jp/stocks/ranking/bbs?market=all"
STORE = Path("board_buzz_history.json")
KEEP_DAYS = 60  # 直近60営業日ぶんだけ保持（無限に肥大化させない）

# 銘柄コード＋市場区分のパターン: 例 "285A東証PRM" "3350東証STD"
CODE_MARKET_RE = re.compile(r"(\d{3,4}[A-Z]?)(東証[A-Z]{3}|名証\w{2,4}|札証|福証)")
# 銘柄名リンクのパターン: 例 <a href=".../quote/285A.T">キオクシアホールディングス(株)</a>
NAME_LINK_RE = re.compile(r'href="[^"]*quote/(\d{3,4}[A-Z]?)\.T"[^>]*>([^<]{1,40})</a>')


def fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (trade-cockpit-buzz-tracker/1.0)"
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_ranking(html: str) -> list[dict]:
    names = {code: name.strip() for code, name in NAME_LINK_RE.findall(html)}
    rows = []
    rank = 0
    for code, market in CODE_MARKET_RE.findall(html):
        rank += 1
        rows.append({
            "rank": rank,
            "code": code,
            "market": market,
            "name": names.get(code, ""),
        })
    return rows


def load_history() -> list[dict]:
    if STORE.exists():
        return json.loads(STORE.read_text(encoding="utf-8"))
    return []


def save_history(history: list[dict]) -> None:
    STORE.write_text(json.dumps(history[-KEEP_DAYS:], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def diff_flags(today_rows: list[dict], prev_rows: list[dict]) -> dict:
    """観測用のフラグのみ。売買判断には使わない。"""
    prev_rank = {r["code"]: r["rank"] for r in prev_rows}
    new_entries, jumped = [], []
    for r in today_rows:
        if r["code"] not in prev_rank:
            new_entries.append(r["code"])
        elif prev_rank[r["code"]] - r["rank"] >= 10:
            jumped.append({"code": r["code"], "from_rank": prev_rank[r["code"]], "to_rank": r["rank"]})
    return {"new_entries": new_entries, "rank_jumped": jumped}


def main():
    try:
        html = fetch_html(URL)
    except Exception as e:  # noqa: BLE001
        print(f"取得失敗: {e}")
        return

    rows = parse_ranking(html)
    if not rows:
        print("警告: 0件抽出。HTML構造が変わった可能性が高い。手動で確認してください。")
        return

    history = load_history()
    prev_rows = history[-1]["rankings"] if history else []
    flags = diff_flags(rows, prev_rows)

    snapshot = {
        "date": datetime.now(JST).date().isoformat(),
        "retrieved_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST"),
        "source": URL,
        "rankings": rows[:50],
        "observation_only_flags": flags,
        "note": "売買判断には使わない。次のキオクシア探索の観測材料としてのみ利用する。",
    }
    history.append(snapshot)
    save_history(history)
    print(f"{len(rows)}件抽出。新規ランクイン{len(flags['new_entries'])}件、急上昇{len(flags['rank_jumped'])}件")


if __name__ == "__main__":
    main()
