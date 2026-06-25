"""Open Interpreter competitor run #2 — improved instructions.

Run #1 failed because OI tried template-matching a nonexistent search_bar image,
then blind-clicked (200,150) and falsely claimed success. This run forces it to
LOOK first (screenshot), reason from what it actually sees, and verify.
"""
import os
from interpreter import interpreter

interpreter.llm.model = "gemini/gemini-2.5-pro"
interpreter.llm.api_key = os.environ["GEMINI_API_KEY"]
interpreter.llm.context_window = 100000
interpreter.llm.supports_vision = True
interpreter.os = True
interpreter.auto_run = True
interpreter.verbose = False

TASK = (
    "Operate the already-open WeChat desktop app on this Mac to send a message. "
    "IMPORTANT METHOD: First take a screenshot and actually LOOK at it. Do NOT use "
    "template-matching against image files that don't exist. Use pyautogui to click "
    "based on what you SEE in the screenshot. "
    "Steps: (1) screenshot, (2) find and click WeChat's search box near the top-left, "
    "(3) type 文件传输助手 and press Enter to open that chat, (4) click the message input "
    "box at the bottom, (5) type EXACTLY: 今天下午3点开会，请准时 (6) press Enter to send. "
    "(7) Take another screenshot and VERIFY the message bubble actually appears in the "
    "chat before claiming success. If you cannot verify it, say 'NOT VERIFIED' — do not "
    "claim success without proof. Message nobody else."
)

try:
    for _ in interpreter.chat(TASK, display=False, stream=True):
        pass
    print("=== OI RUN2 FINISHED ===")
    for m in interpreter.messages[-8:]:
        print(f"[{m.get('role')}/{m.get('type')}] {str(m.get('content'))[:280]}")
except Exception as ex:
    print("=== OI RUN2 ERROR ===", repr(ex)[:400])
