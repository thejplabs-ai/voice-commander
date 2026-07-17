"""
Tests for voice/transcription.py::strip_hallucinated_tail and the temperature
ladder / hallucination_silence_threshold changes (Bug C, bug bounty 2, Task 3).

Bug C (production audit 2026-07): faster-whisper large-v3, at the high end of
the temperature fallback ladder ([0.0 .. 1.0]), completes real speech with
memorized YouTube captions ALWAYS glued at the end, after a complete real
sentence — "Inscreva-se no canal e ative o sininho", "Acesse o nosso site
www.supa.com.br", "Subtitles by the Amara.org community", "Legendas pela
comunidade Amara.org". 9 unambiguous production cases. The old blocklist was
removed in W1 (see transcription.py module docstring history).

Fix: cap temperature ladder to [0.0, 0.2, 0.4] (cuts the hallucination-prone
high-temperature retries at the source), enable
hallucination_silence_threshold=2.0 (+ word_timestamps=True, required by
faster-whisper for that param) as a model-level defense, and
strip_hallucinated_tail() as a deterministic last-resort defense applied at
the single raw_text assembly point (_join_segments — covers both the normal
STT path and the Task 2 no-VAD fallback path, both of which call it).
"""
from unittest.mock import MagicMock

from voice import transcription as tr


# ---------------------------------------------------------------------------
# strip_hallucinated_tail — pure function tests
# ---------------------------------------------------------------------------


def test_strips_inscreva_se_pattern():
    raw = "Preciso terminar o relatório até sexta. Inscreva-se no canal e ative o sininho"
    assert tr.strip_hallucinated_tail(raw) == "Preciso terminar o relatório até sexta."


def test_strips_acesse_o_site_pattern():
    raw = "A reunião ficou marcada para amanhã às dez. Acesse o nosso site www.supa.com.br"
    assert tr.strip_hallucinated_tail(raw) == "A reunião ficou marcada para amanhã às dez."


def test_strips_amara_org_subtitles_pattern():
    raw = "Combinei de entregar o projeto na sexta-feira. Subtitles by the Amara.org community"
    assert tr.strip_hallucinated_tail(raw) == "Combinei de entregar o projeto na sexta-feira."


def test_strips_legendas_pela_comunidade_pattern():
    raw = "Vamos revisar o contrato antes de assinar. Legendas pela comunidade Amara.org"
    assert tr.strip_hallucinated_tail(raw) == "Vamos revisar o contrato antes de assinar."


def test_inscreva_se_in_the_middle_preserved():
    """Only the TAIL is examined (last 160 chars). A mid-text mention followed
    by enough real content to push it out of the tail window must survive
    untouched — the user is reporting what someone said, not being
    hallucinated at."""
    mid = "Alguem me disse ontem: inscreva-se no canal, mas eu ri e nao segui o conselho."
    padding = (
        " Depois disso conversamos sobre outras coisas completamente diferentes, "
        "tipo o jogo de ontem a noite e o que vamos fazer no fim de semana que vem, "
        "sem pressa nenhuma, so relaxando mesmo."
    )
    raw = mid + padding
    assert len(raw) - len(mid) > 100  # padding pushes "inscreva-se" out of the 160-char window
    assert tr.strip_hallucinated_tail(raw) == raw


def test_url_dictated_in_the_middle_preserved():
    """User dictating a URL mid-sentence, with more real speech after it —
    the www.*.com pattern only matches when the URL is the LAST token."""
    raw = "Para o cadastro acesse www.foo.com e depois preencha o formulário que te mandei ontem."
    assert tr.strip_hallucinated_tail(raw) == raw


def test_clean_text_unchanged():
    raw = "Oi, tudo bem? Preciso remarcar a reunião de amanhã para as quinze horas."
    assert tr.strip_hallucinated_tail(raw) == raw


def test_composite_tail_both_removed():
    raw = "Ja mencionei que vou ao mercado e depois preciso estudar. Inscreva-se no canal! Ative o sininho!"
    assert tr.strip_hallucinated_tail(raw) == "Ja mencionei que vou ao mercado e depois preciso estudar."


def test_strip_that_would_empty_text_returns_original():
    """Fail-safe: if the whole text is the hallucinated tail, keep the original."""
    raw = "Inscreva-se no canal e ative o sininho"
    assert tr.strip_hallucinated_tail(raw) == raw


def test_empty_string_unchanged():
    assert tr.strip_hallucinated_tail("") == ""


def test_warn_logged_when_tail_stripped(capsys):
    tr.strip_hallucinated_tail("Falei tudo que precisava. Inscreva-se no canal!")
    out = capsys.readouterr().out
    assert "[WARN]" in out
    assert "cauda alucinada removida" in out


# ---------------------------------------------------------------------------
# _join_segments — single assembly point applies the strip
# ---------------------------------------------------------------------------


def test_join_segments_applies_strip():
    seg1 = MagicMock(text="Falei tudo que precisava.")
    seg2 = MagicMock(text=" Inscreva-se no canal e ative o sininho")
    assert tr._join_segments([seg1, seg2]) == "Falei tudo que precisava."


# ---------------------------------------------------------------------------
# _build_transcribe_kwargs — temperature ladder cap + hallucination defenses
# ---------------------------------------------------------------------------


def test_build_transcribe_kwargs_caps_temperature_and_enables_hallucination_guard(monkeypatch):
    from voice import state
    monkeypatch.setattr(state, "_CONFIG", {
        "WHISPER_LANGUAGE": "",
        "VAD_THRESHOLD": 0.5,
        "WHISPER_BEAM_SIZE": 1,
    })

    model = MagicMock()
    model.transcribe = lambda path, language=None, task=None, initial_prompt=None, **k: None

    kwargs, _vad_params = tr._build_transcribe_kwargs(model, "transcribe")

    assert kwargs["temperature"] == [0.0, 0.2, 0.4]
    assert kwargs["hallucination_silence_threshold"] == 2.0
    assert kwargs["word_timestamps"] is True


# ---------------------------------------------------------------------------
# Deepening (Task 5, bug bounty 2): infra fallbacks must assemble text via
# _join_segments — the single assembly point that carries the tail-strip
# defense. Before the refactor they duplicated the join inline and pasted
# hallucinated tails unfiltered.
# ---------------------------------------------------------------------------


def _fake_model_returning(text: str):
    seg = MagicMock()
    seg.text = text
    model = MagicMock()
    model.transcribe.return_value = (iter([seg]), MagicMock())
    return model


def test_no_vad_infra_fallback_strips_hallucinated_tail():
    model = _fake_model_returning(
        "Fechei o escopo da wave hoje cedo. Inscreva-se no canal e ative o sininho"
    )
    raw, _ = tr._transcribe_no_vad_fallback(model, "x.wav", {}, RuntimeError("silero"))
    assert raw == "Fechei o escopo da wave hoje cedo."


def test_cpu_infra_fallback_strips_hallucinated_tail(monkeypatch):
    from voice import audio as audio_mod
    model = _fake_model_returning(
        "Amanha reviso o contrato com calma. Acesse o nosso site www.supa.com.br"
    )
    monkeypatch.setattr(audio_mod, "get_whisper_model", lambda mode: model)
    raw, _ = tr._transcribe_cpu_fallback("transcribe", "x.wav", {}, {}, RuntimeError("cuda"))
    assert raw == "Amanha reviso o contrato com calma."


def test_model_infra_fallback_strips_hallucinated_tail(monkeypatch):
    from voice import audio as audio_mod
    model = _fake_model_returning(
        "O deploy ficou pronto no fim da tarde. Legendas pela comunidade Amara.org"
    )
    monkeypatch.setattr(audio_mod, "get_whisper_model", lambda mode: model)
    raw, _ = tr._transcribe_model_fallback("transcribe", "x.wav", {}, {}, RuntimeError("model.bin"))
    assert raw == "O deploy ficou pronto no fim da tarde."


def test_trailing_dictated_url_preserved():
    """Review final BB2: URL real ditada como ultima coisa da gravacao nao
    pode ser comida pelo blocklist — so a variante com lead-in ("Acesse o
    nosso site www...") e alucinacao conhecida."""
    raw = "O endereco do cliente e www.padaria-central.com.br"
    assert tr.strip_hallucinated_tail(raw) == raw
