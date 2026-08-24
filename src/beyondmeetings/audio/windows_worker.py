"""Child process that mixes Windows system audio and microphone into a WAV."""
from __future__ import annotations

import sys
import wave
from pathlib import Path


SAMPLE_RATE = 48_000
BLOCK_FRAMES = 4_800


def _mono(data, numpy):
    if data is None or not len(data):
        return numpy.empty(0, dtype="float32")
    return numpy.asarray(data, dtype="float32").mean(axis=1)


def record(target: Path) -> None:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    stop = target.with_suffix(".stop")
    done = target.with_suffix(".done")
    error = target.with_suffix(".error")

    try:
        import numpy
        import soundcard

        speaker = soundcard.default_speaker()
        if speaker is None:
            raise RuntimeError("Windows has no default output device")
        loopback = soundcard.get_microphone(speaker.id, include_loopback=True)
        microphone = soundcard.default_microphone()

        with wave.open(str(target), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(SAMPLE_RATE)
            with loopback.recorder(samplerate=SAMPLE_RATE) as system_stream:
                mic_context = (
                    microphone.recorder(samplerate=SAMPLE_RATE)
                    if microphone is not None else None
                )
                mic_stream = mic_context.__enter__() if mic_context else None
                try:
                    while not stop.exists():
                        system = _mono(system_stream.record(BLOCK_FRAMES), numpy)
                        mic = _mono(mic_stream.record(BLOCK_FRAMES), numpy) if mic_stream else None
                        if mic is not None and len(mic):
                            count = min(len(system), len(mic))
                            mixed = system[:count] + mic[:count]
                        else:
                            mixed = system
                        pcm = (numpy.clip(mixed, -1.0, 1.0) * 32767).astype("<i2")
                        output.writeframes(pcm.tobytes())
                finally:
                    if mic_context:
                        mic_context.__exit__(None, None, None)
    except Exception as exc:
        error.write_text(str(exc), encoding="utf-8")
    finally:
        done.touch()


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    record(Path(sys.argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
