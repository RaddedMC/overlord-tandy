"""Overlord Tandy host for the BASIC chat client on a Tandy 200.

Protocol (both directions):
  * ASCII text, messages end with a single EOT byte (0x04).
  * Tandy -> host: one line typed by the user, then EOT (no CR/LF).
  * Host -> Tandy: reply lines each ending with RS (0x1E, "newline"), then EOT.
    No CR/LF is ever sent to the Tandy.
The BASIC client does its own echo, startup screen, "thinking" animation,
right-aligned display and prompt, so the host only sends plain text.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from textwrap import wrap
from typing import TYPE_CHECKING, Any

import serial

if TYPE_CHECKING:
    from openai import OpenAI

LINE_WIDTH = 39  # The BASIC client keeps at most 39 chars per received line.
SERIAL_DEVICE = "/dev/ttyUSB0"
SERIAL_BAUDRATE = 9600  # Matches "COM:88N1ENN" in the BASIC client.
MAX_TOKENS = 2048
EOT = b"\x04"  # End of message.
NEWLINE = b"\x1e"  # End of one display line (ASCII record separator).
# The BASIC client handles each received character in an interrupt routine, so
# send in small chunks, no faster than it can keep up. Raise CHAR_DELAY if the
# Tandy drops characters; lower it if replies feel slow.
WRITE_CHUNK = 16
CHAR_DELAY = 1 / 50  # Seconds per character.
LINE_DELAY = 0.1  # Extra pause after each line.
CONFIG_PATH = Path.home() / "ai_apis.json"

SYSTEM_PROMPT = """You are Overlord Tandy, a helpful AI running on a Tandy 200.
Reply in plain ASCII only.
Keep every reply brief: at most 12 short lines, unless the user asks for a longer response.
Do not use markdown, colors, emojis, or characters outside the ASCII charset."""

HELP_TEXT = (
    "Overlord Tandy commands:\n"
    "/new starts a new chat.\n"
    "/help shows this help.\n"
    "/quit exits the host program."
)


@dataclass(frozen=True)
class ApiConfig:
    """Configuration for one OpenAI-compatible API endpoint."""

    name: str
    url: str
    key: str
    model: str


def load_api_config(path: Path = CONFIG_PATH) -> ApiConfig:
    """Load the first configured OpenAI-compatible endpoint."""
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

    for api in apis:
        if not isinstance(api, dict) or api.get("type") != "openai":
            continue
        url = api.get("url")
        model = api.get("choice-model")
        if isinstance(url, str) and isinstance(model, str) and url and model:
            return ApiConfig(
                name=str(api.get("name", "OpenAI-compatible API")),
                url=url,
                key=str(api.get("key", "")),
                model=model,
            )
    raise RuntimeError("No usable openai-type API was found in the configuration.")


# Typographic punctuation models often send, mapped to plain ASCII.
ASCII_REPLACEMENTS = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u2032": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u2033": '"',
        "\u00ab": '"',
        "\u00bb": '"',
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2212": "-",
        "\u2014": "--",
        "\u2026": "...",
        "\u2022": "*",
        "\u00a0": " ",
        "\t": " ",
    }
)


def ascii_text(text: str) -> str:
    """Return text safe for the Tandy's ASCII-only display."""
    text = text.translate(ASCII_REPLACEMENTS)
    # Split accented letters into letter + accent, then drop the accent.
    text = "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )
    return text.encode("ascii", "replace").decode("ascii")


def display_lines(text: str, width: int = LINE_WIDTH) -> list[str]:
    """Wrap text into lines the BASIC client can hold."""
    safe = ascii_text(text).replace("\r", "")
    lines: list[str] = []
    for source_line in safe.split("\n"):
        lines.extend(wrap(source_line, width=width, replace_whitespace=False) or [""])
    return lines


class TandyLink:
    """Serial link to the BASIC client."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def read_message(self) -> str:
        """Block until a complete message (ending in EOT) arrives."""
        buffer = bytearray()
        while True:
            raw = self.connection.read(1)
            if not raw:
                continue
            byte = raw[0]
            if byte == EOT[0]:
                return buffer.decode("ascii", "replace").strip()
            if 32 <= byte <= 126:  # Ignore CR/LF and other control bytes.
                buffer.append(byte)

    def _write(self, data: bytes) -> None:
        for start in range(0, len(data), WRITE_CHUNK):
            chunk = data[start : start + WRITE_CHUNK]
            self.connection.write(chunk)
            self.connection.flush()
            time.sleep(len(chunk) * CHAR_DELAY)

    def send(self, text: str) -> None:
        """Send a (possibly multi-line) reply, then EOT."""
        for line in display_lines(text):
            self._write(line.encode("ascii") + NEWLINE)
            time.sleep(LINE_DELAY)
        self._write(EOT)


class CliLink:
    """Same interface on a normal terminal, for testing without the Tandy."""

    def read_message(self) -> str:
        return input("You> ").strip()

    def send(self, text: str) -> None:
        print("\n".join(display_lines(text)))


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


def run(link: Any, client: OpenAI, model: str) -> None:
    """Answer messages from the Tandy until told to quit."""
    from openai import OpenAIError

    history: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    while True:
        try:
            text = link.read_message()
        except EOFError:
            return
        if not text:
            link.send("")  # Empty message: just release the Tandy.
            continue

        command = text.lower()
        if command == "/help":
            link.send(HELP_TEXT)
            continue
        if command in {"/new", "/newchat"}:
            history = [{"role": "system", "content": SYSTEM_PROMPT}]
            link.send("New chat created.")
            continue
        if command in {"/quit", "/exit"}:
            link.send("Goodbye.")
            return

        print(f"Tandy: {text}", file=sys.stderr)
        history.append({"role": "user", "content": text})
        try:
            answer = ask_model(client, model, history)
        except (OpenAIError, RuntimeError) as exc:
            history.pop()
            print(f"Model request failed: {exc}", file=sys.stderr)
            link.send("Model error. Check the host log.")
            continue
        history.append({"role": "assistant", "content": answer})
        link.send(answer)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Overlord Tandy (BASIC client).")
    parser.add_argument(
        "--cli",
        action="store_true",
        help="use the local terminal instead of the serial port",
    )
    parser.add_argument(
        "--device",
        default=SERIAL_DEVICE,
        help=f"serial device (default: {SERIAL_DEVICE})",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=SERIAL_BAUDRATE,
        help=f"baud rate (default: {SERIAL_BAUDRATE})",
    )
    args = parser.parse_args(argv)

    try:
        from openai import OpenAI

        config = load_api_config()
        client = OpenAI(api_key=config.key, base_url=config.url)
        if args.cli:
            run(CliLink(), client, config.model)
        else:
            with serial.Serial(
                args.device, args.baud, timeout=0.2, xonxoff=True
            ) as connection:
                connection.reset_input_buffer()
                print(
                    f"Listening on {args.device} at {args.baud} baud", file=sys.stderr
                )
                run(TandyLink(connection), client, config.model)
    except (RuntimeError, serial.SerialException) as exc:
        print(f"Overlord Tandy: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nOverlord Tandy stopped.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
