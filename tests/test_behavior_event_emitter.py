from scripts.behavior_event_emitter import build_event
def test_exit_flip_resets_frame_without_direction_command():
    x=build_event("TSE:285A","post_exit_flip","FLAT",100,["above_vwap"],ts="2026-09-24T00:10:00+00:00")
    assert x["coach_mode"]=="reassess"
    assert "ゼロから" in x["coach_message"]
    assert "買え" not in x["coach_message"] and "売れ" not in x["coach_message"]
