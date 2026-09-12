from play_audio import play_piper_audio
from text_to_speech import start_piper


def speak(text: str, model=None):
    piper = start_piper(text)
    play_piper_audio(piper, model=model)
