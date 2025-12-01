"""Voice agent using Porcupine wake word, Whisper STT, Piper TTS, and LEO orchestrator."""
from __future__ import annotations

import argparse
import os
import queue
import re
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

import httpx
import numpy as np
import pvporcupine
import sounddevice as sd
from faster_whisper import WhisperModel
from piper import PiperVoice, SynthesisConfig
from scipy.signal import resample_poly

TARGET_SAMPLE_RATE = 16000
DEFAULT_BLOCK_SIZE = 512
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_KEYWORD_PATH = PROJECT_ROOT / "data" / "wakeword" / "hey_leo.ppn"
ENV_CANDIDATES = [Path(".env"), PROJECT_ROOT / ".env"]
DEFAULT_PIPER_SYN_CONFIG = SynthesisConfig(length_scale=1.0, noise_scale=0.667, noise_w_scale=0.8)


def load_env_file() -> None:
    loaded: set[Path] = set()
    for raw_path in ENV_CANDIDATES:
        candidate = raw_path.expanduser()
        if not candidate.exists():
            continue
        resolved = candidate.resolve()
        if resolved in loaded:
            continue
        loaded.add(resolved)
        for line in resolved.read_text().splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000", help="LEO orchestrator base URL")
    parser.add_argument("--user-id", default="henry")
    parser.add_argument("--session-id", default="voice")
    parser.add_argument(
        "--listen-duration",
        type=float,
        default=60.0,
        help="Max seconds to record per request before forcing a cutoff (set <=0 for unlimited)",
    )
    parser.add_argument("--whisper-model", default="base", help="Whisper model size or path for faster-whisper")
    parser.add_argument("--whisper-device", default="cpu", choices=["cpu", "cuda"], help="Device for Whisper")
    parser.add_argument("--whisper-compute-type", default="int8", help="faster-whisper compute type (e.g. float16, int8)")
    parser.add_argument("--language", default="en")
    parser.add_argument("--piper-model", required=True, help="Path to Piper ONNX model")
    parser.add_argument("--piper-config", required=True, help="Path to Piper JSON config")
    parser.add_argument("--input-device", type=int, default=None, help="sounddevice input device index")
    parser.add_argument("--sample-rate", type=int, default=TARGET_SAMPLE_RATE)
    parser.add_argument("--block-size", type=int, default=DEFAULT_BLOCK_SIZE)
    parser.add_argument("--quiet", action="store_true", help="Suppress intermediate logs")
    parser.add_argument(
        "--porcupine-keyword",
        default=str(DEFAULT_KEYWORD_PATH),
        help=(
            "Path to the Porcupine .ppn keyword file. Defaults to data/wakeword/hey_leo.ppn "
            "relative to the repo (override if you need a different keyword)."
        ),
    )
    parser.add_argument(
        "--porcupine-access-key",
        help="Picovoice access key. Defaults to PICOVOICE_ACCESS_KEY environment variable.",
    )
    parser.add_argument(
        "--porcupine-sensitivity",
        type=float,
        default=0.65,
        help="Porcupine sensitivity [0,1]; higher means more triggers but more false positives.",
    )
    parser.add_argument(
        "--manual-trigger",
        action="store_true",
        help="Skip wake-word detection and manually trigger recordings (debug fallback).",
    )
    parser.add_argument(
        "--silence-duration",
        type=float,
        default=1.75,
        help="Seconds of trailing silence required before ending an utterance (raise this if pauses cut you off; set <=0 to disable).",
    )
    parser.add_argument(
        "--followup-window",
        type=float,
        default=5.0,
        help=(
            "Seconds to keep listening for follow-up speech after activation (set to 0 to disable)."
        ),
    )
    parser.add_argument(
        "--speech-threshold",
        type=float,
        default=0.02,
        help="RMS threshold for treating microphone input as speech during follow-up listening.",
    )
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


def load_porcupine(args: argparse.Namespace) -> Tuple[Optional[pvporcupine.Porcupine], Optional[Path]]:
    if args.manual_trigger:
        return None, None
    if not args.porcupine_keyword:
        raise SystemExit("--porcupine-keyword is required unless --manual-trigger is enabled.")
    keyword_path = Path(args.porcupine_keyword).expanduser().resolve()
    if not keyword_path.exists():
        raise SystemExit(f"Porcupine keyword file not found: {keyword_path}")
    access_key = args.porcupine_access_key or os.getenv("PICOVOICE_ACCESS_KEY")
    if not access_key:
        raise SystemExit("Set --porcupine-access-key or PICOVOICE_ACCESS_KEY environment variable.")
    try:
        detector = pvporcupine.create(
            access_key=access_key,
            keyword_paths=[str(keyword_path)],
            sensitivities=[args.porcupine_sensitivity],
        )
    except pvporcupine.PorcupineError as exc:  # pragma: no cover - runtime guard
        raise SystemExit(f"Failed to initialize Porcupine: {exc}") from exc
    return detector, keyword_path


def resample_audio(audio: np.ndarray, input_rate: int, target_rate: int = TARGET_SAMPLE_RATE) -> np.ndarray:
    if input_rate == target_rate:
        return audio
    return resample_poly(audio, target_rate, input_rate)


def flush_queue(stream_queue: queue.Queue[bytes]) -> None:
    """Drop any buffered audio so each recording starts fresh."""
    while True:
        try:
            stream_queue.get_nowait()
        except queue.Empty:
            break


def record_utterance(
    stream_queue: queue.Queue[bytes],
    sample_rate: int,
    max_seconds: float,
    silence_seconds: float,
    threshold: float,
    initial_block: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Record until trailing silence is observed or the max duration is hit."""
    samples: list[np.ndarray] = []
    started = False
    silence_time = 0.0
    deadline = None if max_seconds <= 0 else time.monotonic() + max_seconds

    if initial_block is not None and initial_block.size:
        samples.append(initial_block)
        started = True

    while True:
        if deadline is not None and time.monotonic() >= deadline:
            break
        timeout = 0.1
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            timeout = min(timeout, remaining)
        try:
            data = stream_queue.get(timeout=timeout)
        except queue.Empty:
            continue
        block = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        if block.size == 0:
            continue
        block_duration = len(block) / sample_rate
        rms = float(np.sqrt(np.mean(np.square(block))))
        if not started:
            if rms < threshold:
                continue
            started = True
        samples.append(block)
        if threshold > 0 and rms < threshold and silence_seconds > 0:
            silence_time += block_duration
            if silence_time >= silence_seconds:
                break
        else:
            silence_time = 0.0

    if not samples:
        return np.array([], dtype=np.float32)
    return np.concatenate(samples)


def detect_followup_utterance(
    stream_queue: queue.Queue[bytes],
    sample_rate: int,
    max_seconds: float,
    silence_seconds: float,
    wait_seconds: float,
    threshold: float,
) -> Optional[np.ndarray]:
    """Return an audio buffer when speech-like input occurs within the grace window."""
    if wait_seconds <= 0:
        return None
    deadline = time.monotonic() + wait_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        timeout = min(0.1, remaining)
        try:
            data = stream_queue.get(timeout=timeout)
        except queue.Empty:
            continue
        block = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(np.square(block))))
        if rms < threshold:
            continue
        utterance = record_utterance(
            stream_queue,
            sample_rate,
            max_seconds,
            silence_seconds,
            threshold,
            initial_block=block,
        )
        if utterance.size:
            return utterance
        return None


def transcribe_audio(model: WhisperModel, audio: np.ndarray, sample_rate: int, language: str) -> str:
    resampled = resample_audio(audio, sample_rate, TARGET_SAMPLE_RATE)
    segments, _ = model.transcribe(resampled, language=language, beam_size=5)
    text_parts = [seg.text.strip() for seg in segments if seg.text]
    return " ".join(text_parts).strip()


def is_meaningful_text(text: str) -> bool:
    """Return True if the transcription contains alphanumeric content (not just punctuation/whitespace)."""

    if not text:
        return False
    return bool(re.search(r"[A-Za-z0-9]", text))


def speak_text(voice: PiperVoice, text: str) -> None:
    chunks = list(voice.synthesize(text, syn_config=DEFAULT_PIPER_SYN_CONFIG))
    if not chunks:
        return
    audio = np.concatenate([chunk.audio_float_array for chunk in chunks])
    sample_rate = chunks[0].sample_rate
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
    load_env_file()
    args = parse_args()

    porcupine, keyword_path = load_porcupine(args)
    mic_sample_rate = args.sample_rate if porcupine is None else porcupine.sample_rate
    block_size = args.block_size if porcupine is None else porcupine.frame_length
    whisper = load_whisper(args)
    piper_voice = load_piper(args)

    client = httpx.Client(timeout=60.0)
    audio_queue: queue.Queue[bytes] = queue.Queue()
    followup_deadline = 0.0
    followup_prompted = False

    def reset_followup_window() -> None:
        nonlocal followup_deadline, followup_prompted
        followup_deadline = 0.0
        followup_prompted = False

    def extend_followup_window() -> None:
        nonlocal followup_deadline, followup_prompted
        if args.followup_window > 0:
            followup_deadline = time.monotonic() + args.followup_window
            followup_prompted = False
        else:
            reset_followup_window()

    def process_audio_block(audio: np.ndarray) -> bool:
        if audio.size == 0:
            if not args.quiet:
                print("No audio captured.")
            return False
        text = transcribe_audio(whisper, audio, mic_sample_rate, args.language)
        if not text or not is_meaningful_text(text):
            if not args.quiet:
                print("No speech detected.")
            return False
        print(f"you (transcribed)> {text}")
        try:
            reply = send_chat(client, args.base_url, args.user_id, args.session_id, text)
        except httpx.HTTPError as exc:
            print(f"Chat request failed: {exc}")
            return True
        print(f"leo > {reply}")
        speak_text(piper_voice, reply)
        flush_queue(audio_queue)
        return True

    def audio_callback(indata, frames, time_info, status):  # pragma: no cover - realtime callback
        if status:
            print(status, file=sys.stderr)
        audio_queue.put(bytes(indata))

    with sd.RawInputStream(
        samplerate=mic_sample_rate,
        blocksize=block_size,
        device=args.input_device,
        dtype="int16",
        channels=1,
        callback=audio_callback,
    ):
        if porcupine is None:
            print("Voice agent running in manual trigger mode (Porcupine disabled).")
            print("Press Enter when you're ready to speak (Ctrl+C to exit).")
        else:
            keyword_label = keyword_path.name if keyword_path else "wake word"
            print(
                "Voice agent running with Porcupine wake word detection. "
                f"Say '{keyword_label}' to start (Ctrl+C to exit)."
            )
        try:
            while True:
                now = time.monotonic()
                if args.followup_window > 0 and now < followup_deadline:
                    if not args.quiet and not followup_prompted:
                        remaining = max(0.0, followup_deadline - now)
                        print(
                            f"Listening for follow-ups (wake word not required) "
                            f"for {remaining:.1f}s..."
                        )
                        followup_prompted = True
                    wait_seconds = followup_deadline - now
                    audio = detect_followup_utterance(
                        audio_queue,
                        mic_sample_rate,
                        args.listen_duration,
                        args.silence_duration,
                        wait_seconds,
                        args.speech_threshold,
                    )
                    if audio is None:
                        reset_followup_window()
                        continue
                    if process_audio_block(audio):
                        extend_followup_window()
                    else:
                        followup_prompted = False
                    continue

                followup_prompted = False
                if porcupine is None:
                    input("\n[manual trigger] Press Enter to capture speech...")
                    flush_queue(audio_queue)
                    audio = record_utterance(
                        audio_queue,
                        mic_sample_rate,
                        args.listen_duration,
                        args.silence_duration,
                        args.speech_threshold,
                    )
                    if process_audio_block(audio):
                        extend_followup_window()
                    else:
                        reset_followup_window()
                    continue

                data = audio_queue.get()
                block_int16 = np.frombuffer(data, dtype=np.int16)
                result = porcupine.process(block_int16.tolist())
                detected = bool(result) if isinstance(result, bool) else result >= 0
                if detected:
                    if not args.quiet:
                        print("Wake word detected. Listening...")
                    block_float = block_int16.astype(np.float32) / 32768.0
                    audio = record_utterance(
                        audio_queue,
                        mic_sample_rate,
                        args.listen_duration,
                        args.silence_duration,
                        args.speech_threshold,
                        initial_block=block_float,
                    )
                    if process_audio_block(audio):
                        extend_followup_window()
                    else:
                        reset_followup_window()
        except KeyboardInterrupt:
            print("\nVoice agent stopped.")
        finally:
            client.close()
            if porcupine is not None:
                porcupine.delete()


if __name__ == "__main__":
    main()
