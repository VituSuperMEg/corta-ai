from corta_ai.pipeline import create_ass


def test_stylish_captions_alternate_and_stay_inside_clip(tmp_path):
    subtitle = tmp_path / "stylish.ass"
    words = [{"start": 9.8 + i * .5, "end": 10.2 + i * .5, "text": f"fala{i}"}
             for i in range(9)]
    create_ass(words, 10, 14, subtitle, stylish_captions=True, varied_fonts=True)
    content = subtitle.read_text()
    events = [line for line in content.splitlines() if line.startswith("Dialogue:")]
    assert len(events) == 9
    assert events[0].startswith("Dialogue: 0,0:00:00.00,0:00:00.20,")
    assert events[-1].startswith("Dialogue: 0,0:00:03.80,0:00:04.00,")
    assert r"\fscx94" in content
    assert r"\blur1" in content
    assert r"\fscx115" in content
    assert r"\kf" not in content
    assert all(r"\fnPoppins ExtraBold" in event for event in events[:3])
    assert all(r"\fnBarlow Condensed ExtraBold" in event for event in events[3:6])
    assert all(r"\fnBebas Neue" in event for event in events[6:])


def test_stylish_captions_respect_silence_and_escape_text(tmp_path):
    subtitle = tmp_path / "stylish.ass"
    create_ass([
        {"start": 0, "end": .4, "text": r"oi{\pos(0,0)}"},
        {"start": 2, "end": 2.5, "text": "voltou"},
        {"start": 3, "end": 3, "text": "inválida"},
    ], 0, 4, subtitle, stylish_captions=True)
    events = [line for line in subtitle.read_text().splitlines() if line.startswith("Dialogue:")]
    assert len(events) == 2
    assert ",0:00:00.00,0:00:00.40," in events[0]
    assert ",0:00:02.00,0:00:02.50," in events[1]
    assert r"\POS(0,0)" not in events[0]
    assert "VOLTOU" not in events[0]


def test_stylish_captions_accept_empty_transcript(tmp_path):
    subtitle = tmp_path / "empty.ass"
    create_ass([], 0, 1, subtitle, stylish_captions=True)
    assert "Dialogue:" not in subtitle.read_text()


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


def test_karaoke_timing_excludes_word_audio_before_clip_start(tmp_path):
    subtitle = tmp_path / "clip.ass"
    create_ass(
        [
            {"start": 9.5, "end": 10.2, "text": "começou"},
            {"start": 10.3, "end": 10.7, "text": "agora"},
        ],
        clip_start=10,
        clip_end=12,
        destination=subtitle,
    )

    content = subtitle.read_text(encoding="utf-8")
    assert r"{\kf30}COMEÇOU" in content


def test_font_and_effect_options_are_independent(tmp_path):
    words = [{"start": i * .5, "end": i * .5 + .4, "text": "ação"} for i in range(15)]
    for effects in (False, True):
        for fonts in (False, True):
            path = tmp_path / f"{effects}-{fonts}.ass"
            create_ass(words, 0, 8, path, stylish_captions=effects, varied_fonts=fonts)
            content = path.read_text()
            assert (r"\fscx" in content) == effects
            for family in ("Poppins ExtraBold", "Barlow Condensed ExtraBold", "Bebas Neue"):
                assert (family in content) == fonts


def test_keyword_highlight_is_independent_from_caption_styles(tmp_path):
    words = [{"start": i * .5, "end": i * .5 + .4, "text": text}
             for i, text in enumerate(["isso", "é", "dinheiro", "fácil", "demais"])]
    for stylish in (False, True):
        for highlight in (False, True):
            path = tmp_path / f"{stylish}-{highlight}.ass"
            create_ass(words, 0, 3, path, stylish_captions=stylish, keyword_highlight=highlight)
            content = path.read_text()
            assert ("&H0000FFFF&" in content) is highlight
            assert (r"\bord9" in content) is highlight


def test_keyword_highlight_skips_groups_without_long_words(tmp_path):
    subtitle = tmp_path / "short.ass"
    create_ass([{"start": 0, "end": .4, "text": "oi"}, {"start": .5, "end": .9, "text": "la"}],
               0, 2, subtitle, keyword_highlight=True)
    assert "&H0000FFFF&" not in subtitle.read_text()


def test_keyword_restore_returns_to_base_style(tmp_path):
    subtitle = tmp_path / "restore.ass"
    create_ass([{"start": 0, "end": 1, "text": "dinheiro"},
                {"start": 1, "end": 2, "text": "fácil"},
                {"start": 2, "end": 3, "text": "total"}],
               0, 4, subtitle, keyword_highlight=True)
    content = subtitle.read_text()
    assert r"\1c&H0000FFFF&\bord9" in content
    assert r"\1c&H00FFFFFF&\bord7" in content  # palavras seguintes voltam ao estilo base
