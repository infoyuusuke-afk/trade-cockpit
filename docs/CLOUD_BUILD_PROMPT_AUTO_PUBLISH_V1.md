# Claude Code / Cloud Build Prompt — AUTO PUBLISH V1 R1

Work from branch: `design/auto-publisher-v1`.
Read `docs/AUTO_PUBLISH_SYSTEM_SPEC.md` first.

Goal: implement Release Gate R1 (DRY-RUN) only.

Requirements:
1. Create `auto_publish/` as an independent Python 3.12 subsystem.
2. It must have zero imports from AI Cockpit runtime process/control code. Reading exported JSON/CSV files is allowed through explicit input paths only.
3. Implement pipeline states:
   `INGEST -> VALIDATE -> STORY_SELECT -> FACT_CHECK -> SCRIPT -> LOCALIZE -> ASSET_RENDER -> APPROVAL -> SCHEDULE`.
   STOP before PUBLISH.
4. Use SQLite for queue/state. Every story must have stable `story_id`, evidence refs, SHA256s, target language, target platform, schedule time, and pipeline state.
5. Implement `DryRunPublisher` only. It writes the exact payload that WOULD be sent to a platform, but never performs network publishing.
6. Implement a post-market scheduler:
   - Europe baseline wave 22:00–00:00 JST.
   - North America short-video baseline wave 05:00–10:00 JST next day.
   - all scheduling timezone-aware; add DST tests.
7. Render one 9:16 1080x1920 MP4 using FFmpeg from a deterministic fixture:
   - title/hook
   - 3 evidence-backed bullets
   - burned-in English captions
   - end disclaimer
   If FFmpeg is unavailable in CI, provide a deterministic command builder plus a test fixture and CI installation step rather than silently skipping.
8. Add compliance checks:
   - reject unsupported profit claims;
   - distinguish paper/shadow from real;
   - reject missing source refs;
   - reject date mismatches;
   - reject empty captions/scripts.
9. Add CLI:
   - `python -m auto_publish.cli ingest --input <dir>`
   - `... build-drafts --date YYYY-MM-DD`
   - `... queue`
   - `... approve <story_id>`
   - `... schedule <story_id>`
   - `... pause-all`
10. Add tests for:
   - idempotency
   - duplicate prevention
   - source hash provenance
   - timezone/DST
   - approval required
   - no network publication
   - fail-closed on missing/stale evidence
11. Add `auto_publish/README.md` with local Windows setup.
12. Add architecture diagram in Mermaid.
13. Do not touch 28580/28581/28582/28583.
14. Do not reference RssOrder, broker submit, or real-order code.
15. Do not modify the current V9 AI Cockpit UI.
16. No merge to main. Open one PR from this branch or a child branch and report SHA/test results.

Acceptance:
- full test suite green;
- one fixture produces a complete artifact directory with draft JSON + schedule + render manifest;
- `rg -n "RssOrder|28580|28581|28582|28583" auto_publish` proves no runtime coupling (README may mention the prohibition only);
- no HTTP POST to social platforms exists in R1.
