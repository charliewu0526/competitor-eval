"""T1 pilot task: send a WeChat message to a specific contact.

Domain #1 (closed-source desktop app). This is the single thinnest task used to
prove the pipeline. WeChat has no public API for desktop send -> a cloud agent
would GATE as cannot-reach; Vio and Simular operate the GUI directly.

End-state can't be read by a script (closed app), so the primary-goal assertion
is a human-verified flag dropped into the RunRecord context.
"""
import pathlib
from pipeline import objective as O
from pipeline import taskbank as TB

# X1: the task is now a directory under tasks/. meta.json is the single
# machine-readable source — TASK is loaded (and validated) from it rather than
# hardcoded here, so the .py and the bank can never drift apart.
TASK_DIR = pathlib.Path(__file__).resolve().parent / "T1-wechat-send-001"
TASK = TB.assert_valid(TASK_DIR)


def assertions():
    """Bind the task's concrete assertions to ctx keys an operator fills in."""
    return [
        O.manual_check("target contact received the exact message",
                       "msg_received", primary=True),
        O.manual_check("message text matches exactly (no typos)",
                       "text_exact", primary=True),
        O.manual_check("no other contact was messaged",
                       "no_collateral", primary=False),
    ]
