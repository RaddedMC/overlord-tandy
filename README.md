# Overlord Tandy

Since Sam Altman is stealing all our RAM, we built an AI agent to run on a Tandy 200 from 1984 -- a system with 40 KB of RAM!

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

## Commands
- `/new`: Clear the conversation history and start a new chat
- `/quit`: Exit the program