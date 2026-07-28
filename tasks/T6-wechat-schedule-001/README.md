# T6-wechat-schedule-001

Capability domain: **wechat-im** · Task nature: **scheduled**

## Scenario
Every workday at 18:00, send the message '今日工作已完成，日报已更新' to the contact '文件传输助手'. Set this up to run on schedule today.

## Notes
This task is part of the auto-seeded task bank (scripts/gen_tasks.py). The
neutral standard prompt (below, ADR-0016) is what every product receives — no
product-specific syntax. End-state assertions live in `tasks.T6_wechat_schedule_001`.

