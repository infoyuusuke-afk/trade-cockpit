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

パース方式（v2・修正版）:
  初版は正規表現で<a href>タグを直接読む方式にしていたが、実際のHTML構造と
  合わず0件抽出になることを実行結果で確認した（2026-09-14）。
  pandas.read_html()を使い、ページ内の<table>要素をそのままDataFrame化する
  方式に変更。個別のclass名やタグ属性に依存しないため、Yahoo側の細かい
  マークアップ変更に対してより頑健。表内の「名称・コード・市場」列のテキスト
  （例:「キオクシアホールディングス(株)285A東証PRM掲示板」）から、正規表現で
  銘柄コード・市場区分を抜き出し、その手前の文字列を銘柄名とする。

制約（正直な申告）:
  - 開発環境からYahoo!ファイナンスへのアクセス自体ができないため、実際の
    HTML本体を見て検証したわけではない。ページがテーブルタグで構成されている
    ことは以前の取得結果（マークダウン変換後の表示）から推測している。
  - それでも抽出0件が続く場合は、対象ページがJavaScriptでの動的レンダリングに
    切り替わった可能性がある。その場合はplaywright（既存の依存関係）での
    レンダリング取得に切り替える必要がある。
"""
import re
import io
import json
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd

JST = timezone(timedelta(hours=9))
URL = "https://finance.yahoo.co.jp/stocks/ranking/bbs?market=all"
STORE = Path("board_buzz_history.json")
KEEP_DAYS = 60  # 直近60営業日ぶんだけ保持（無限に肥大化させない）

# 銘柄コード＋市場区分のパターン: 例 "285A東証PRM" "3350東証STD"
CODE_MARKET_RE = re.compile(r"(\d{3,4}[A-Z]?)(東証[A-Z]{3}|名証\w{2,4}|札証|福証)")


def fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (trade-cockpit-buzz-tracker/1.0)"
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_ranking(html: str) -> list[dict]:
    try:
        tables = pd.read_html(io.StringIO(html))
    except ValueError:
        return []

    # 「名称・コード・市場」のような列名、または本文にコード+市場パターンを
    # 含む表を探す（列名は先方都合で変わりうるため、中身で判定する）
    target = None
    for df in tables:
        joined = df.astype(str).apply(lambda col: col.str.cat(sep=" "), axis=0)
        text_blob = " ".join(joined.tolist())
        if CODE_MARKET_RE.search(text_blob):
            target = df
            break
    if target is None:
        return []

    rows = []
    rank = 0
    for _, row in target.iterrows():
        row_text = " ".join(str(v) for v in row.tolist())
        m = CODE_MARKET_RE.search(row_text)
        if not m:
            continue
        rank += 1
        code, market = m.group(1), m.group(2)
        name = row_text[:m.start()].strip()
        # 順位列の数字などが先頭に混ざる場合があるので、末尾側の会社名らしい部分を優先
        name = re.sub(r"^\d+\s*", "", name).strip()
        rows.append({"rank": rank, "code": code, "market": market, "name": name})
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

