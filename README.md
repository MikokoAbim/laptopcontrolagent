# Laptop Control Agent

An LLM agent that controls a Windows laptop from natural-language requests.

- Built with LangChain and LangGraph, using models through OpenRouter.
- Reads on-screen elements with UI Automation (`pywinauto`).
- Clicks, types and presses keys with `pyautogui`.
- Uses a conditional-routing state graph with a human-approval node (`interrupt()`) that pauses before any message is sent.
- Loads on-demand skill files to make UI choices more deterministic.
- Uses native tools instead of an earlier MCP design, which added unnecessary overhead.

## Requirements

- Windows 10 or 11 (the tools are Windows-only).
- Python 3.10 or newer.
- An [OpenRouter](https://openrouter.ai) API key.
- WhatsApp Desktop, only for the WhatsApp flow.

## Setup

- Create and activate a virtual environment:

  ```powershell
  python -m venv .venv
  .\.venv\Scripts\Activate.ps1
  ```

- Install dependencies:

  ```powershell
  pip install -r requirements.txt
  ```

- Create your env file and set `OPENROUTER_API_KEY` in it:

  ```powershell
  Copy-Item .env.example .env
  ```

## Run

- Start the agent from the repo root, as a module:

  ```powershell
  python -m agent.main
  ```

- Ensure whatsapp is open beforehand because the open application command doesnt work yet. when the application is open then the script works

- Type a request at the `You >` prompt, for example: `open notepad and type hello`.
- Do not run `python agent/main.py`; the `agent` package import fails that way.
- Before a WhatsApp message is sent, the agent asks `approve yes/no ?`. Only `yes` sends it.
- To abort a runaway action, move the mouse to the top-left corner of the screen (`pyautogui` failsafe).

## Configuration

Set these in `.env`:

- `OPENROUTER_API_KEY`: required.
- `MODEL`: any OpenRouter model that supports tool calling (default `deepseek/deepseek-chat-v3.1`).
- `TEMPERATURE`: default `0.6`.
- `MAX_TOKENS`: default `4096`.

## How it works

- Graph nodes: `agent`, `automation_tools`, `skill_tools`, `approval_node`, `sensitive_tools`.
- After each model call, the router sends tool calls to:
  - `skill_tools` for `load_skill`.
  - `automation_tools` for open, focus, read, click, type and key tools.
  - `approval_node` for `send_whatsapp_message`, which runs only if approved.
- Skills live in `agent/skills/`. To add one, create a `.md` file there and register it in `SKILL_CATALOG` in `agent/main.py`.

## Known limitations

- `agent/skills/whatsapp_skill.md` has a TODO for your profile-image screen coordinates. Fill them in for your display.
- Only the final send is approval-gated. Typing into the message box is not.
- `SKILLS_DIR` in `.env` is not used; skills always load from `agent/skills/`.

## Legacy files

These belong to the replaced MCP design. They are not part of the run path and need packages not in `requirements.txt` (such as `mcp`, `groq`, `ollama`):

- `chat_app.py`, `chat_app_gemma4.py`, `chat_app_gemma4_backup.py`
- `mcp_client.py`, `mcp_server.py`
- `test_vision_ai.py`
