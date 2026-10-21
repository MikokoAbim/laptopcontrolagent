# WhatsApp Skill

Guidance for navigating WhatsApp Desktop specifically.

## Opening WhatsApp
1. `open_application("whatsapp")`
2. `focus_application("WhatsApp")`
3. `get_screen_elements("WhatsApp")`

## Finding a contact
1. Click the `Edit` field tagged `[USE THIS TO SEARCH/FIND contacts or items]`, then `type_text(contact_name)`.
2. Call `get_screen_elements("WhatsApp")` again and click the matching contact `ListItem`.

## Sending a message
1. Click the `Edit` field tagged `[USE THIS TO TYPE AND SEND MESSAGES]`, then `type_text(message)`.
2. Call `send_whatsapp_message` to press enter and send. This requires human approval.

## Finding the user's profile image
- When asked to find or click the user's own profile image, always use `mouse_click` directly — do not search `get_screen_elements` for an "Image" element, WhatsApp does not expose the avatar with an accessible name.
- Target coordinates: **<TODO: fill in the x,y coordinates for your screen>** (typically the circular avatar in the top-left of the WhatsApp title bar).
