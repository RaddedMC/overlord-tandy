I have a Tandy 200 retro computer connected to this system over Serial. Help me build a TUI AI harness for it.

Implement the project in Python. Use the `pyserial` and `openai` libraries.
The project name is "Overlord Tandy". In the system prompt, be sure the AI is named Overlord Tandy.

## The computer:
- A retro Tandy 200. It has a 40x15 character display
- DO NOT display any characters outside of the ASCII charset. NO colours. It supports bell and clears, but nothing more.
- Make a serial connection to `/dev/ttyUSB0` at 1200 baud

## The application
- Leave a space for an ASCII art startup screen. Disply that at the start of the program and clear it once all libraries are loaded and the client is ready to work.
- When the LLM is thinking, be sure to display a `Thinking...` animation so that the model output doesn't explode the limited display space.
- Implement a slash-command system. So far, just have a slash command that creates a new chat.
- Leave space for a system prompt. Create a good sample system prompt where the AI introduces itself as "Overlord Tandy". Be sure it keeps its output brief.

## APIs
- Look for models and API keys in `/home/$user/ai_apis.json`
- The format for the API key file is the following:
```
{
    "apis": [
        {
            "name": "EagleCloud Ollama",
            "type": "openai",
            "url": "https://ollama-eagleserv.hippocampus-ruler.ts.net/v1",
            "key": "none",
            "choice-model": "gpt-oss:20b"
        },
        {
            "name": "EagleCloud ComfyUI",
            "type": "comfyui",
            "url": "http://eagleserv.hippocampus-ruler.ts.net:8188",
            "key": "none"
        }
    ]
}
```
  - Type is the type of API. For now, just use `openai`-type APIs. `name` is the server friendly name, `url` is the full url of the server to the OpenAI endpoint, `key` is the API bearer key, `choice-model` is the model string you should use with this endpoint.
  - These servers are compatible with the OpenAI API. Use the `openai` pip library and follow their documentation to create the AI integration.