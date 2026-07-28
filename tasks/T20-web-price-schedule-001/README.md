# T20-web-price-schedule-001

Capability domain: **browser-web** · Task nature: **scheduled**

## Scenario
Set up a task that checks the price of the product at input/target-url.txt every morning at 09:00 and appends '{date},{price}' to output/price-history.csv.

## Notes
This task is part of the auto-seeded task bank (scripts/gen_tasks.py). The
neutral standard prompt (below, ADR-0016) is what every product receives — no
product-specific syntax. End-state assertions live in `tasks.T20_web_price_schedule_001`.

