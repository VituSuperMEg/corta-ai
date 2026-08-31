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

