"""T1 pilot task: send a WeChat message to a specific contact.

Domain #1 (closed-source desktop app). This is the single thinnest task used to
prove the pipeline. WeChat has no public API for desktop send -> a cloud agent
would GATE as cannot-reach; Vio and Simular operate the GUI directly.

End-state can't be read by a script (closed app), so the primary-goal assertion
is a human-verified flag dropped into the RunRecord context.
"""
from pipeline.schema import TaskSpec
from pipeline import objective as O

TASK = TaskSpec(
    task_id="T1-wechat-send-001",
    domain="1",
    app="wechat",
    prompt=("Open WeChat and send the exact message '今天下午3点开会，请准时' "
            "to the contact named '文件传输助手'. Do not message anyone else."),
    core_assertions=[
        "primary: target contact received the exact message (human-verified)",
        "primary: message text matches exactly, no typos",
        "no destructive side-effects: no other contact was messaged (human-verified)",
    ],
    expects_file=False,
)


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
