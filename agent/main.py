from pathlib import Path
from datetime import datetime
import time
import ctypes
import platform
import subprocess

import pyautogui
import pyperclip
from pywinauto import Desktop

from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from agent import config
from langgraph.graph import MessagesState, END, StateGraph, START
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage, HumanMessage
from langgraph.types import interrupt, Command
from langgraph.prebuilt import ToolNode
from langgraph.checkpoint.memory import InMemorySaver
import asyncio

pyautogui.FAILSAFE = True

SKILLS_DIRECTORY = Path(__file__).parent / "skills"

SKILL_CATALOG = {
    "desktop_navigation_skill": "Guidance for opening, focusing, and reading UI elements before acting on any desktop app.",
    "whatsapp_skill": "Guidance for finding contacts, sending messages, and locating the user's profile image in WhatsApp.",
}


def read_skill_file(name: str) -> str:
    return (SKILLS_DIRECTORY / f"{name}.md").read_text(encoding="utf-8").strip()


@tool
def load_skill(skill_name: str) -> str:
    """Load the full instructions for a named skill from the catalog"""
    if skill_name not in SKILL_CATALOG:
        raise ValueError(f"Unknown skill: {skill_name}. Available: {list(SKILL_CATALOG)}")
    return read_skill_file(skill_name)


@tool
def open_application(app_name: str) -> str:
    """Open an application by name on the user's system"""
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.Popen(f"start {app_name}", shell=True)
        time.sleep(2.5)
        return f"Opened {app_name}"
    except Exception as e:
        return f"Failed to open application: {e}"


@tool
def wait(seconds: float) -> str:
    """Wait N seconds for an app or animation to finish loading"""
    time.sleep(seconds)
    return f"Waited {seconds}s"


@tool
def focus_application(app_title: str) -> str:
    """Bring an application window to the front so it is ready to interact with. Use after open_application. app_title example: 'WhatsApp'"""
    try:
        desktop = Desktop(backend="uia")
        windows = desktop.windows(title_re=f".*{app_title}.*")

        if not windows:
            return f"No windows called '{app_title}'"

        window = windows[0]
        hwnd = window.handle

        if window.is_minimized():
            window.restore()
            time.sleep(0.3)

        ctypes.windll.user32.SetForegroundWindow(hwnd)
        ctypes.windll.user32.BringWindowToTop(hwnd)

        time.sleep(0.5)
        return f"Focused: {window.window_text()}"
    except Exception as e:
        return f"Error: {e}"


@tool
def get_screen_elements(app_title: str = "") -> str:
    """Get all interactive UI elements currently on screen with their coordinates. app_title: optional window title to target e.g 'WhatsApp'"""
    desktop = Desktop(backend="uia")

    if app_title:
        windows = desktop.windows(title_re=f".*{app_title}.*")
        if not windows:
            return f"Sorry there are no windows called {app_title}"
        window = windows[0]
    else:
        window = desktop.get_active()

    seen = set()
    elements = []

    skip_names = {"Minimize", "Maximise", "Maximize", "Minimise", "Close", "Restore", "Untitled"}
    search_hints = {"search", "find", "filter", "look_up"}
    message_hints = {"message", "type", "write", "compose", "reply", "chat"}

    for element in window.descendants():
        try:
            element_name = element.element_info.name
            element_type = element.element_info.control_type
            element_rectangle = element.rectangle()

            if element_type in ("Button", "Edit", "Text", "ListItem", "MenuItem", "Hyperlink", "DataItem") and element_name:
                cx = (element_rectangle.left + element_rectangle.right) // 2
                cy = (element_rectangle.top + element_rectangle.bottom) // 2

                if cx == 0 and cy == 0:
                    continue
                if element_name in skip_names:
                    continue

                cx_rounded = round(cx / 5) * 5
                cy_rounded = round(cy / 5) * 5
                key = (element_name, element_type, cx_rounded, cy_rounded)
                if key in seen:
                    continue
                seen.add(key)

                role_hint = ""
                if element_type == "Edit":
                    element_name_lower = element_name.lower()
                    if any(h in element_name_lower for h in search_hints):
                        role_hint = " [USE THIS TO SEARCH/FIND contacts or items] "
                    elif any(h in element_name_lower for h in message_hints):
                        role_hint = " [USE THIS TO TYPE AND SEND MESSAGES] "
                    else:
                        role_hint = " [test input field] "
                elements.append((element_type, element_name, cx, cy, role_hint))
        except Exception:
            continue

    if not elements:
        return "There are no interactive element found in this window"

    def sort_key(e):
        etype, ename, cx, cy, hint = e
        if etype == "Edit" and "SEARCH" in hint:
            return 0
        if etype == "Edit":
            return 1
        if etype == "Button":
            return 2
        return 3

    elements.sort(key=sort_key)

    lines = [f"{etype} '{ename}'{hint} at x={cx} y={cy}" for etype, ename, cx, cy, hint in elements[:40]]
    return "\n".join(lines)


@tool
def mouse_click(x: int, y: int, button: str = "left") -> str:
    """Click at x,y coordinates on screen"""
    pyautogui.click(x, y, button=button, duration=0.5)
    time.sleep(0.4)
    return f"Clicked at ({x}, {y})"


@tool
def type_text(text: str) -> str:
    """Type text at the current cursor position."""
    pyperclip.copy(text)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.3)
    return f"Typed: {text}"


@tool
def press_key(key: str) -> str:
    """Press a keyboard key or combo. Examples: 'enter', 'escape', 'ctrl+a' etc"""
    if "+" in key:
        pyautogui.hotkey(*key.split("+"))
    else:
        pyautogui.press(key)
    time.sleep(0.3)
    return f"Pressed {key} key"


@tool
def get_local_time() -> str:
    """Get the current local computer time."""
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


@tool
def send_whatsapp_message(message: str) -> str:
    """Type a message into the currently focused WhatsApp message box and send it. Requires human approval"""
    pyperclip.copy(message)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.3)
    pyautogui.press("enter")
    time.sleep(0.3)
    return f"Sent message: {message}"


skill_tools = [load_skill]
automation_tools = [open_application, wait, focus_application, get_screen_elements, mouse_click, type_text, press_key, get_local_time]
sensitive_tools = [send_whatsapp_message]
all_tools = skill_tools + automation_tools + sensitive_tools

llm = ChatOpenAI(
    model=config.MODEL_NAME,
    base_url=config.OPENROUTER_BASE_URL,
    api_key=config.require_api_key(),
    temperature=config.TEMPERATURE,
    max_completion_tokens=config.MAX_TOKENS,
).bind_tools(all_tools)

catalog_lines = "\n".join(f"- {name}: {desc}" for name, desc in SKILL_CATALOG.items())

SYSTEM_PROMPT = (
    "You are a desktop automation assistant. "
    "Use open_application/focus_application/get_screen_elements to navigate apps. "
    "Use mouse_click, type_text and press_key to interact with UI elements. "
    "Use send_whatsapp_message only to send a typed message in WhatsApp. "
    "If a tool call fails, acknowledge the error and ask the user to try again.\n\n"
    "You have access to skills with more detailed guidance. Call load_skill "
    "with the skill name if one looks relevant before proceeding. Available skills:\n"
    f"{catalog_lines}"
)


async def call_model(state: MessagesState):
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    try:
        response = await llm.ainvoke(messages)
    except Exception as exc:
        return {"messages": [AIMessage(content=f"Sorry, I encountered an error calling the model: {exc}")]}
    return {"messages": [response]}


def route_after_agent(state: MessagesState):
    last_message = state["messages"][-1]
    if not last_message.tool_calls:
        return END

    requested_tool_name = last_message.tool_calls[0]["name"]

    if requested_tool_name == "load_skill":
        return "skill_tools"

    if requested_tool_name in {t.name for t in automation_tools}:
        return "automation_tools"

    if requested_tool_name == "send_whatsapp_message":
        return "approval_node"

    raise ValueError(f"Unsupported tool requested: {requested_tool_name}")


async def approval_node(state: MessagesState):
    last_message = state["messages"][-1]
    first_tool_call = last_message.tool_calls[0]

    tool_info = {"tool_name": first_tool_call["name"], "tool_args": first_tool_call["args"]}
    decision = interrupt(tool_info)

    if decision == "approve":
        return Command(goto="sensitive_tools")

    rejection_message = [
        ToolMessage(content="Tool access was denied, therefore operation cant happen", tool_call_id=first_tool_call["id"])
    ]
    return Command(goto="agent", update={"messages": rejection_message})


def build_graph():
    graph = StateGraph(MessagesState)

    graph.add_node("agent", call_model)
    graph.add_node("approval_node", approval_node)
    graph.add_node("automation_tools", ToolNode(automation_tools, handle_tool_errors=True))
    graph.add_node("sensitive_tools", ToolNode(sensitive_tools, handle_tool_errors=True))
    graph.add_node("skill_tools", ToolNode(skill_tools, handle_tool_errors=True))

    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route_after_agent)
    graph.add_edge("automation_tools", "agent")
    graph.add_edge("sensitive_tools", "agent")
    graph.add_edge("skill_tools", "agent")

    return graph.compile(checkpointer=InMemorySaver())


async def main():
    app = build_graph()
    thread_id = "chat-1"

    while True:
        user_input = input("You > ")

        if not user_input:
            continue

        run_config = {"configurable": {"thread_id": thread_id}}
        response = await app.ainvoke({"messages": [HumanMessage(content=user_input)]}, run_config)
        state = app.get_state(run_config)

        while state.next:
            if state.tasks and state.tasks[0].interrupts:
                interruption = state.tasks[0].interrupts[0].value
                print(f"The following sensitive tool needs your approval: {interruption['tool_name']}")

                user_decision = "approve" if input("approve yes/no ?").strip().lower() == "yes" else "denied"

                response = await app.ainvoke(Command(resume=user_decision), run_config)
                state = app.get_state(run_config)
            else:
                break

        print(f"Jarvis > {response['messages'][-1].content}")


if __name__ == "__main__":
    asyncio.run(main())
