import pytest

from corta_ai.timeline import (FREEZE_LENGTH, build_timeline, map_times, pick_climax,
                               retime_ass, src_to_out)


def test_build_timeline_ramp_and_freeze_shorten_clip():
    timeline = build_timeline(15.0, climax=8.0, ramp=True, freeze=True)
    # clip 8s + freeze 0.4s + clip 0.6s + ramp 2.5s/1.5 + clip 3.9s = 14.566...
    assert timeline["duration"] == pytest.approx(8 + 0.4 + 0.6 + 2.5 / 1.5 + 3.9, abs=0.01)
    assert timeline["duration"] < 15.0
    kinds = [beat["kind"] for beat in timeline["beats"]]
    assert kinds == ["clip", "freeze", "clip", "clip", "clip"]
    speeds = [beat["speed"] for beat in timeline["beats"] if beat["kind"] == "clip"]
    assert speeds == [1.0, 1.0, 1.5, 1.0]


def test_build_timeline_disabled_returns_none():
    assert build_timeline(15.0, climax=5.0) is None


def test_short_clips_skip_ramp_but_can_freeze():
    timeline = build_timeline(5.0, climax=4.6, ramp=True, freeze=True)
    kinds = [beat["kind"] for beat in timeline["beats"]]
    assert "freeze" in kinds
    assert all(beat["speed"] == 1.0 for beat in timeline["beats"] if beat["kind"] == "clip")


def test_src_to_out_maps_across_freeze_and_ramp():
    timeline = build_timeline(15.0, climax=8.0, ramp=True, freeze=True)
    assert src_to_out(timeline, 0.0) == 0.0
    assert src_to_out(timeline, 7.0) == 7.0  # antes do freeze, sem mudança
    freeze_at = next(beat for beat in timeline["beats"] if beat["kind"] == "freeze")
    assert src_to_out(timeline, freeze_at["at"]) == pytest.approx(freeze_at["out"])
    assert src_to_out(timeline, freeze_at["at"] + 0.001) == pytest.approx(
        freeze_at["out"] + FREEZE_LENGTH + 0.001)
    # dentro da rampa o tempo corre 1.5x
    ramp = next(beat for beat in timeline["beats"] if beat.get("speed", 1.0) > 1.0)
    inside = ramp["a"] + 0.3
    assert src_to_out(timeline, inside) == pytest.approx(ramp["out"] + 0.3 / 1.5)
    assert src_to_out(timeline, 15.0) == pytest.approx(timeline["duration"])


def test_map_times_passthrough_without_timeline():
    assert map_times(None, [1.0, 2.0]) == [1.0, 2.0]


def test_retime_ass_shifts_dialogue_times(tmp_path):
    timeline = build_timeline(15.0, climax=8.0, ramp=True, freeze=True)
    path = tmp_path / "clip.ass"
    path.write_text(
        "[Events]\n"
        "Format: Layer, Start, End, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:09.00,0:00:10.00,Estilo,,0,0,,Depois do freeze\n"
        "Dialogue: 0,0:00:01.00,0:00:02.00,Estilo,,0,0,,Antes do freeze\n",
        encoding="utf-8")
    retime_ass(path, timeline)
    lines = path.read_text(encoding="utf-8").splitlines()
    late, early = lines[2].split(","), lines[3].split(",")

    def stamp(value: str) -> float:
        hours, minutes, rest = value.split(":")
        seconds, centis = rest.split(".")
        return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(centis) / 100

    # 9s→10s cai na rampa: no arquivo dura só 2/3 do tempo original
    assert stamp(late[2]) - stamp(late[1]) == pytest.approx(1.0 / 1.5, abs=0.02)
    assert early[1] == "0:00:01.00" and early[2] == "0:00:02.00"  # antes do freeze, intocado
    assert "Depois do freeze" in lines[2]


def test_pick_climax_prefers_last_emphasis_in_safe_zone():
    assert pick_climax(20.0, emphasis=[1.0, 5.0, 16.0]) == 16.0
    assert pick_climax(10.0, emphasis=[0.5]) == pytest.approx(5.5)  # fallback no meio
    assert pick_climax(10.0, energy=[0, 0, 0, 9, 0, 0]) == 3.0
