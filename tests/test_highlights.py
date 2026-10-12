from corta_ai.highlights import TranscriptSegment, choose_highlights


def test_pipeline_selects_exact_requested_number_of_non_overlapping_clips():
    segments = [
        TranscriptSegment(start=i * 10, end=(i + 1) * 10, text=f"Trecho interessante número {i} com uma ideia completa." )
        for i in range(24)
    ]

    highlights = choose_highlights(segments, clip_count=3, clip_duration=40, video_duration=240)

    assert len(highlights) == 3
    assert all(item.duration == 40 for item in highlights)
    assert all(
        first.end <= second.start or second.end <= first.start
        for index, first in enumerate(highlights)
        for second in highlights[index + 1 :]
    )


def test_pipeline_fails_clearly_when_exact_quantity_does_not_fit():
    segments = [TranscriptSegment(start=0, end=50, text="Conteúdo curto.")]

    try:
        choose_highlights(segments, clip_count=3, clip_duration=30, video_duration=50)
    except ValueError as error:
        assert "não comporta 3 cortes" in str(error)
    else:
        raise AssertionError("expected a clear capacity error")



def test_hook_start_prefers_sentence_openings_with_hooks():
    segments = [
        TranscriptSegment(0, 10, "e aí a gente foi lá e comprou tudo"),
        TranscriptSegment(10, 20, "depois voltamos pra casa"),
        TranscriptSegment(23, 33, "Você sabia que 90% das pessoas erram isso?"),
        TranscriptSegment(33, 43, "vou explicar agora"),
    ]
    plain = choose_highlights(segments, 1, 20, 60)[0]
    hooked = choose_highlights(segments, 1, 20, 60, hook_start=True)[0]
    assert hooked.start == 23
    assert hooked.start != plain.start or hooked.score > plain.score


def test_end_cta_overlay_lands_in_last_seconds(tmp_path):
    from corta_ai.effects import append_overlays
    path = tmp_path / "s.ass"
    path.write_text("", encoding="utf-8")
    append_overlays(path, 30, end_cta=True)
    text = path.read_text(encoding="utf-8")
    assert "SEGUE PRA VER MAIS" in text and "0:00:26.00,0:00:30.00" in text
    append_overlays(path, 5, end_cta=True)
    assert path.read_text(encoding="utf-8").count("SEGUE") == 1
