"""
margin_caution_check.py
SHORT側の「実際に信用売りできるか」の判定材料の一つとして、東証が毎日公表している
「日々公表銘柄」（信用取引残高の公表を日々行うことで注意を促している銘柄）を取得する。

出典: https://www.jpx.co.jp/markets/equities/margin-daily/
      （認証不要、日次更新、東証公式）

重要な注意点（東証の説明そのまま）:
  「日々公表銘柄」への指定は、それ自体は信用取引の規制措置ではない。
  ただし指定銘柄名の先頭に ※ が付いている銘柄は「信用取引に関する規制を行っている銘柄」
  （実際に新規建てが制限されている等）であり、これはSHORT不可の強いシグナルになる。
  ◆は「特別周知銘柄」（周知の措置のみ、規制ではない）。

  つまり:
    ※あり → regulated: true（新規の信用売りができない可能性が高い。要個別確認）
    ※なし → regulated: false（日々公表銘柄ではあるが、規制措置そのものではない）

  楽天証券固有の「一般信用売りの在庫切れ」「品貸料（逆日歩）」はこのページからは
  分からない。これは楽天証券側のリアルタイム情報を別途確認する必要があり、
  今回のスクリプトではカバーしていない（残タスク）。

出力: margin_caution.json
  {"updated_at": "...", "source": "...", "designated": [{"code":..., "name":..., "regulated": bool, "designated_date":...}], "released_recently": [...]}
"""
import re
import io
import json
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd

JST = timezone(timedelta(hours=9))
URL = "https://www.jpx.co.jp/markets/equities/margin-daily/index.html"
OUT = Path("margin_caution.json")

CODE_RE = re.compile(r"\b(\d{3,4}[A-Z]?)\b")


def fetch_html(url: str) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (trade-cockpit-margin-check/1.0)"
    })
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_designated(html: str) -> tuple[list[dict], list[dict]]:
    try:
        tables = pd.read_html(io.StringIO(html))
    except ValueError:
        return [], []

    designated, released = [], []
    for df in tables:
        cols = [str(c) for c in df.columns]
        if not any("コード" in c for c in cols):
            continue
        date_col = next((c for c in cols if "指定日" in c or "解除日" in c), None)
        name_col = next((c for c in cols if "銘柄" in c), cols[0])
        code_col = next((c for c in cols if "コード" in c), cols[1] if len(cols) > 1 else cols[0])
        is_released = date_col and "解除日" in date_col
        target = released if is_released else designated

        for _, row in df.iterrows():
            raw_name = str(row.get(name_col, ""))
            code_val = str(row.get(code_col, "")).strip()
            m = CODE_RE.search(code_val) or CODE_RE.search(raw_name)
            if not m:
                continue
            regulated = raw_name.strip().startswith("※") or "※" in raw_name
            target.append({
                "code": m.group(1),
                "name": raw_name.lstrip("※◆").strip(),
                "regulated": regulated,
                "date": str(row.get(date_col, "")) if date_col else None,
            })
    return designated, released


def main():
    try:
        html = fetch_html(URL)
    except Exception as e:  # noqa: BLE001
        print(f"取得失敗: {e}")
        return

    designated, released = parse_designated(html)
    if not designated:
        print("警告: 0件抽出。HTML構造が変わった可能性が高い。手動で確認してください。")
        return

    out = {
        "updated_at": datetime.now(JST).strftime("%Y-%m-%d %H:%M:%S JST"),
        "source": URL,
        "note": (
            "regulated=trueは東証が新規信用取引等を規制している銘柄（SHORT不可の強いシグナル）。"
            "regulated=falseは日々公表銘柄ではあるが規制措置そのものではない。"
            "楽天証券固有の一般信用在庫切れ・逆日歩はこのデータではカバーしていない（別途確認要）。"
        ),
        "designated": designated,
        "released_recently": released,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"日々公表銘柄 {len(designated)}件（うち規制中{sum(d['regulated'] for d in designated)}件）、解除{len(released)}件")


if __name__ == "__main__":
    main()
