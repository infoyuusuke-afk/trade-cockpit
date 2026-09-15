"""JPX calendar and TDnet catalysts. Kabutan is a human review link only."""
from __future__ import annotations

import io
import json
import re
import sys
import traceback
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
import yfinance as yf
from lxml import html as LH

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
JPX = 'https://www.jpx.co.jp/listing/event-schedules/financial-announcement/index.html'
TDNET = 'https://www.release.tdnet.info/inbs/'
OUT = ROOT / 'earnings_calendar.json'
EVIDENCE = ROOT / 'artifacts/earnings-calendar'

# モメンタムレーン＋的中率自己検証（旧scripts/upcoming_earnings.pyより統合、2026-09-15）。
# 2系統に分かれていた決算カレンダーをこのファイルへ一本化する際、upcoming_earnings.py
# 独自の価値だった「方向レーンの継続的な的中率検証」だけを移植した。ログファイルは
# 同じパスを使い続けることで、これまでの検証履歴を引き継ぐ。
LOG_PATH = ROOT / 'data/earnings_predictions_log.json'
MOMENTUM_MIN_N = 20


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 trade-cockpit-public-disclosures/1.0'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read()
        print(json.dumps({'fetch': url, 'http': resp.status, 'bytes': len(body)}, ensure_ascii=False), flush=True)
        return body


def code_of(value):
    s = re.sub(r'\.0$', '', str(value).strip())
    return s if re.fullmatch(r'(?:\d{4}|\d{3}[A-Z])', s) else None


def parse_schedule(frame, source, today):
    """Only header-labelled announcement dates; never interpret fiscal-end dates."""
    result = []
    header = None
    for _, row in frame.iterrows():
        cells = [str(x).strip().replace('\n', '').replace(' ', '').replace('\u3000', '') for x in row]
        code_col = next((i for i,x in enumerate(cells) if 'コード' in x), None)
        date_col = next((i for i,x in enumerate(cells) if ('発表' in x or '開示' in x) and ('日' in x or '予定' in x)), None)
        name_col = next((i for i,x in enumerate(cells) if any(k in x for k in ['会社名', '銘柄名', '商号'])), None)
        if code_col is not None and date_col is not None and name_col is not None:
            header = (code_col, date_col, name_col)
            continue
        if header is None:
            continue
        ci, di, ni = header
        code = code_of(row.iloc[ci])
        value = row.iloc[di]
        if not code or pd.isna(value):
            continue
        # Reject numeric Excel values rather than silently treating them as nanoseconds.
        if isinstance(value, (int, float)):
            continue
        try:
            stamp = pd.Timestamp(value).date()
        except (ValueError, TypeError):
            continue
        if today - timedelta(days=7) <= stamp <= today + timedelta(days=60):
            result.append({'code': code, 'name': str(row.iloc[ni]).strip(), 'date': stamp.isoformat(),
                           'source_url': source, 'source': 'JPX公表予定', 'status': '予定（変更あり）'})
    return result, header is not None


def calendar(today):
    raw = fetch(JPX)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / 'jpx.html').write_bytes(raw)
    doc = LH.fromstring(raw)
    urls = list(dict.fromkeys(urljoin(JPX, u) for u in doc.xpath('//a/@href') if re.search(r'\.xlsx?(?:$|\?)', u, re.I)))
    if not urls:
        raise ValueError('JPX schedule spreadsheet links not found')
    events, sources = [], []
    for index, url in enumerate(urls[-4:]):
        body = fetch(url)
        (EVIDENCE / f'schedule-{index}.{url.split(".")[-1]}').write_bytes(body)
        sheets = pd.read_excel(io.BytesIO(body), sheet_name=None, header=None)
        found = False
        rows = []
        for name, frame in sheets.items():
            parsed, recognized = parse_schedule(frame, url, today)
            print(json.dumps({'sheet': name, 'header_recognized': recognized, 'events': len(parsed),
                              'sample_rows': frame.head(8).fillna('').astype(str).values.tolist()}, ensure_ascii=False), flush=True)
            rows.extend(parsed)
            found |= recognized
        if not found:
            raise ValueError(f'Unrecognized JPX schedule headers: {url}')
        events.extend(rows)
        sources.append({'url': url, 'events': len(rows)})
    unique = {(e['code'], e['date']): e for e in events}
    return sorted(unique.values(), key=lambda e:(e['date'], e['code'])), sources


def classify(title):
    tags = []
    corrected = bool(re.search('訂正|取消|撤回', title))
    if corrected:
        tags.append('訂正・取消確認')
    if '上方修正' in title:
        tags.append('上方修正')
    if '下方修正' in title:
        tags.append('下方修正')
    if '増配' in title:
        tags.append('増配')
    if '減配' in title or '無配' in title:
        tags.append('減配・無配')
    if '業績予想' in title and '修正' in title and not any(t in tags for t in ['上方修正','下方修正']):
        tags.append('業績修正・方向要確認')
    if '配当' in title and ('修正' in title or '剰余金' in title) and not any(t in tags for t in ['増配','減配・無配']):
        tags.append('配当変更・内容要確認')
    if '決算短信' in title:
        tags.append('決算発表')
    if '特別利益' in title:
        tags.append('一過性利益')
    if '特別損失' in title:
        tags.append('一過性損失')
    return tags


def parse_disclosures(raw, day, now):
    doc = LH.fromstring(raw.decode('utf-8') if isinstance(raw, bytes) else raw)
    events = []
    for tr in doc.xpath('//tr'):
        cells = tr.xpath('./td')
        if len(cells) < 4:
            continue
        text = [' '.join(c.itertext()).strip() for c in cells]
        if not re.fullmatch(r'\d{2}:\d{2}', text[0]):
            continue
        raw_code = text[1]
        code = code_of(raw_code[:-1]) if re.fullmatch(r'(?:\d{4}|\d{3}[A-Z])0', raw_code) else None
        if not code:
            continue
        title = text[3]
        tags = classify(title)
        if not tags:
            continue
        published = datetime.fromisoformat(f'{day}T{text[0]}:00+09:00')
        if published > now:
            continue
        links = cells[3].xpath('.//a/@href')
        if not links:
            continue
        events.append({'code': code, 'name': text[2], 'title': title, 'published_at': published.isoformat(),
                       'date': day, 'source_url': urljoin(TDNET, links[0]), 'tags': tags,
                       'basis': 'TDnet表題。数値・本文はリンク先で確認', 'forecast_probability': None})
    return events, doc


def disclosures(now):
    events, coverage, errors = [], [], []
    for offset in range(4):
        day = (now.date() - timedelta(days=offset)).isoformat()
        compact = day.replace('-', '')
        url = TDNET + f'I_list_001_{compact}.html'
        seen = set()
        pages = 0
        while url and pages < 8:
            if url in seen:
                break
            seen.add(url)
            try:
                raw = fetch(url)
            except Exception as exc:
                errors.append({'url': url, 'error': f'{type(exc).__name__}: {exc}'})
                break
            (EVIDENCE / f'tdnet-{compact}-{pages}.html').write_bytes(raw)
            parsed, doc = parse_disclosures(raw, day, now)
            visible = doc.text_content()
            if '開示' not in visible and '情報' not in visible:
                errors.append({'url': url, 'error': 'Unrecognized TDnet page'})
                break
            events.extend(parsed)
            pages += 1
            next_urls = [urljoin(url, a.get('href')) for a in doc.xpath('//a[@href]')
                         if '次へ' in (a.text_content() + ' '.join(a.xpath('.//img/@alt'))) and f'_{compact}.html' in a.get('href')]
            for node in doc.xpath('//*[@onclick]'):
                if '次へ' not in node.text_content():
                    continue
                match = re.fullmatch(r"pager\('(I_list_\d{3}_\d{8}\.html)'\)", node.get('onclick', ''))
                if match and f'_{compact}.html' in match.group(1):
                    next_urls.append(urljoin(url, match.group(1)))
            url = next_urls[0] if next_urls else None
        coverage.append({'date': day, 'pages': pages, 'truncated': bool(url and pages >= 8)})
    return list({e['source_url']: e for e in events}.values()), coverage, errors


def analysis(event, items):
    same = [x for x in items if x['code'] == event['code']]
    tags = list(dict.fromkeys(t for x in same for t in x['tags']))
    if any(t in tags for t in ['訂正・取消確認','下方修正','減配・無配']):
        label = '警戒材料あり'
    elif any(t in tags for t in ['上方修正','増配']):
        label = '発表済み好材料あり'
    elif same:
        label = '関連開示を確認'
    else:
        label = '未発表・期待判断の根拠不足'
    checks = ['通期計画と進捗率・前年同期の季節性', '営業利益と一過性損益の区別',
              '会社予想と市場予想の差', '増配の実質額（株式分割調整後）', '決算前の株価上昇・織り込み']
    return {'label': label, 'recent_tags': tags, 'evidence_urls': [x['source_url'] for x in same],
            'upward_revision_probability': None, 'checks': checks,
            'note': '直近開示の整理。次回上方修正や株価上昇の予測ではありません。'}


def momentum_lean(code):
    """直近モメンタムに基づく仮説的な方向レーン。決算内容そのものの予測ではない。
    旧upcoming_earnings.pyから移植（ロジックは変更していない）。"""
    ticker = code + '.T'
    try:
        raw = yf.download(ticker, period='30d', interval='1d', auto_adjust=False, progress=False)
        if raw is None or raw.empty or len(raw) < 6:
            return {'available': False, 'reason': '価格データ不足'}
        closes = raw['Close'].dropna()
        if hasattr(closes, 'squeeze'):
            closes = closes.squeeze()
        last = float(closes.iloc[-1])
        ret5 = (last / float(closes.iloc[-6]) - 1) * 100 if len(closes) >= 6 else None
        ret20 = (last / float(closes.iloc[-21]) - 1) * 100 if len(closes) >= 21 else None
        lean_source = ret5 if ret5 is not None else ret20
        if lean_source is None:
            direction = '中立'
        elif lean_source >= 2:
            direction = '上昇レーン（モメンタムのみ・決算内容は未考慮）'
        elif lean_source <= -2:
            direction = '下落レーン（モメンタムのみ・決算内容は未考慮）'
        else:
            direction = '中立'
        return {
            'available': True,
            'last_close': round(last, 1),
            'return_5d_pct': round(ret5, 2) if ret5 is not None else None,
            'return_20d_pct': round(ret20, 2) if ret20 is not None else None,
            'momentum_direction': direction,
        }
    except Exception as e:  # noqa: BLE001
        return {'available': False, 'reason': str(e)}


def load_log():
    if not LOG_PATH.exists():
        return []
    try:
        return json.loads(LOG_PATH.read_text(encoding='utf-8'))
    except Exception:
        return []


def save_log(log):
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def resolve_pending(log, today):
    """target_dateを過ぎた過去の予想について、実際の値動きを取得し的中判定を確定する。"""
    for entry in log:
        if entry.get('status') != 'pending':
            continue
        try:
            target = datetime.strptime(entry['target_date'], '%Y-%m-%d').date()
        except Exception:
            continue
        if target >= today:
            continue  # まだ結果が出る日を迎えていない
        ticker = entry['code'] + '.T'
        try:
            raw = yf.download(ticker, period='10d', interval='1d', auto_adjust=False, progress=False)
            if raw is None or raw.empty:
                continue
            raw = raw[raw.index.date >= target]
            if len(raw) < 2:
                continue
            before = float(raw['Close'].iloc[0])
            after = float(raw['Close'].iloc[1])
            actual_pct = (after / before - 1) * 100
            actual_direction = '上昇' if actual_pct > 0.5 else ('下落' if actual_pct < -0.5 else '中立')
            predicted = entry.get('momentum_direction', '')
            hit = (
                ('上昇' in predicted and actual_direction == '上昇')
                or ('下落' in predicted and actual_direction == '下落')
                or (predicted == '中立' and actual_direction == '中立')
            )
            entry['status'] = 'resolved'
            entry['actual_return_pct'] = round(actual_pct, 2)
            entry['actual_direction'] = actual_direction
            entry['hit'] = hit
        except Exception:  # noqa: BLE001
            continue
    return log


def apply_momentum(events, today):
    """カレンダー中、直近で最も近い『次の決算発表日』の銘柄だけにモメンタムレーンを付与する。
    60日先まで全銘柄に付けると計算コストが大きく、決算直前の参考情報という原意からも外れるため。
    JPXの日程表は銘柄ごとに実際の発表日を持つので、旧upcoming_earnings.pyが抱えていた
    『翌営業日』とカレンダー上の翌暦日のズレ（土日を挟むと不一致になる）は発生しない。"""
    future_dates = sorted({e['date'] for e in events if e['date'] > today.isoformat()})
    target_date = future_dates[0] if future_dates else None
    log = load_log()
    existing_keys = {(e.get('code'), e.get('target_date')) for e in log}
    if target_date:
        for event in events:
            if event['date'] != target_date:
                continue
            momentum = momentum_lean(event['code'])
            event['momentum'] = momentum
            key = (event['code'], target_date)
            if key not in existing_keys and momentum.get('available'):
                log.append({
                    'code': event['code'],
                    'name': event['name'],
                    'target_date': target_date,
                    'logged_at': datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S JST'),
                    'momentum_direction': momentum.get('momentum_direction'),
                    'return_5d_pct': momentum.get('return_5d_pct'),
                    'status': 'pending',
                })
    log = resolve_pending(log, today)
    save_log(log)
    resolved = [e for e in log if e.get('status') == 'resolved']
    n = len(resolved)
    hits = sum(1 for e in resolved if e.get('hit'))
    hit_rate = round(hits / n * 100, 1) if n else None
    validation = {
        'resolved_n': n,
        'hit_rate_pct': hit_rate,
        'min_n_threshold': MOMENTUM_MIN_N,
        'status': '参考値（要検証）' if n >= MOMENTUM_MIN_N else '試運転・検証中（サンプル不足）',
    }
    return target_date, validation


def main():
    now = datetime.now(JST)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    errors = []
    events, sources = [], []
    try:
        events, sources = calendar(now.date())
    except Exception as exc:
        traceback.print_exc()
        errors.append({'source': 'JPX', 'error': f'{type(exc).__name__}: {exc}'})
    items, coverage, disclosure_errors = disclosures(now)
    errors.extend(disclosure_errors)
    config = json.loads((ROOT / 'ms2_live/watchlist_100.json').read_text(encoding='utf-8-sig'))
    watched = {x['ticker'].split('.')[0] for x in config.get('stocks', {}).values() if 'ticker' in x}
    for event in events:
        event['watched'] = event['code'] in watched
        event['analysis'] = analysis(event, items)
    for item in items:
        item['watched'] = item['code'] in watched
    momentum_target_date, momentum_validation = apply_momentum(events, now.date())
    result = {'schema_version': 1, 'updated_at': now.isoformat(), 'calendar': events,
              'catalysts': sorted(items, key=lambda x:x['published_at'], reverse=True),
              'sources': sources, 'disclosure_coverage': coverage, 'errors': errors,
              'calendar_status': 'error' if any(e.get('source') == 'JPX' for e in errors) else 'ok',
              'coverage_note': 'JPX掲載月次表の前7日〜先60日（掲載対象のみ、全銘柄網羅ではない）。TDnetは直近4暦日・各日最大8ページ。',
              'kabutan_calendar_url': 'https://s.kabutan.jp/warnings/news_schedule/',
              'analysis_note': '上方修正等は表題で明示されたものだけ分類。方向不明の修正は要確認。確率や決算前の上昇予測は未算出。',
              'momentum_target_date': momentum_target_date,
              'momentum_validation': momentum_validation,
              'momentum_note': 'momentum_directionは決算内容そのものの予測ではなく、直近5日/20日の株価モメンタムのみに'
                                '基づく仮説的な参考値。カレンダー中、直近の発表日の銘柄だけに付与する。'}
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'calendar': len(events), 'catalysts': len(items), 'errors': errors}, ensure_ascii=False))
    # Always publish fresh source status; the workflow validates health after committing.
    return result


if __name__ == '__main__':
    main()
