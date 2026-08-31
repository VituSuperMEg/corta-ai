from corta_ai.pipeline import create_ass


def test_karaoke_timing_preserves_pause_before_next_word(tmp_path):
    subtitle = tmp_path / "clip.ass"
    create_ass(
        [
            {"start": 0.0, "end": 0.4, "text": "primeira"},
            {"start": 1.0, "end": 1.4, "text": "segunda"},
        ],
        clip_start=0,
        clip_end=2,
        destination=subtitle,
    )

    content = subtitle.read_text(encoding="utf-8")
    assert r"{\kf100}PRIMEIRA" in content
    assert r"{\kf40}SEGUNDA" in content
