"""chirp.py - the fleet's Brainfuck phrases as a WAV for her speaker (/chirp?u=<n>, RIFT's conversations).

Every phrase is a Brainfuck program that prints its words; a robot says it by beeping the source,
one tone per symbol. The robots with a buzzer do that in firmware (talk_bf.h); she has a speaker, so
this writes the same tones into a WAV. talk_bf.json is RIFT/Fleet/talk_bf.json: copy it when
brainfuck_talk.py changes.
"""
import io
import json
import math
import os
import struct
import wave

RATE = 22050
GAP_MS = 10
VOICE_PCT = 105      # a little higher than the phrasebook's, as KIDA-00 is smaller than NORA
TONES = {"+": 1568, "-": 784, ">": 1319, "<": 1047, "[": 880, "]": 1175, ".": 2093, ",": 523}

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "talk_bf.json"), encoding="utf-8") as f:
    UTTERANCES = {u["index"]: u for u in json.load(f)}


def wav_of(index):
    """WAV bytes for utterance `index`, KeyError if there's no such one."""
    samples = bytearray()
    for c in UTTERANCES[index]["bf"]:
        hz = TONES.get(c, 0) * VOICE_PCT / 100
        for n in range(RATE * (80 if c == "." else 28) // 1000):
            samples += struct.pack("<h", int(9000 * math.copysign(1, math.sin(2 * math.pi * hz * n / RATE))))
        samples += bytes(2 * RATE * GAP_MS // 1000)
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(samples))
    return out.getvalue()
