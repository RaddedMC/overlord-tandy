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
CONFIG_PATH = Path.home() / "ai_apis.json"

# Replace this placeholder with a compact ASCII startup design if desired.
STARTUP_SCREEN = (
    "  OVERLORD TANDY                        \n"
    "  Now loading...       #                \n"
    "                      ##                \n"
    "                 #   # #                \n"
    "                # # #   #               \n"
    "               #   #    #               \n"
    "###########   #          #    ##########\n"
    "          #  #            #  #          \n"
    "          #  #            # #           \n"
    "           ##              #            \n"
    "           #                            \n"
    "                    github.com/raddedmc \n"
    "                              /jarboer  \n"
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


def display_lines(text: str, width: int = DISPLAY_WIDTH) -> list[str]:
    """Wrap text into display-width ASCII lines."""
    safe = ascii_text(text).replace("\r", "")
    lines: list[str] = []
    for source_line in safe.split("\n"):
        lines.extend(wrap(source_line, width=width, replace_whitespace=False) or [""])
    return lines


class TandyDisplay:
    """Minimal 40x15 terminal renderer."""

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    def write(self, text: str) -> None:
        self.connection.write(ascii_text(text).encode("ascii"))

    def clear(self) -> None:
        self.write("\x1bE")  # Char: "ESC E"

    def render(self, text: str, bell: bool = False) -> None:
        lines = display_lines(text)[:DISPLAY_HEIGHT]
        self.write("\r\n".join(line[:DISPLAY_WIDTH] for line in lines))
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
        if bell:
            self.write("\x07")  # Char: "BEL"

    def startup(self) -> None:
        self.render(STARTUP_SCREEN)


def output(display: Any, text: str, bell: bool = False) -> None:
    """Send application output through the active display."""
    display.render(text, bell=bell)


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
        previous = frames[(index - 1) % len(frames)] if index else ""
        display.write("\b" * len(previous) + frames[index % len(frames)])
        index += 1
        stop.wait(0.35)


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
    output(display, "Overlord Tandy ready.\nType a message.\n/new starts a new chat.")

    while True:
        output(display, "Your turn.\n> ")
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
        output(display, answer, bell=True)
        time.sleep(1.5)


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
            display.clear()
            run(None, client, config.model, display=display, input_reader=read_cli_input)
        else:
            with serial.Serial(args.device, SERIAL_BAUDRATE, timeout=0.2) as connection:
                display = TandyDisplay(connection)
                display.clear()
                display.startup()
                config = load_api_config()
                client = make_client(config)
                display.clear()
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
