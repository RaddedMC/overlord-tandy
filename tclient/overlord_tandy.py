"""Overlord Tandy host for the tb.do client.

tb.do runs on the Tandy and does its own line editing, title screen and
"thinking" animation. It sends each typed line ending in CR, and shows each
line it receives (ending in CR, at most 39 chars) as a right-aligned reply.
This host only reads those lines, asks the model and sends the answer back.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from textwrap import wrap
from typing import TYPE_CHECKING, Any

import serial

if TYPE_CHECKING:
    from openai import OpenAI

SERIAL_DEVICE = "/dev/ttyUSB0"
SERIAL_BAUDRATE = 9600  # tb.do opens "COM:88N1ENN": 9600 baud, 8N1, XON/XOFF.
LINE_WIDTH = 39  # tb.do keeps at most 39 chars of each received line.
LINE_DELAY = 0.2  # Seconds between lines, so the BASIC program can keep up.
MAX_TOKENS = 2048  # Longest reply the model may send; longer ones are cut off.
REQUEST_TIMEOUT = 60  # Seconds before giving up on one API and trying the next.
WRITE_TIMEOUT = 5  # Seconds a serial write may block (e.g. after an XOFF) before failing.
CONFIG_PATH = Path.home() / "ai_apis.json"

SYSTEM_PROMPT = """You are Overlord Tandy, a helpful AI running on a Tandy 200.
Reply in plain ASCII only.
Keep every reply brief: at most 15 short lines, unless the user asks for a longer response.
Do not use markdown, colors, emojis, or characters outside the ASCII charset."""

HELP_TEXT = (
    "/new starts a new chat.\n"
    "/help shows this help."
)


@dataclass(frozen=True)
class ApiConfig:
    """Configuration for one OpenAI-compatible API endpoint."""

    name: str
    url: str
    key: str
    model: str


def debug(message: str) -> None:
    """Print a timestamped debug line on the host terminal."""
    print(f"[{time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


def load_api_configs(path: Path = CONFIG_PATH) -> list[ApiConfig]:
    """Load every configured OpenAI-compatible endpoint, in file order."""
    try:
        with path.open(encoding="utf-8") as config_file:
            data: Any = json.load(config_file)
    except FileNotFoundError as exc:
        raise RuntimeError(f"API configuration not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"API configuration is not valid JSON: {path}") from exc
    except OSError as exc:
        raise RuntimeError(f"Could not read API configuration: {exc}") from exc

    apis = data.get("apis") if isinstance(data, dict) else None
    if not isinstance(apis, list):
        raise RuntimeError("API configuration must contain an 'apis' list.")

    configs: list[ApiConfig] = []
    for api in apis:
        if not isinstance(api, dict) or api.get("type") != "openai":
            continue
        url = api.get("url")
        model = api.get("choice-model")
        if isinstance(url, str) and isinstance(model, str) and url and model:
            configs.append(ApiConfig(
                name=str(api.get("name", "OpenAI-compatible API")),
                url=url,
                key=str(api.get("key", "")),
                model=model,
            ))
    if not configs:
        raise RuntimeError("No usable openai-type API was found in the configuration.")
    return configs


# Typographic punctuation models often send, mapped to plain ASCII.
ASCII_REPLACEMENTS = str.maketrans({
    "‘": "'",  # Char: "‘"
    "’": "'",  # Char: "’"
    "‚": "'",  # Char: "‚"
    "‛": "'",  # Char: "‛"
    "′": "'",  # Char: "′"
    "“": '"',  # Char: "“"
    "”": '"',  # Char: "”"
    "„": '"',  # Char: "„"
    "‟": '"',  # Char: "‟"
    "″": '"',  # Char: "″"
    "«": '"',  # Char: "«"
    "»": '"',  # Char: "»"
    "‐": "-",  # Char: "‐"
    "‑": "-",  # Char: "‑"
    "‒": "-",  # Char: "‒"
    "–": "-",  # Char: "–"
    "—": "--",  # Char: "—"
    "−": "-",  # Char: "−"
    "…": "...",  # Char: "…"
    "•": "*",  # Char: "•"
    " ": " ",  # Char: "NBSP"
    "\t": " ",
})


def ascii_text(text: str) -> str:
    """Return text safe for the Tandy's ASCII-only display."""
    text = text.translate(ASCII_REPLACEMENTS)
    # Split accented letters into letter + accent so the accent can be dropped (é -> e).
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return text.encode("ascii", "replace").decode("ascii")


def reply_lines(text: str) -> list[str]:
    """Wrap text into lines tb.do can show, dropping control characters."""
    lines: list[str] = []
    for paragraph in ascii_text(text).replace("\r", "").split("\n"):
        paragraph = "".join(c for c in paragraph if 32 <= ord(c) <= 126)
        lines.extend(wrap(paragraph, LINE_WIDTH) or [""])
    return lines


def send_response(connection: Any, text: str) -> None:
    """Send text to the Tandy one line at a time."""
    lines = reply_lines(text)
    debug(f"TX {len(lines)} line(s)")
    for number, line in enumerate(lines, start=1):
        data = (line + "\r\n").encode("ascii")
        started = time.monotonic()
        try:
            connection.write(data)
            connection.flush()
        except serial.SerialTimeoutException:
            debug(f"TX line {number} timed out after {WRITE_TIMEOUT}s: "
                  "the Tandy may have sent XOFF or the port is not connected")
            return
        elapsed = time.monotonic() - started
        debug(f"TX {number:>2}: {data!r}" + (f" (write took {elapsed:.2f}s)" if elapsed > 0.5 else ""))
        time.sleep(LINE_DELAY)
    debug("TX done")


def read_line(connection: Any) -> str:
    """Wait for one CR-terminated line typed on the Tandy."""
    buffer = bytearray()
    while True:
        data = connection.read(256)
        if not data:
            continue
        debug(f"RX raw {data!r}")
        for byte in data:
            if byte == 13:  # CR ends the line.
                text = buffer.decode("ascii", "replace").strip()
                buffer.clear()
                if text:
                    return text
                debug("RX empty line ignored")
            elif byte != 10:  # Ignore LF.
                buffer.append(byte)


def make_client(config: ApiConfig) -> OpenAI:
    """Create the OpenAI client for an OpenAI-compatible endpoint."""
    from openai import OpenAI

    # The default timeout is 10 minutes with 2 retries, which leaves the Tandy
    # stuck on "thinking" when an endpoint is unreachable.
    return OpenAI(
        api_key=config.key, base_url=config.url, timeout=REQUEST_TIMEOUT, max_retries=0
    )


def ask_model(client: OpenAI, model: str, messages: list[dict[str, str]]) -> str:
    """Request one concise response from the configured model."""
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.4,
        max_tokens=MAX_TOKENS,
    )
    if not response.choices:
        raise RuntimeError("The model returned no choices.")
    message = response.choices[0].message
    content = getattr(message, "content", None)
    debug(f"Model finish_reason={response.choices[0].finish_reason!r}, "
          f"content={len(content or '')} chars")
    if not content:
        # Some reasoning models expose their answer in a provider-specific field.
        content = getattr(message, "reasoning_content", None)
    if not content:
        content = getattr(message, "reasoning", None)
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("The model returned an empty response.")
    answer = ascii_text(content).strip()
    if response.choices[0].finish_reason == "length":
        answer += "\n\n[Reply cut off: too long.]"
    return answer


def ask_with_fallback(configs: list[ApiConfig], messages: list[dict[str, str]]) -> str:
    """Try each configured API in turn, logging progress while waiting."""
    from openai import OpenAIError

    errors: list[str] = []
    for config in configs:
        debug(f"Asking {config.name} ({config.model} at {config.url})")
        result: dict[str, Any] = {}

        def request() -> None:
            try:
                result["answer"] = ask_model(make_client(config), config.model, messages)
            except (OpenAIError, RuntimeError) as exc:
                result["error"] = exc

        started = time.monotonic()
        worker = threading.Thread(target=request, daemon=True)
        worker.start()
        while worker.is_alive():
            worker.join(5)
            if worker.is_alive():
                debug(f"  still waiting ({time.monotonic() - started:.0f}s)")
        elapsed = time.monotonic() - started
        if "answer" in result:
            debug(f"  answered in {elapsed:.1f}s")
            return result["answer"]
        error = result.get("error")
        debug(f"  failed after {elapsed:.1f}s: {type(error).__name__}: {error}")
        errors.append(f"{config.name}: {error}")
    raise RuntimeError("All APIs failed: " + "; ".join(errors))


def run(connection: Any, configs: list[ApiConfig]) -> None:
    """Answer each line from the Tandy until the host is stopped."""
    history: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    while True:
        debug("Waiting for a line from the Tandy...")
        user_text = read_line(connection)
        debug(f"Tandy: {user_text!r}")
        command = user_text.lower()
        if command == "/help":
            send_response(connection, HELP_TEXT)
            continue
        if command in {"/new", "/newchat"}:
            history = [{"role": "system", "content": SYSTEM_PROMPT}]
            send_response(connection, "New chat created.")
            continue

        history.append({"role": "user", "content": user_text})
        try:
            answer = ask_with_fallback(configs, history)
        except RuntimeError as exc:
            history.pop()
            debug(f"Model request failed: {exc}")
            send_response(connection, "Model error. Check the host log.")
            continue
        history.append({"role": "assistant", "content": answer})
        debug(f"Overlord: {answer!r}")
        send_response(connection, answer)


def main(argv: list[str] | None = None) -> int:
    """Load configuration, open the serial port and serve the Tandy."""
    parser = argparse.ArgumentParser(description="Run the Overlord Tandy host for tb.do.")
    parser.add_argument(
        "--device",
        default=SERIAL_DEVICE,
        help=f"serial device for the Tandy connection (default: {SERIAL_DEVICE})",
    )
    args = parser.parse_args(argv)

    try:
        configs = load_api_configs()
        for number, config in enumerate(configs, start=1):
            debug(f"API {number}: {config.name} ({config.model} at {config.url})")
        with serial.Serial(
            args.device, SERIAL_BAUDRATE, bytesize=8, parity="N", stopbits=1,
            timeout=0.1, write_timeout=WRITE_TIMEOUT, xonxoff=True,
        ) as connection:
            connection.reset_input_buffer()
            debug(f"Listening on {args.device} at {SERIAL_BAUDRATE} 8N1, XON/XOFF")
            run(connection, configs)
    except (RuntimeError, serial.SerialException) as exc:
        print(f"Overlord Tandy: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nOverlord Tandy stopped.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
