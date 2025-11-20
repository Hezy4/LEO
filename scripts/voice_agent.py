"""Voice agent using wake word, Whisper STT, Piper TTS, and LEO orchestrator."""
from __future__ import annotations

import argparse
import queue
import sys
from pathlib import Path
from typing import Optional

import httpx
import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from openwakeword import Model as WakeModel
from piper import PiperVoice

DEFAULT_SAMPLE_RATE = 16000
DEFAULT_BLOCK_SIZE = 512


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000", help="LEO orchestrator base URL")
    parser.add_argument("--user-id", default="henry")
    parser.add_argument("--session-id", default="voice")
    parser.add_argument("--wakeword-model", required=True, help="Path to openwakeword .tflite model")
    parser.add_argument("--wakeword-name", default="leo", help="Wake word model name (defaults to 'leo')")
    parser.add_argument("--wake-threshold", type=float, default=0.5, help="Wake word detection threshold")
    parser.add_argument("--listen-duration", type=float, default=6.0, help="Seconds of audio to record after wake word")
    parser.add_argument("--whisper-model", default="base", help="Whisper model size or path for faster-whisper")
    parser.add_argument("--whisper-device", default="cpu", choices=["cpu", "cuda"], help="Device for Whisper")
    parser.add_argument("--whisper-compute-type", default="int8", help="faster-whisper compute type (e.g. float16, int8)")
    parser.add_argument("--language", default="en")
    parser.add_argument("--piper-model", required=True, help="Path to Piper ONNX model")
    parser.add_argument("--piper-config", required=True, help="Path to Piper JSON config")
    parser.add_argument("--input-device", type=int, default=None, help="sounddevice input device index")
    parser.add_argument("--sample-rate", type=int, default=DEFAULT_SAMPLE_RATE)
    parser.add_argument("--block-size", type=int, default=DEFAULT_BLOCK_SIZE)
    parser.add_argument("--quiet", action="store_true", help="Suppress intermediate logs")
    return parser.parse_args()


def load_whisper(args: argparse.Namespace) -> WhisperModel:
    return WhisperModel(
        args.whisper_model,
        device=args.whisper_device,
        compute_type=args.whisper_compute_type,
    )


def load_piper(args: argparse.Namespace) -> PiperVoice:
    model_path = Path(args.piper_model)
    config_path = Path(args.piper_config)
    if not model_path.exists() or not config_path.exists():
        raise SystemExit("Piper model/config not found")
    return PiperVoice.load(str(model_path), str(config_path))


def record_audio(stream_queue: queue.Queue[bytes], seconds: float, sample_rate: int) -> np.ndarray:
    total_samples = int(seconds * sample_rate)
    chunks: list[np.ndarray] = []
    collected = 0
    while collected < total_samples:
        data = stream_queue.get()
        block = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        chunks.append(block)
        collected += len(block)
    return np.concatenate(chunks)


def transcribe_audio(model: WhisperModel, audio: np.ndarray, sample_rate: int, language: str) -> str:
    segments, _ = model.transcribe(audio, language=language, beam_size=5)
    text_parts = [seg.text.strip() for seg in segments if seg.text]
    return " ".join(text_parts).strip()


def speak_text(voice: PiperVoice, text: str) -> None:
    audio, sample_rate = voice.synthesize(text, length_scale=1.0, noise=0.667, noisew=0.8)
    sd.play(audio, sample_rate)
    sd.wait()


def send_chat(client: httpx.Client, base_url: str, user_id: str, session_id: str, message: str) -> str:
    payload = {"user_id": user_id, "session_id": session_id, "message": message}
    response = client.post(f"{base_url.rstrip('/')}/chat", json=payload, timeout=120)
    response.raise_for_status()
    body = response.json()
    for action in body.get("actions", []):
        print(f"[tool] {action.get('tool')} -> {action.get('status')}: {action.get('message')}")
    return body.get("reply", "")


def main() -> None:
    args = parse_args()

    wake_model = WakeModel(wakeword_models=[args.wakeword_model])
    wakeword_name = args.wakeword_name or Path(args.wakeword_model).stem
    whisper = load_whisper(args)
    piper_voice = load_piper(args)

    client = httpx.Client(timeout=60.0)
    audio_queue: queue.Queue[bytes] = queue.Queue()

    def audio_callback(indata, frames, time_info, status):  # pragma: no cover - realtime callback
        if status:
            print(status, file=sys.stderr)
        audio_queue.put(bytes(indata))

    with sd.RawInputStream(
        samplerate=args.sample_rate,
        blocksize=args.block_size,
        device=args.input_device,
        dtype="int16",
        channels=1,
        callback=audio_callback,
    ):
        print("Voice agent running. Say the wake word to start (Ctrl+C to exit).")
        try:
            while True:
                data = audio_queue.get()
                block = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                scores = wake_model.predict(block)
                score = scores.get(wakeword_name, 0.0)
                if score >= args.wake_threshold:
                    if not args.quiet:
                        print(f"Wake word detected (score={score:.2f}). Listening...")
                    audio = np.concatenate([block, record_audio(audio_queue, args.listen_duration, args.sample_rate)])
                    text = transcribe_audio(whisper, audio, args.sample_rate, args.language)
                    if not text:
                        if not args.quiet:
                            print("No speech detected.")
                        continue
                    print(f"you (transcribed)> {text}")
                    try:
                        reply = send_chat(client, args.base_url, args.user_id, args.session_id, text)
                    except httpx.HTTPError as exc:
                        print(f"Chat request failed: {exc}")
                        continue
                    print(f"leo > {reply}")
                    speak_text(piper_voice, reply)
        except KeyboardInterrupt:
            print("\nVoice agent stopped.")
        finally:
            client.close()


if __name__ == "__main__":
    main()
