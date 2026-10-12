from array import array
from itertools import product
import wave

from corta_ai.effects import append_overlays, create_accent_audio, emphasis_times, opening_text
from corta_ai.pipeline import create_ass, render_clip


def test_emphasis_uses_clip_relative_times_and_spaces_accents():
    words = [dict(start=i, end=i+.3, text="uau!") for i in range(30)]
    times = emphasis_times(words, 10, 25)
    assert times == [1, 5]
    assert all(0 <= t < 15 for t in times)
    assert emphasis_times([dict(start=0, end=.4, text="teste")], 0, 10) == [6.0]  # fallback espaçado


def test_opening_title_is_bounded_and_uses_only_clip_words():
    words = [dict(start=0, end=1, text="fora"), dict(start=10, end=11, text="ação")]
    assert opening_text(words, 10, 15) == "ação"
    assert len(opening_text(words, 10, 15, "x"*100)) == 60


def test_visual_options_do_not_enable_each_other(tmp_path):
    for progress, title in product((False, True), repeat=2):
        path = tmp_path / f"{progress}-{title}.ass"
        create_ass([], 0, 10, path)
        append_overlays(path, 10, progress_bar=progress, title=r"ação {\pos(0,0)}" if title else "")
        content = path.read_text()
        assert ("Dialogue: 2," in content) == progress
        assert (r"\fscx100" in content) == progress
        assert ("Dialogue: 4,0:00:00.00,0:00:03.00" in content) == title
        assert r"\POS(0,0)" not in content


def test_audio_accents_are_quiet_and_silent_outside_cues(tmp_path):
    path = tmp_path / "accents.wav"
    create_accent_audio(path, 2, [1])
    with wave.open(str(path)) as audio:
        assert audio.getnframes() == 48000
        samples = array('h', audio.readframes(audio.getnframes()))
    assert not any(samples[:24000])
    assert 8000 < max(abs(x) for x in samples) < 16000  # audível, sem clipar
    assert not any(samples[30000:])


def test_render_filters_respect_zoom_and_sound_flags(tmp_path, monkeypatch):
    from corta_ai import pipeline
    commands = []
    monkeypatch.setattr(pipeline, '_run', lambda command, message: commands.append(command))
    for zoom, sound in product((False, True), repeat=2):
        render_clip(tmp_path/'source.mp4', tmp_path/'clip.ass', 10, 5, tmp_path/'out.mp4',
                    smooth_zoom=zoom, sound_effects=sound, emphasis=[1])
        command = ' '.join(commands[-1])
        assert ('zoompan=' in command) == zoom
        assert ('amix=' in command) == sound
        assert ('accents.wav' in command) == sound


def test_base_render_keeps_the_old_command_without_new_effects(tmp_path, monkeypatch):
    from corta_ai import pipeline
    commands = []
    monkeypatch.setattr(pipeline, '_run', lambda command, message: commands.append(command))
    render_clip(tmp_path / 'source.mp4', tmp_path / 'clip.ass', 0, 5, tmp_path / 'out.mp4')
    command = ' '.join(commands[-1])
    assert 'scale=1144:2036' not in command
    assert 'eq=brightness' not in command
    assert 'vignette' not in command and 'noise=' not in command
    assert 'sfx.wav' not in command
    assert 'zoompan=' not in command


def test_attention_flags_reach_the_ffmpeg_command(tmp_path, monkeypatch):
    from corta_ai import pipeline
    commands = []
    monkeypatch.setattr(pipeline, '_run', lambda command, message: commands.append(command))
    render_clip(tmp_path / 'source.mp4', tmp_path / 'clip.ass', 0, 5, tmp_path / 'out.mp4',
                shake=[2.0], flash=[1.0], hook_fx=True, vignette=True,
                sfx_events=[(0.0, "impact")])
    command = ' '.join(commands[-1])
    assert 'scale=1144:2036' in command and 'crop=w=1080:h=1920:x=' in command
    assert "eq=brightness=0.45:enable='between(t,0.550,0.630)+between(t,0.950,1.030)+between(t,1.000,1.090)'" in command
    assert 'vignette=angle=PI/5,noise=alls=5:allf=t' in command
    assert 'sfx.wav' in command and 'amix=inputs=2' in command
    assert 'zoompan=' in command  # hook_fx sozinho já pede o zoompan
    assert (tmp_path / 'clip.sfx.wav').is_file()


def test_external_music_track_replaces_the_synthesized_pad(tmp_path, monkeypatch):
    from corta_ai import pipeline
    commands = []
    monkeypatch.setattr(pipeline, '_run', lambda command, message: commands.append(command))
    track = tmp_path / "faixa-ncs.mp3"
    track.write_bytes(b"id3")
    render_clip(tmp_path / 'source.mp4', tmp_path / 'clip.ass', 0, 5, tmp_path / 'out.mp4',
                music=True, music_file=str(track), music_volume=0.5)
    command = ' '.join(commands[-1])
    assert str(track) in command
    assert 'volume=0.50[music_in]' in command
    assert not (tmp_path / 'clip.music.wav').exists()  # nada de pad sintetizado
    render_clip(tmp_path / 'source.mp4', tmp_path / 'clip.ass', 0, 5, tmp_path / 'out.mp4',
                music=True, music_volume=0.35)
    assert (tmp_path / 'clip.music.wav').is_file()  # desmarcado/faixa vazia: comportamento base


def test_sfx_track_places_events_on_time_and_stays_silent_between(tmp_path):
    from corta_ai.effects import create_sfx_audio
    path = tmp_path / "sfx.wav"
    create_sfx_audio(path, 4, [(1.0, "impact"), (3.2, "riser")])
    with wave.open(str(path)) as audio:
        assert audio.getnframes() == 96000
        samples = array('h', audio.readframes(audio.getnframes()))
    assert not any(samples[: 24000 * 9 // 10])  # silêncio antes do primeiro evento
    assert max(abs(x) for x in samples[24000:40000]) > 1000  # impacto por volta de 1 s
    assert not any(samples[24000 * 2 : 24000 * 3])  # intervalo sem eventos
    assert max(abs(x) for x in samples[24000 * 33 // 10:]) > 500  # riser no fim
