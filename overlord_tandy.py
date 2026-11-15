"""Overlord Tandy: a small ASCII-only AI terminal for a Tandy 200."""

from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from textwrap import wrap
from typing import TYPE_CHECKING, Any, Callable, TextIO

import serial

if TYPE_CHECKING:
    from openai import OpenAI

DISPLAY_WIDTH = 40
DISPLAY_HEIGHT = 15
SERIAL_DEVICE = "/dev/ttyUSB0"
SERIAL_BAUDRATE = 1200
CLEAR_DELAY = 0.2  # Seconds the Tandy needs to clear its LCD before taking more text.
# The Tandy only buffers 64 received bytes, so send in small chunks no faster
# than it can draw them, even when the port itself is faster (e.g. an emulator pty).
WRITE_CHUNK = 16
CHAR_DELAY = 1 / 100  # Seconds per character, a little slower than 1200 baud.
CONFIG_PATH = Path.home() / "ai_apis.json"

# Replace this placeholder with a compact ASCII startup design if desired.
STARTUP_SCREEN = (
    "  OVERLORD TANDY       #                \n"
    "                      ##                \n"
    "                 #   # #                \n"
    "                # # #   #               \n"
    "               #   #    #               \n"
    "###########   #          #    ##########\n"
    "          #  #            #  #          \n"
    "          #  #            # #           \n"
    "           ##              #            \n"
    "           #            Now loading...  \n"
)


SYSTEM_PROMPT = """You are Overlord Tandy, a helpful AI running on a Tandy 200.
Reply in plain ASCII only. Keep every reply brief: at most 5 short lines,
with no line longer than 40 characters. Do not use markdown, colors, emojis,
or characters outside the ASCII charset."""


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


def ascii_text(text: str) -> str:
    """Return text safe for the Tandy's ASCII-only display."""
    return text.encode("ascii", "replace").decode("ascii").replace("\t", " ")


# Wrap one short of the full width: a full-width line makes the Tandy's cursor
# wrap on its own, so the line break after it would leave a blank row.
def display_lines(text: str, width: int = DISPLAY_WIDTH - 1) -> list[str]:
    """Wrap text into display-width ASCII lines."""
    safe = ascii_text(text).replace("\r", "")
    lines: list[str] = []
    for source_line in safe.split("\n"):
        lines.extend(wrap(source_line, width=width, replace_whitespace=False) or [""])
    return lines


def display_pages(text: str, height: int = DISPLAY_HEIGHT - 1) -> list[str]:
    """Split text into screens, leaving the last row free for a prompt."""
    lines = display_lines(text)
    return ["\n".join(lines[i : i + height]) for i in range(0, len(lines), height)]


class TandyDisplay:
    """Minimal 40x15 terminal renderer."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.row = 0  # Lines currently used on screen.

    def write(self, text: str) -> None:
        data = ascii_text(text).encode("ascii")
        for start in range(0, len(data), WRITE_CHUNK):
            chunk = data[start : start + WRITE_CHUNK]
            self.connection.write(chunk)
            self.connection.flush()
            time.sleep(len(chunk) * CHAR_DELAY)

    def clear(self) -> None:
        self.write("\x1bE")  # Char: "ESC E"
        self.connection.flush()
        time.sleep(CLEAR_DELAY)
        self.row = 0

    def move_to_row(self, row: int) -> None:
        self.write(f"\x1bY{chr(32 + row)}{chr(32)}")  # Char: "ESC Y <row> <col>"

    def render(self, text: str, bell: bool = False, clear: bool = True) -> None:
        lines = [line[:DISPLAY_WIDTH] for line in display_lines(text)][:DISPLAY_HEIGHT]
        if clear or self.row == 0:
            self.clear()
            self.write("\r\n".join(lines))
        elif self.row + len(lines) <= DISPLAY_HEIGHT:
            self.write("\r\n" + "\r\n".join(lines))
        else:
            # Not enough room: overwrite the bottom lines instead of scrolling.
            self.move_to_row(DISPLAY_HEIGHT - len(lines))
            self.write("\r\n".join("\x1bK" + line for line in lines))  # Char: "ESC K"
        self.row = min(self.row + len(lines), DISPLAY_HEIGHT)
        if bell:
            self.write("\x07")  # Char: "BEL"

    def startup(self) -> None:
        self.render(STARTUP_SCREEN)


class CliDisplay:
    """Renderer for a normal terminal."""

    def clear(self) -> None:
        print("\x1b[2J\x1b[H", end="", flush=True)  # Char: "ESC[2J ESC[H"

    def write(self, text: str) -> None:
        print(ascii_text(text), end="", flush=True)

    def render(self, text: str, bell: bool = False) -> None:
        self.clear()
        self.write(text)
    def render(self, text: str, bell: bool = False, clear: bool = True) -> None:
        if clear:
            self.clear()
        else:
            print()
        print(ascii_text(text), end="", flush=True)
        if bell:
            self.write("\x07")  # Char: "BEL"

    def startup(self) -> None:
        self.render(STARTUP_SCREEN)


def output(display: Any, text: str, bell: bool = False, clear: bool = True) -> None:
    """Send application output through the active display."""
    display.render(text, bell=bell, clear=clear)


def make_client(config: ApiConfig) -> OpenAI:
    """Create the OpenAI client for an OpenAI-compatible endpoint."""
    from openai import OpenAI

    return OpenAI(api_key=config.key, base_url=config.url)


def ask_model(client: OpenAI, model: str, messages: list[dict[str, str]]) -> str:
    """Request one concise response from the configured model."""
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.4,
        max_tokens=512,
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
    return ascii_text(content).strip()


def ask_model_until_complete(
    client: OpenAI,
    model: str,
    messages: list[dict[str, str]],
    cancel: threading.Event,
) -> str | None:
    """Run a model request in the background so Ctrl-C can cancel its output."""
    from openai import OpenAIError

    result: dict[str, Any] = {}

    def request() -> None:
        try:
            result["answer"] = ask_model(client, model, messages)
        except (OpenAIError, RuntimeError) as exc:
            result["error"] = exc

    request_thread = threading.Thread(target=request, daemon=True)
    request_thread.start()
    while request_thread.is_alive():
        if cancel.wait(0.1):
            return None
    request_thread.join()
    if "error" in result:
        raise result["error"]
    return result["answer"]


def watch_serial_cancel(
    connection: Any, cancel: threading.Event, stop: threading.Event
) -> None:
    """Watch for Ctrl-C from the Tandy while a model request is running."""
    while not stop.is_set():
        if connection.read(1) == b"\x03":
            cancel.set()
            return


def thinking(display: Any, stop: threading.Event) -> None:
    """Animate a small status message while the model request is running."""
    frames = (".", "..", "...")
    index = 0
    display.clear()
    display.write("Thinking")
    while not stop.is_set():
        output(display, frames[index % len(frames)])
        index += 1
        stop.wait(0.5)


def read_input(connection: Any) -> str:
    """Read one line from the Tandy, which sends input one character at a time."""
    characters: list[str] = []
    while True:
        raw = connection.read(1)
        if not raw:
            continue
        character = raw.decode("ascii", "replace")
        if character in "\r\n":
            connection.write(b"\r\n")
            return "".join(characters).strip()
        if character in "\b\x7f":  # Char: "DEL"
            if characters:
                characters.pop()
                connection.write(b"\b \b")
            continue
        if character == "\x03":  # Char: "ETX"
            raise KeyboardInterrupt
        if 32 <= ord(character) <= 126:
            characters.append(character)
            connection.write(raw)


def read_cli_input() -> str:
    """Read one user message from the local terminal."""
    return input().strip()


def run(
    connection: Any | None,
    client: OpenAI,
    model: str,
    log: TextIO = sys.stderr,
    display: Any | None = None,
    input_reader: Callable[[], str] | None = None,
) -> None:
    """Run the interactive chat loop."""
    from openai import OpenAIError

    if display is None:
        if connection is None:
            raise RuntimeError("A display or serial connection is required.")
        display = TandyDisplay(connection)
    if input_reader is None:
        if connection is None:
            input_reader = read_cli_input
        else:
            input_reader = lambda: read_input(connection)
    history: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]

    input_reader()  # Allow user to choose when to go next
    display.clear()
    output(display, "Overlord Tandy ready.\nType a message.\n/new starts a new chat.\nPress enter to start.")

    input_reader() # Allow user to choose when to go next

    while True:
        output(display, "You > ")
        try:
            user_text = input_reader()
        except EOFError:
            output(display, "Goodbye.")
            return
        except (OSError, UnicodeError) as exc:
            raise RuntimeError(f"Input failed: {exc}") from exc
        if not user_text:
            continue
        if user_text.lower() in {"/new", "/newchat"}:
            history = [{"role": "system", "content": SYSTEM_PROMPT}]
            output(display, "New chat created.")
            time.sleep(0.8)
            continue
        if user_text.lower() in {"/quit", "/exit"}:
            output(display, "Goodbye.")
            return

        history.append({"role": "user", "content": user_text})
        stop = threading.Event()
        animation = threading.Thread(target=thinking, args=(display, stop), daemon=True)
        animation.start()
        cancel = threading.Event()
        watch_stop = threading.Event()
        watcher: threading.Thread | None = None
        previous_signal_handler: Any = None
        if connection is None:
            previous_signal_handler = signal.getsignal(signal.SIGINT)

            def cancel_from_signal(_signum: int, _frame: Any) -> None:
                cancel.set()

            signal.signal(signal.SIGINT, cancel_from_signal)
        else:
            watcher = threading.Thread(
                target=watch_serial_cancel,
                args=(connection, cancel, watch_stop),
                daemon=True,
            )
            watcher.start()
        answer: str | None = None
        request_error: Exception | None = None
        try:
            answer = ask_model_until_complete(client, model, history, cancel)
        except (OpenAIError, RuntimeError) as exc:
            history.pop()
            print(f"Model request failed: {exc}", file=log)
            request_error = exc
        finally:
            watch_stop.set()
            if watcher is not None:
                watcher.join()
            if connection is None and previous_signal_handler is not None:
                signal.signal(signal.SIGINT, previous_signal_handler)
            stop.set()
            animation.join()
        display.clear()
        if request_error is not None:
            output(display, "Model error.\nCheck the host log.")
            time.sleep(1.0)
            continue
        if answer is None:
            history.pop()
            output(display, "Stopped.")
            time.sleep(0.8)
            continue
        history.append({"role": "assistant", "content": answer})
        display.clear()
        pages = display_pages(answer + "\n\nDismiss: Press enter.")
        for number, page in enumerate(pages, start=1):
            output(display, page, bell=number == 1)
            if number < len(pages):
                output(display, f"More ({number}/{len(pages)}): Press enter.", clear=False)
                input_reader()

        input_reader() # Allow user to choose when to go next


def main(argv: list[str] | None = None) -> int:
    """Load dependencies and configuration, then start the terminal."""
    parser = argparse.ArgumentParser(description="Run Overlord Tandy.")
    parser.add_argument(
        "--cli",
        action="store_true",
        help="use the local terminal instead of the Tandy serial connection",
    )
    parser.add_argument(
        "--device",
        default=SERIAL_DEVICE,
        help=f"serial device for the Tandy connection (default: {SERIAL_DEVICE})",
    )
    args = parser.parse_args(argv)

    try:
        if args.cli:
            display = CliDisplay()
            display.clear()
            display.startup()
            config = load_api_config()
            client = make_client(config)
            run(None, client, config.model, display=display, input_reader=read_cli_input)
        else:
            with serial.Serial(args.device, SERIAL_BAUDRATE, timeout=0.2, xonxoff=True) as connection:
                display = TandyDisplay(connection)
                display.clear()
                display.startup()
                config = load_api_config()
                client = make_client(config)
                run(connection, client, config.model, display=display)
    except (RuntimeError, serial.SerialException) as exc:
        print(f"Overlord Tandy: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nOverlord Tandy stopped.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
