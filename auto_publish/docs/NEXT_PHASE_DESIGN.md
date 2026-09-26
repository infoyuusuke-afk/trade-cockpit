# Auto Publish — 次フェーズ設計（TTS / 日本語字幕 / 配信時間最適化 / dry-run E2E）

Date: 2026-09-26 JST ・ Base: `design/auto-publisher-v1`（R1_COMPLETE、Acceptance証跡 `0597b81`）

共通の境界（全工程で維持）:
- 実SNS送信なし（生成 → approval → dry-run → SCHEDULED まで）
- broker / RssOrder / real-submit、Scheduled Tasks / autostart は使わない
- AI Cockpit本体（V9/V10 runtime、Excel、MS2、VoiceBridge）とは結合しない。停止処理にも触れない
- private MS2 / account / order / fill / holding 情報は外に出さない
- canonical contract、hash semantics、evidence integrity、data classification の意味は変えない
- 新しい生成物は、既存の仕組み（artifacts表 → content_sha256 → 承認）の中に追加する形にする

---

## 1. TSE営業日カレンダー（実装済み・`08e63a3`）

- データ: `config/tse_calendar.json`
  - JPX 休業日一覧（2026–2027）。内閣府の祝日一覧と照合済み
  - 出典URLと取得日をファイル内に記録
- 判定: 次をすべて満たす日だけを営業日とする
  - カバー年内である
  - 月〜金である
  - JPXの休業日ではない
  - owner追加の臨時休場日（`extra_closures`）ではない
- 失敗時の扱い:
  - 休場日 → `NOT_TRADING_DAY`
  - カバー外の年 → `CALENDAR_UNAVAILABLE`（推測しない）
  - ファイル不正 → `CALENDAR_INVALID`
- 大引け時刻: カレンダーの値を正とする。`session_overrides` で特定日だけ変更できる
- 監査: VALIDATE の監査行にカレンダーのSHA256を記録する
- 運用: 翌年分は、JPXが公表した後に追加する（春分・秋分は前年2月の官報で確定するため）
  - 年初までに追加しないと、その年は fail-closed で止まる。これは意図した挙動

## 2. TTS（ナレーション）設計

### 目的
各セグメントの**承認対象テキストと完全に同一の文**を読み上げる。多言語（en-US / ja-JP、将来は他言語）に拡張できる構造にする。

### 構造
```
TtsProvider (interface)
  synthesize(text, lang, voice) -> AudioClip {path, duration_s, sha256, provider, voice, engine_version}
providers:
  silent       … 現行の無音。常に利用可能（フォールバックではなく明示選択）
  fake_tone    … テスト専用。テキストのハッシュから決定的に音を生成（CI用）
  windows_sapi … Windows標準の System.Speech（オフライン・無料）。PowerShell経由で実行
  espeak_ng    … Linux CI用（apt）。品質は低いが決定的
  （将来）cloud_tts … APIキーと課金が必要なため、owner承認があるまで無効
```
- 設定例（言語ごと）:
  `{"tts": {"en-US": {"provider": "windows_sapi", "voice": "<PCにある英語音声>"}, "ja-JP": {...}}}`
- VOICEVOX 等のローカルHTTPエンジンは、「ネットワーク系importを禁止する」方針と衝突する（localhostでも該当）。使う場合は方針判断が先に必要
- AI Cockpit の VoiceBridge（SBV2）は、分離方針のため使わない

### タイムライン
- セグメント長 = max(最小4.0秒, 音声長 + 0.4秒)。これまでの固定6秒をやめる
- 合計が 20–45秒 に収まらなければ fail-closed（`NARRATION_TOO_LONG`）とし、自動での文章短縮はしない
- 字幕のタイミングもこのセグメント長から作る（字幕と音声を同じ区切りにする）
- 音声処理: セグメントごとのWAV → adelay/concat → loudnorm（-16 LUFS）→ AAC 128k

### 証跡・承認
- 新しい生成物:
  - `narration_{lang}.m4a`
  - `tts_manifest.json`（provider、voice、engine_version、セグメントごとの text_sha256 / audio_sha256 / duration）
- artifacts表に登録し、content_sha256 に含める
  - 音声が変われば承認をやり直す必要がある（既存の仕組みがそのまま効く）
- 読みの辞書（`templates/lexicon_{lang}.json`、例: ティッカーの読み方）
  - 音声用テキストにだけ適用する
  - 変換前後のテキストと辞書のSHA256を manifest に記録する
  - 画面に表示する文は変えない

### テスト
- fake_tone で、決定的なタイムラインと字幕同期を検証する
- 45秒超過時の fail-closed
- provider がタイムアウトした場合は TransientError（再試行）、それ以外の失敗は fail-closed
- テキスト一致の検証（承認対象の文 == TTS入力の文。辞書適用前）

### PC実機作業
- Windowsに入っている音声の一覧を確認する（英語と日本語の音声の有無）
- 試聴用の dry-run を1本作り、承認する

## 3. 日本語字幕 設計

### 構造
- 字幕トラックは言語ごとに `captions_{lang}.srt` を作る
  - 既存の `captions.srt`（en）は互換のため残す
- 動画のバリアント（`render.variants`）:
  - `en_primary`（現行）: 英語字幕を焼き込み。オプションで日本語の補助行を下に小さく表示
  - `ja_primary`: 日本語ナレーション（TTS）＋日本語字幕。国内向け
- 言語ごとのフォント設定（fail-closed）:
  - ja-JP: Windows は Yu Gothic UI / Meiryo、CI は Noto Sans CJK JP
  - フォントが無いまま焼き込もうとしたら `FONT_MISSING`

### 折り返し・禁則
- 文字数ではなく**表示幅**で折り返す（East Asian Width: 全角=2、半角=1）
  - 1行の上限は全角約16文字（44px想定）
- 禁則処理:
  - 行頭に置かない文字: 。、）」』】・ー など
  - 行末に置かない文字: （「『【 など
- 数値と単位（例: 2,345円、+3.02%）は途中で分割しない

### テスト
- 表示幅での折り返しのゴールデンテスト
- 禁則処理のケース
- CJKフォントなしでの fail-closed
- ja字幕とナレーションの区切りが一致すること
- 描画の決定性（同じ入力 → 同じバイト列）

### PC実機作業
- Windowsのフォントで描画した1フレームを、目視で確認する

## 4. 配信時間最適化 設計（海外視聴者向け）

### 段階
1. **現行（baseline）**
   - JST固定の枠: 欧州 22–24時、北米 翌05–07時／08–10時
   - 現地時刻はDST対応済み
2. **計測の受け皿（dry-run期）**
   - `post_metrics` 表を追加する
     - platform、publish_at_utc、wave、audience_tz、local_hour、weekday、lang、template_version、duration
     - views_1h / views_24h / views_7d、retention、likes、shares、comments、follows
   - 実APIが使えない間は、ownerが各プラットフォームの分析画面から書き出したCSVを、読み取り専用で取り込む
3. **最適化（十分なデータが溜まってから）**
   - 起動条件: プラットフォームごとに14日以上、かつ30投稿以上。満たさなければ baseline のまま
   - 候補: 許可された枠の中の30分刻みのスロット（プラットフォームごとの配信可能時間帯ポリシーの範囲内）
   - 評価: 視聴者の現地時刻・曜日ごとに成果（例: views_24h）を正規化する
     - Thompson sampling（ベイズ的な探索手法）で順位を付ける
     - 探索枠は20%にして、baseline の時間帯も一定割合は残す
   - 制約: 二重予約をしない、同一プラットフォームの最小間隔、DST切替週の扱い、東証休場日の扱い
     - 休場日は「その日の記事がない」だけで、配信日自体は制約しない
   - 説明可能性: 選んだスロットと、その理由（スコア・サンプル数・探索/活用の区別）を監査ログに記録する
   - 出力はあくまで提案。承認と dry-run の境界は変えない

### テスト
- データが少ないときは baseline に戻ること
- シードを固定した決定的なランキング
- DST切替週
- 配信窓の外を選ばないこと

## 5. dry-run での end-to-end 配信検証 設計

- **プラットフォームごとの payload 契約テスト**（JSON Schema）
  - 例: YouTube の title は100字以内、TikTok の caption 長さ、X のテキストは280字以内、必須フィールド
  - 動画側の制約: 解像度、尺、サイズ上限
- **would_publish シミュレータ**
  - `publish_at` を過ぎた SCHEDULED を検出し、送信の代わりに `would_publish` 記録を監査ログに書く
  - ネットワークは使わない
  - 二重配信の防止（idempotency key）と、PAUSE / DISABLE / CANCEL が有効なことを、時刻を進めて検証する
- **日次リハーサル**
  - export → ingest → build → （承認）→ schedule → would_publish までをまとめたレポートを出す
  - 実データはローカルでだけ実行し、リポジトリには合成データ（fixture）のE2Eのみ置く
- **キルスイッチ訓練**
  - PAUSE ALL、プラットフォーム停止、予約取消のそれぞれについて、「その後に would_publish が出ないこと」を検証する

---

## 実装順（合意済みの優先順位）

1. TSE営業日カレンダー … **完了**
2. TTS … provider インタフェース、fake_tone / silent、タイムラインの可変化、音声の証跡（Cloudで実施）
   → Windows SAPI provider（PC確認）
3. 日本語字幕 … 字幕トラックの多言語化、表示幅での折り返し、禁則処理、フォントの fail-closed（Cloud）→ PCで目視確認
4. 配信時間最適化 … post_metrics 表と CSV 取り込み → optimizer（データが溜まるまでは baseline のまま）
5. dry-run E2E … payload契約テスト、would_publish シミュレータ、キルスイッチ訓練
