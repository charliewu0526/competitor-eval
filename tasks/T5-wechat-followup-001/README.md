# T5-wechat-followup-001

Capability domain: **wechat-im** · Task nature: **long-horizon**

## Scenario
In WeChat, send a polite follow-up reminder to each of these 3 contacts who haven't replied: '李娜', '王强', '赵敏'. Message: '您好，关于上周的方案，方便今天回复我吗？'

## Notes
This task is part of the auto-seeded task bank (scripts/gen_tasks.py). The
neutral standard prompt (below, ADR-0016) is what every product receives — no
product-specific syntax. End-state assertions live in `tasks.T5_wechat_followup_001`.

