import subprocess

TEXT = "Speech recognition is working. Jarvis can hear you."

subprocess.run([
    "espeak-ng",
    "-w", "reply.wav",
    TEXT
], check=True)

subprocess.run([
    "aplay",
    "-D", "plughw:2,0",
    "reply.wav"
], check=True)
