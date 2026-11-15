# Overlord Tandy

An ASCII-only AI terminal for a Tandy 200 over serial.

## Setup

```sh
python3 -m pip install -r requirements.txt
python3 overlord_tandy.py
```

The program reads the first `openai`-type endpoint with a `choice-model` from
`/home/$USER/ai_apis.json`, then connects to `/dev/ttyUSB0` at 1200 baud.

To run it directly in your local terminal instead, use:

```sh
python3 overlord_tandy.py --cli
```

Type `/new` to clear the conversation. `/quit` exits the program.
