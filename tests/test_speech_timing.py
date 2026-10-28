import pytest

import conversation_loop


def test_speech_timing_separates_synthesis_and_playback(monkeypatch):
    clock = iter([10.0, 12.0, 15.5])
    events = []
    monkeypatch.setattr(conversation_loop.time, "perf_counter", lambda: next(clock))
    monkeypatch.setattr(conversation_loop, "voice_event",
                        lambda event, **fields: events.append((event, fields)))
    monkeypatch.setattr(conversation_loop, "synthesize_to_wav", lambda text: "reply.wav")

    def play(path):
        assert path == "reply.wav"
        assert events[-1] == ("speech_audio_ready",
                              {"kind": "answer", "synthesis_seconds": "2.000"})
        assert not any(event == "speech_output_finished" for event, _ in events)

    monkeypatch.setattr(conversation_loop, "play_wav_file", play)
    conversation_loop.speak("Four.", kind="answer")
    assert events[-1] == ("speech_output_finished", {
        "kind": "answer", "playback_seconds": "3.500", "total_seconds": "5.500",
    })


def test_failed_playback_does_not_claim_completion(monkeypatch):
    events = []
    monkeypatch.setattr(conversation_loop, "voice_event",
                        lambda event, **fields: events.append(event))
    monkeypatch.setattr(conversation_loop, "synthesize_to_wav", lambda text: "reply.wav")

    def fail(path):
        raise ConnectionError("disconnected")

    monkeypatch.setattr(conversation_loop, "play_wav_file", fail)
    with pytest.raises(ConnectionError):
        conversation_loop.speak("Four.")
    assert "speech_audio_ready" in events
    assert "speech_output_finished" not in events
