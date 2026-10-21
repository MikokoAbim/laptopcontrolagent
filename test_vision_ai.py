import ollama
import base64
import pyautogui
import io
import screeninfo
import asyncio

monitors = screeninfo.get_monitors()
primary = next(m for m in monitors if m.is_primary)

screenshot = pyautogui.screenshot(region=(
    primary.x,
    primary.y,
    primary.width,
    primary.height
))

screenshot = screenshot.resize((800, 450))

buffer = io.BytesIO()
screenshot.save(buffer, format="JPEG", quality=70)
b64 = base64.b64encode(buffer.getvalue()).decode()


async def main():
    response = await asyncio.to_thread(
        ollama.chat,
        model="llava:7b",
        messages=[
            {
                "role": "user",
                "content": "Extract UI structure for automation: 1. Panels 2. Buttons (name + position) 3. Text elements 4. Notifications/unread indicators 5. Input fields Do NOT interpret meaning. Do NOT guess application type.",
                "images": [b64]
            }
        ]
    )

    print(response["message"]["content"])


asyncio.run(main())