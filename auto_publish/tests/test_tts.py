"""TTS: provider policy, deterministic fake_tone, audio-driven timeline, 20-45 s gate,
and narration bound into the approval hash (audio change => approval invalid)."""
import copy
import hashlib
import io
import json
import unittest
import wave
from unittest import mock

from auto_publish.app.config import load_config
from auto_publish.app.errors import EvidenceError, ValidationError
from auto_publish.app.pipeline import (
    ARTIFACT_FILES, LEGACY_ARTIFACT_FILES, approve, build_drafts, retry, schedule, story_dir,
)
from auto_publish.app.hashing import sha256_file, sha256_json, write_json_atomic
from auto_publish.app.tts import narration as tts
from auto_publish.app.tts.base import AudioClip, NarrationLengthError, TtsError, get_provider, wav_bytes
from auto_publish.app.tts.providers import FakeToneProvider
from auto_publish.tests.helpers import GOLDEN_DIR, SESSION, FakeRenderer, PipelineCase

FAKE = {"tts": {"voices": {"en-US": {"provider": "fake_tone"}, "ja-JP": {"provider": "fake_tone"}}}}


def _post(lang="en-US"):
    return json.loads((GOLDEN_DIR / f"TEST1_{lang}.json").read_text(encoding="utf-8"))


def _tts_cfg(**over):
    cfg = copy.deepcopy(load_config()["tts"])
    cfg.update(over)
    return cfg


def _fake_cfg(**over):
    return _tts_cfg(voices={"en-US": {"provider": "fake_tone"}, "ja-JP": {"provider": "fake_tone"}}, **over)


class TestProviderPolicy(unittest.TestCase):
    def test_offline_providers_available(self):
        self.assertEqual(get_provider("silent", 24000).name, "silent")
        self.assertEqual(get_provider("fake_tone", 24000).name, "fake_tone")

    def test_pc_phase_providers_fail_closed(self):
        for name in ("windows_sapi", "espeak_ng"):
            with self.assertRaises(TtsError) as cm:
                get_provider(name, 24000)
            self.assertEqual(cm.exception.code, "TTS_PROVIDER_UNAVAILABLE")

    def test_cloud_provider_is_not_allowed(self):
        with self.assertRaises(ValidationError) as cm:
            get_provider("cloud_tts", 24000)
        self.assertEqual(cm.exception.code, "TTS_PROVIDER_NOT_ALLOWED")
        with self.assertRaises(ValidationError) as cm:
            load_config(overrides={"tts": {"voices": {"en-US": {"provider": "cloud_tts"}}}})
        self.assertEqual(cm.exception.code, "TTS_PROVIDER_NOT_ALLOWED")

    def test_bad_timing_config_rejected(self):
        for over in ({"sample_rate": 22050}, {"min_total_seconds": 50}, {"max_total_seconds": 90}):
            with self.assertRaises(ValidationError, msg=over):
                load_config(overrides={"tts": over})

    def test_default_is_silent_for_both_languages(self):
        voices = load_config()["tts"]["voices"]
        self.assertEqual({v["provider"] for v in voices.values()}, {"silent"})


class TestFakeTone(unittest.TestCase):
    # Pinned bytes: integer-only synthesis must be identical on Linux CI and the owner's Windows PC.
    GOLDEN = {
        ("It closed at ¥2,345, +6.40% on the day.", "en-US"):
            (2540, "3a7b031f1d5a136a5cd901a61ff719264ce9cc3853a5bdeb8cf92e4d367e32d5",
             "7d47cd9aa47bcbbd83d8a850ddad19a987ca202701c7547e72a926a7b831593a"),
        ("終値は2,345円、前日比+6.40%。", "ja-JP"):
            (1890, "37d7440116f415383edcc19ca79200e3168651a9f83db540d04ffa11934be800",
             "e12f392534198545bf2655aadefa131a3995cc3b1c9cbc295de8289933561d86"),
    }

    def test_golden_bytes(self):
        p = FakeToneProvider(24000)
        for (text, lang), (ms, pcm_sha, wav_sha) in self.GOLDEN.items():
            c = p.synthesize(text, lang, None)
            self.assertEqual((c.duration_ms, c.sha256), (ms, pcm_sha), lang)
            self.assertEqual(hashlib.sha256(wav_bytes(c.pcm, 24000)).hexdigest(), wav_sha, lang)

    def test_deterministic_and_text_sensitive(self):
        p = FakeToneProvider(24000)
        a = p.synthesize("Hello market", "en-US", None)
        self.assertEqual(a, p.synthesize("Hello market", "en-US", None))
        self.assertNotEqual(a.sha256, p.synthesize("Hello market!", "en-US", None).sha256)
        self.assertNotEqual(a.sha256, p.synthesize("Hello market", "en-US", "voice2").sha256)

    def test_length_follows_display_width(self):
        p = FakeToneProvider(24000)
        self.assertEqual(p.duration_ms("abcd"), 300)                 # floor
        self.assertEqual(p.duration_ms("a" * 20), 1300)
        self.assertEqual(p.duration_ms("あ" * 10), 1300)            # full-width = 2 cells

    def test_wav_is_canonical_mono_16bit(self):
        c = FakeToneProvider(24000).synthesize("abc def", "en-US", None)
        with wave.open(io.BytesIO(wav_bytes(c.pcm, 24000))) as w:
            self.assertEqual((w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()),
                             (1, 2, 24000, c.samples))


class TestNarrationTimeline(unittest.TestCase):
    def test_silent_keeps_r1_fixed_layout(self):
        n = tts.narrate(_post(), _tts_cfg(), 6)
        self.assertIsNone(n.wav)
        self.assertEqual([(s["start"], s["end"]) for s in n.timeline], [(0, 6), (6, 12), (12, 18), (18, 24), (24, 30)])
        self.assertTrue(all(isinstance(s["end"], int) for s in n.timeline))   # byte-identical R1 JSON
        self.assertEqual(n.manifest["timing"], "fixed_segment_seconds")

    def test_audio_driven_durations(self):
        post = _post()
        n = tts.narrate(post, _fake_cfg(), 6)
        p = FakeToneProvider(24000)
        prev = 0
        for seg, tl, m in zip(post["segments"], n.timeline, n.manifest["segments"]):
            clip = p.duration_ms(seg["text"])
            want = max(4000, clip + 400)
            self.assertEqual(round(tl["start"] * 1000), prev)
            self.assertEqual(round((tl["end"] - tl["start"]) * 1000), want, seg["id"])
            self.assertEqual(m["audio_ms"], clip)
            prev += want
        self.assertEqual(n.manifest["total_seconds"], prev / 1000)
        self.assertTrue(20 <= prev / 1000 <= 45)

    def test_track_places_each_clip_at_its_segment_start(self):
        post = _post()
        n = tts.narrate(post, _fake_cfg(), 6)
        with wave.open(io.BytesIO(n.wav)) as w:
            pcm = w.readframes(w.getnframes())
        self.assertEqual(len(pcm) // 2, round(n.timeline[-1]["end"] * 24000))
        p = FakeToneProvider(24000)
        for seg, tl in zip(post["segments"], n.timeline):
            clip = p.synthesize(seg["text"], "en-US", None).pcm
            off = round(tl["start"] * 24000) * 2
            self.assertEqual(pcm[off:off + len(clip)], clip, seg["id"])
            end = round(tl["end"] * 24000) * 2
            self.assertEqual(set(pcm[off + len(clip):end]), {0}, seg["id"])   # padding is silence

    def test_same_input_same_bytes(self):
        a, b = tts.narrate(_post("ja-JP"), _fake_cfg(), 6), tts.narrate(_post("ja-JP"), _fake_cfg(), 6)
        self.assertEqual(a.wav, b.wav)
        self.assertEqual(a.manifest, b.manifest)

    def test_too_long_fails_closed_and_is_not_shortened(self):
        post = _post()
        post["segments"][1]["text"] = "The close was ordinary. " * 30
        with self.assertRaises(NarrationLengthError) as cm:
            tts.narrate(post, _fake_cfg(), 6)
        self.assertEqual(cm.exception.code, "NARRATION_TOO_LONG")
        self.assertIsInstance(cm.exception, ValidationError)          # non-retryable class
        self.assertGreater(cm.exception.details["total_seconds"], 45)

    def test_limit_boundaries(self):
        total = tts.narrate(_post(), _fake_cfg(), 6).manifest["total_seconds"]
        tts.narrate(_post(), _fake_cfg(max_total_seconds=total), 6)             # == max: allowed
        with self.assertRaises(NarrationLengthError):
            tts.narrate(_post(), _fake_cfg(max_total_seconds=total - 0.01), 6)
        with self.assertRaises(NarrationLengthError) as cm:
            tts.narrate(_post(), _fake_cfg(min_total_seconds=total + 0.01), 6)
        self.assertEqual(cm.exception.code, "NARRATION_TOO_SHORT")
        with self.assertRaises(NarrationLengthError):                           # silent layout is gated too
            tts.narrate(_post(), _tts_cfg(), 10)                                # 5 x 10 s = 50 s

    def test_test_only_provider_refuses_real_data(self):
        post = _post()
        post["fixture"] = False
        with self.assertRaises(ValidationError) as cm:
            tts.narrate(post, _fake_cfg(), 6)
        self.assertEqual(cm.exception.code, "TTS_TEST_PROVIDER_ON_REAL_DATA")

    def test_empty_audio_from_provider_fails_closed(self):
        class Mute:
            name, narrates, test_only = "mute", True, False

            def synthesize(self, text, lang, voice):
                return AudioClip(b"", 24000, "mute", voice, "0")
        with mock.patch.object(tts, "get_provider", lambda *_a: Mute()):
            with self.assertRaises(TtsError) as cm:
                tts.narrate(_post(), _fake_cfg(), 6)
        self.assertEqual(cm.exception.code, "TTS_EMPTY_AUDIO")

    def test_verify_detects_text_not_matching_narration(self):
        import tempfile
        from pathlib import Path
        post = _post()
        n = tts.narrate(post, _fake_cfg(), 6)
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / n.file).write_bytes(n.wav)
            write_json_atomic(d / tts.TTS_MANIFEST, tts.build_manifest("s", [n]))
            tts.verify(d, [post])
            edited = copy.deepcopy(post)
            edited["segments"][1]["text"] += " Huge upside."
            with self.assertRaises(EvidenceError) as cm:
                tts.verify(d, [edited])
            self.assertEqual(cm.exception.code, "TTS_TEXT_MISMATCH")
            (d / n.file).write_bytes(n.wav[:-2] + b"\x01\x00")
            with self.assertRaises(EvidenceError) as cm:
                tts.verify(d, [post])
            self.assertEqual(cm.exception.code, "NARRATION_MISMATCH")


class TestNarrationInApproval(PipelineCase):
    overrides = FAKE

    def build(self):
        self.ingest_validate()
        results = build_drafts(self.ctx, SESSION, FakeRenderer())
        self.assertEqual({r["state"] for r in results}, {"AWAITING_APPROVAL"}, results)
        sid = results[0]["story_id"]
        return sid, story_dir(self.ctx, {"story_id": sid, "session_date": SESSION})

    def content(self, sid):
        return self.ctx.conn.execute("SELECT content_sha256 FROM stories WHERE story_id=?", (sid,)).fetchone()[0]

    def test_narration_and_manifest_are_in_the_content_hash(self):
        sid, sdir = self.build()
        rows = {r["name"]: r["sha256"] for r in self.ctx.conn.execute(
            "SELECT name, sha256 FROM artifacts WHERE story_id=?", (sid,))}
        for name in (*ARTIFACT_FILES, "narration_en-US.wav", "narration_ja-JP.wav"):
            self.assertEqual(rows[name], sha256_file(sdir / name), name)
        self.assertEqual(sha256_json(rows), self.content(sid))
        m = json.loads((sdir / "tts_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(m["langs"]["ja-JP"]["narration_sha256"], rows["narration_ja-JP.wav"])
        rm = json.loads((sdir / "render_manifest.json").read_text(encoding="utf-8"))
        self.assertIn("narration_en-US.wav", rm["artifact_set"])
        detail = json.loads(self.ctx.conn.execute(
            "SELECT detail_json FROM audit_log WHERE to_state='RENDERED' AND entity_id=?", (sid,)).fetchone()[0])
        self.assertEqual(detail["tts"]["en-US"]["provider"], "fake_tone")
        self.assertEqual(detail["tts"]["en-US"]["timing"], "audio_driven")

    def test_srt_boundaries_equal_narration_boundaries(self):
        sid, sdir = self.build()
        m = json.loads((sdir / "tts_manifest.json").read_text(encoding="utf-8"))
        for lang in ("en-US", "ja-JP"):
            srt = (sdir / f"captions_{lang}.srt").read_text(encoding="utf-8")
            for seg in m["langs"][lang]["segments"]:
                s, e = (int(round(x * 1000)) for x in (seg["start"], seg["end"]))
                stamp = "{:02d}:{:02d}:{:02d},{:03d}"
                fmt = lambda ms: stamp.format(ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)
                self.assertIn(f"{fmt(s)} --> {fmt(e)}", srt, (lang, seg["id"]))
        self.assertEqual((sdir / "captions.srt").read_bytes(), (sdir / "captions_en-US.srt").read_bytes())

    def test_audio_changed_before_approval_fails_closed(self):
        sid, sdir = self.build()
        wav = sdir / "narration_en-US.wav"
        data = bytearray(wav.read_bytes())
        data[-1] ^= 0x01
        wav.write_bytes(bytes(data))
        with self.assertRaises(EvidenceError) as cm:
            approve(self.ctx, sid, "yusuke")
        self.assertEqual(cm.exception.code, "ARTIFACT_TAMPERED")
        self.assertEqual(cm.exception.details["name"], "narration_en-US.wav")
        self.assertEqual(self.story_state(sid), "FAILED")

    def test_audio_changed_after_approval_invalidates_it(self):
        sid, sdir = self.build()
        approve(self.ctx, sid, "yusuke")
        (sdir / "narration_ja-JP.wav").write_bytes(wav_bytes(b"\x00\x00" * 24000, 24000))
        with self.assertRaises(EvidenceError) as cm:
            schedule(self.ctx, sid)
        self.assertEqual(cm.exception.code, "ARTIFACT_TAMPERED")
        self.assertEqual(self.story_state(sid), "FAILED")
        self.assertEqual(self.ctx.conn.execute("SELECT COUNT(*) FROM schedules").fetchone()[0], 0)

    def test_tts_manifest_edit_invalidates_approval(self):
        sid, sdir = self.build()
        approve(self.ctx, sid, "yusuke")
        p = sdir / "tts_manifest.json"
        m = json.loads(p.read_text(encoding="utf-8"))
        m["langs"]["en-US"]["voice"] = "someone-else"
        write_json_atomic(p, m)
        with self.assertRaises(EvidenceError) as cm:
            schedule(self.ctx, sid)
        self.assertEqual(cm.exception.code, "ARTIFACT_TAMPERED")

    def test_dropping_the_narration_record_is_detected(self):
        sid, _ = self.build()
        self.ctx.conn.execute("DELETE FROM artifacts WHERE story_id=? AND name='narration_en-US.wav'", (sid,))
        with self.assertRaises(EvidenceError) as cm:
            approve(self.ctx, sid, "yusuke")
        self.assertEqual(cm.exception.code, "ARTIFACT_MISSING")
        self.assertEqual(cm.exception.details["missing"], ["narration_en-US.wav"])

    def test_different_voice_gives_different_content_hash(self):
        sid, _ = self.build()
        first = self.content(sid)
        from auto_publish.tests.helpers import make_ctx, copy_fixture
        from auto_publish.app.ingest.ingest import ingest, validate
        for voice, same in ((None, True), ("alt", False)):
            root = self.root / f"other_{voice}"
            over = copy.deepcopy(FAKE)
            over["tts"]["voices"]["en-US"]["voice"] = voice
            ctx = make_ctx(root, overrides=over)
            try:
                ingest(ctx, copy_fixture(root))
                validate(ctx, SESSION)
                build_drafts(ctx, SESSION, FakeRenderer())
                other = ctx.conn.execute("SELECT content_sha256 FROM stories WHERE story_id=?", (sid,)).fetchone()[0]
            finally:
                ctx.conn.close()
            self.assertEqual(other == first, same, voice)

    def test_happy_path_schedules(self):
        sid, _ = self.build()
        approve(self.ctx, sid, "yusuke")
        self.assertEqual(schedule(self.ctx, sid)["state"], "SCHEDULED")


class TestNarrationTooLongInPipeline(PipelineCase):
    overrides = {"tts": {**FAKE["tts"], "max_total_seconds": 21}}

    def test_story_fails_closed_and_cannot_be_retried(self):
        self.ingest_validate()
        results = build_drafts(self.ctx, SESSION, FakeRenderer())
        for r in results:
            self.assertEqual(r["state"], "FAILED")
            self.assertEqual(r["error"]["code"], "NARRATION_TOO_LONG")
            with self.assertRaises(ValidationError) as cm:
                retry(self.ctx, r["story_id"], "again", FakeRenderer())
            self.assertEqual(cm.exception.code, "NOT_RETRYABLE")
        self.assertEqual(self.ctx.conn.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0], 0)


class TestLegacyR1Story(PipelineCase):
    """A story rendered before TTS (no tts_manifest / artifact_set) must still verify."""

    def test_legacy_artifact_set_still_approves(self):
        self.ingest_validate()
        (r, *_rest) = build_drafts(self.ctx, SESSION, FakeRenderer())
        sid = r["story_id"]
        sdir = story_dir(self.ctx, {"story_id": sid, "session_date": SESSION})
        rm = json.loads((sdir / "render_manifest.json").read_text(encoding="utf-8"))
        rm.pop("artifact_set")
        write_json_atomic(sdir / "render_manifest.json", rm)
        c = self.ctx.conn
        c.execute("DELETE FROM artifacts WHERE story_id=? AND name NOT IN (%s)" % ",".join("?" * len(LEGACY_ARTIFACT_FILES)),
                  (sid, *LEGACY_ARTIFACT_FILES))
        c.execute("UPDATE artifacts SET sha256=? WHERE story_id=? AND name='render_manifest.json'",
                  (sha256_file(sdir / "render_manifest.json"), sid))
        for extra in ("tts_manifest.json",):
            (sdir / extra).unlink()
        hashes = {row["name"]: row["sha256"] for row in c.execute("SELECT name, sha256 FROM artifacts WHERE story_id=?", (sid,))}
        c.execute("UPDATE stories SET content_sha256=? WHERE story_id=?", (sha256_json(hashes), sid))
        self.assertEqual(approve(self.ctx, sid, "yusuke")["state"], "APPROVED")
        self.assertEqual(schedule(self.ctx, sid)["state"], "SCHEDULED")


if __name__ == "__main__":
    unittest.main()
