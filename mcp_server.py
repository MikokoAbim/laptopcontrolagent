from mcp.server.fastmcp import FastMCP
from duckduckgo_search import DDGS
import pyperclip
from pywinauto import Desktop
import subprocess
import platform
import pyautogui
import time
import ctypes
import os

mcp = FastMCP("mcp-with-agent-demo")

# Use absolute path based on script location
# 1. __file__ = chat_app.py location

# 2. abspath(__file__) = 
#   E:\AiAgentsGood\AiAgents\mcp_with_agent_test\chat_app.py

# 3. dirname(abspath(__file__)) = removes filename
#   E:\AiAgentsGood\AiAgents\mcp_with_agent_test

# 4. join(script_dir, "mcp_server.py") = adds new filename
#   E:\AiAgentsGood\AiAgents\mcp_with_agent_test\mcp_server.py
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) 
DOCS_PATH = os.path.join(SCRIPT_DIR, "docs")

os.makedirs(DOCS_PATH, exist_ok=True)
pyautogui.FAILSAFE = True  # move mouse to top-left corner to abort

@mcp.tool(
        name="open_application",
        description="Open an application by name on user system"
)
def open_application(app_name: str) -> str:
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.Popen(f"start {app_name}", shell = True)
        time.sleep(2.5)
        return f"Opened {app_name}"
    except Exception as e:
        return f"Failed to open application: {e}"

@mcp.tool(name="wait", description="Wait N seconds for an app or animation to finish loading")
def wait(seconds: float) -> str:
    time.sleep(seconds)
    return f"Waited {seconds}s"

@mcp.tool(
    name = "focus_application",
    description ="Bring an application window to the front so it is ready to interact with. "
                "Use this after open_application. app_title example: 'WhatsApp'"
)
def focus_application(app_title: str) -> str:
    try:
        desktop = Desktop(backend="uia")
        windows = desktop.windows(title_re=f".*{app_title}.*")

        if not windows:
            return f"No windows called '{app_title}'"
        
        window = windows[0]
        hwnd = window.handle

        # only restore if actually minimized, never touch a maximized window
        if window.is_minimized():
            window.restore()
            time.sleep(0.3)

        # bring to front without changing window state
        ctypes.windll.user32.SetForegroundWindow(hwnd)
        ctypes.windll.user32.BringWindowToTop(hwnd)

        time.sleep(0.5)
        return f"Focused: {window.window_text()}"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool(
        name = "get_screen_elements",
        description = "Get all interactive UI elements currently on screen with their coordinates."
                        "Returns buttons, inputs, text fields etc with x,y coordinates"
)
def get_screen_elements(app_title: str = "") -> str:
    """
    Reads the accessibility tree of the focused window.
    app_title: optional window title to target e.g 'WhatsApp'
    """
    desktop = Desktop(backend="uia")

    if app_title:
        windows = desktop.windows(title_re = f".*{app_title}.*")
        if not windows:
            return f"Sorry there are no windows called {app_title}"
        window = windows[0]
    else:
        window = desktop.get_active()

    seen = set()
    elements = []

    skip_names = {
        "Minimize", "Maximise", "Maximize", "Minimise", 
        "Close", "Restore", "Untitled"
    }

    # keywords that hint a search field
    search_hints = {"search", "find", "filter", "look_up"}

    # keywords that hint an Edit field is a message/compose box
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
                # round to nearest 5px so 1px-ff duplicates get caught
                cx_rounded = round(cx/5) * 5
                cy_rounded = round(cy/5) * 5

                key = (element_name, element_type, cx_rounded, cy_rounded)
                if key in seen:
                    continue
                seen.add(key)

                # Add a role hint for Edit fields so the model understands intent
                role_hint = ""
                if element_type == "Edit":
                    element_name_lower = element_name.lower()
                    if any(search_hint in element_name_lower for search_hint in search_hints):
                        role_hint = " [USE THIS TO SEARCH/FIND contacts or items] "
                    elif any(message_hint in element_name_lower for message_hint in message_hints):
                        role_hint = " [USE THIS TO TYPE AND SEND MESSAGES] "
                    else:
                        role_hint = " [test input field] "
                            # Store as tuple during loop
                elements.append((element_type, element_name, cx, cy, role_hint))
        except:
            continue

    if not elements:
        return "There are no interactive element found in this window"
    
    # Sort: put Serarch Edit fields first, then other Edits then Buttons, then rest
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

    lines = [
        f"{etype} '{ename}'{hint} at x={cx} y={cy}"
        for etype, ename, cx, cy, hint in elements[:40]
    ]

    # Model would now see
    # Edit 'Search' [USE THIS TO SEARCH/FIND contacts or items] at x=200 y=150
    # Edit 'Message' [USE THIS TO TYPE AND SEND messages] at x=500 y=600
    # Button 'New chat' at x=400 y=50
    
    return "\n".join(lines)


@mcp.tool(
        name= "mouse_click",
        description="Click at x,y coordinates on screen"
)
def mouse_click(x: int, y
                :int, button: str = "left") -> str:
    pyautogui.click(x, y, button=button, duration=0.5)
    time.sleep(0.4)
    return f"Clicked at ({x}, {y})"


# @mcp.tool(
#         name="type_text",
#         description="Type text at the current cursor position. "
# )
# def type_text(text: str) -> str:
#     pyautogui.typewrite(text, interval=0.05)
#     return f"Typed: {text}"

@mcp.tool(
        name="type_text",
        description="Type text at the current cursor position. "
)
def type_text(text: str) -> str:
    pyperclip.copy(text)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.3)
    return f"Typed: {text}"


@mcp.tool(
    name = "press_key",
    description  = "Press a keyboard key or combo. "
                    "Exmaples: 'enter', 'escape', 'ctrl_f', 'ctrl+a' etc"
)
def press_key(key: str) -> str:
    if "+" in key:
        pyautogui.hotkey(*key.split("+"))
    else:
        pyautogui.press(key)
    time.sleep(0.3)
    return f"Pressed {key} key"

# @mcp.tool(
#         name = "web_search",
#         description = "Search the web and return text results without opening a browser"
# )
# def web_search(query: str, max_results_returned: int = 5) -> str:
#     """Searches the web using DuckDuckGo"""

#     try:
#         with DDGS() as ddgs:
#             results = list(ddgs.text(query, max_results = max_results_returned))

#             if not results:
#                 return "No results found"
            
#             output = []
#             for i, r in enumerate(results, 1):
#                 output.append(f"{i}. {r['title']}\n {r['href']}\n {r['body']}\n")
            
#             # output = [
#             #    "1. Title A\nlink A\nsnippet A",
#             #    "2. Title B\nlink B\nsnippet B"
#             # ]
#             # goes from that to this as one string
#             # 1. Title A
#             #    link A
#             #    snippet A

#             # 2. Title B
#             #    link B
#             #    snippet B

#             return "\n".join(output)
#     except Exception as e:
#         return f"Search failed: {str(e)}"


if __name__ == "__main__":
    mcp.run(transport="stdio")