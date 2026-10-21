# Desktop Navigation Skill

Guidance for opening, focusing, and interacting with any desktop application via UI Automation.

## Standard flow
1. `open_application(app_name)` — only if the app is not already open.
2. `focus_application(app_title)` — brings the window to the foreground. Skip this and step 1 if the user refers to "this page/screen/current window" or gives no app name; instead call `get_screen_elements` with no arguments.
3. `get_screen_elements(app_title)` — reads the UI Automation tree and returns interactive elements with coordinates.

## Rules
- One tool call per turn. Always wait for the result before acting again.
- Call `get_screen_elements` again after every `mouse_click` — coordinates and elements change once the screen updates.
- Never reuse coordinates from a previous `get_screen_elements` call.
- To search or filter, click the `Edit` field tagged `[USE THIS TO SEARCH/FIND contacts or items]`, never a `Button`.
