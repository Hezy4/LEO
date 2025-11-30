"""Standalone Porcupine wake-word test harness.

Run this before wiring Porcupine into the full voice agent to make sure the
keyword file, access key, and microphone input all work as expected.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pvporcupine
import sounddevice as sd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_CANDIDATES = [Path(".env"), PROJECT_ROOT / ".env"]


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
    parser.add_argument(
        "--keyword-file",
        required=True,
        help="Path to the Porcupine .ppn keyword file downloaded from the Picovoice Console",
    )
    parser.add_argument(
        "--access-key",
        help="Picovoice access key. Defaults to the PICOVOICE_ACCESS_KEY environment variable.",
    )
    parser.add_argument(
        "--sensitivity",
        type=float,
        default=0.5,
        help="Sensitivity in the range [0, 1]. Higher is more sensitive but may yield more false triggers.",
    )
    parser.add_argument(
        "--input-device",
        type=int,
        help="sounddevice input device index (list devices with --list-devices)",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="Print available audio devices and exit.",
    )
    parser.add_argument(
        "--show-audio-level",
        action="store_true",
        help="Periodically print the RMS input level to help debug microphone gain.",
    )
    parser.add_argument(
        "--level-interval",
        type=float,
        default=1.5,
        help="Seconds between audio-level prints when --show-audio-level is enabled.",
    )
    parser.add_argument(
        "--exit-on-detect",
        action="store_true",
        help="Exit the script immediately after the first detection (useful for quick smoke tests).",
    )
    return parser.parse_args()


def list_devices_and_exit() -> None:
    devices = sd.query_devices()
    for idx, device in enumerate(devices):
        print(
            f"{idx:>3}: {device['name']} | in={device['max_input_channels']} "
            f"out={device['max_output_channels']}"
        )

def resolve_access_key(cli_value: Optional[str]) -> str:
    key = cli_value or os.getenv("PICOVOICE_ACCESS_KEY")
    if not key:
        raise SystemExit("Set --access-key or the PICOVOICE_ACCESS_KEY environment variable.")
    return key


def main() -> int:
    load_env_file()
    args = parse_args()

    if args.list_devices:
        list_devices_and_exit()
        return 0

    keyword_path = Path(args.keyword_file).expanduser().resolve()
    if not keyword_path.exists():
        raise SystemExit(f"Keyword file not found: {keyword_path}")

    access_key = resolve_access_key(args.access_key)

    porcupine: Optional[pvporcupine.Porcupine] = None
    try:
        porcupine = pvporcupine.create(
            access_key=access_key,
            keyword_paths=[str(keyword_path)],
            sensitivities=[args.sensitivity],
        )
    except pvporcupine.PorcupineError as exc:  # pragma: no cover - runtime guard
        raise SystemExit(f"Failed to initialize Porcupine: {exc}") from exc

    stream = None
    last_level_print = time.monotonic()
    print(
        "Listening for wake word... (Ctrl+C to stop)\n"
        f"  keyword: {keyword_path.name}\n"
        f"  sample_rate: {porcupine.sample_rate} Hz\n"
        f"  frame_length: {porcupine.frame_length} samples"
    )

    try:
        stream = sd.RawInputStream(
            samplerate=porcupine.sample_rate,
            blocksize=porcupine.frame_length,
            device=args.input_device,
            dtype="int16",
            channels=1,
        )
        stream.start()
        while True:
            data, overflowed = stream.read(porcupine.frame_length)
            if overflowed:
                print("[warn] Audio overflow detected. Try increasing block size or reducing CPU load.", file=sys.stderr)
            pcm = np.frombuffer(data, dtype=np.int16)
            result = porcupine.process(pcm.tolist())
            detected = bool(result) if isinstance(result, bool) else result >= 0
            if detected:
                print("DETECTED")
                if args.exit_on_detect:
                    break
            if args.show_audio_level:
                now = time.monotonic()
                if now - last_level_print >= args.level_interval:
                    floats = pcm.astype(np.float32) / 32768.0
                    rms = float(np.sqrt(np.mean(np.square(floats))) * 100.0)
                    print(f"[level] RMS={rms:.2f}% of full scale")
                    last_level_print = now
    except KeyboardInterrupt:
        print("\nStopping Porcupine test.")
    finally:
        if stream is not None:
            stream.stop()
            stream.close()
        if porcupine is not None:
            porcupine.delete()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
