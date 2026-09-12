import sounddevice as sd
import soundfile as sf

DEVICE = 2
SAMPLE_RATE = 16000
SECONDS = 5

print("Recording for 5 seconds...")
audio = sd.rec(
    int(SECONDS * SAMPLE_RATE),
    samplerate=SAMPLE_RATE,
    channels=1,
    dtype="int16",
    device=DEVICE,
)
sd.wait()

sf.write("python_test.wav", audio, SAMPLE_RATE)
print("Playing back...")
sd.play(audio, samplerate=SAMPLE_RATE, device=DEVICE)
sd.wait()

print("Done.")
