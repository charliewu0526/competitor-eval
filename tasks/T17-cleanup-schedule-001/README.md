# T17-cleanup-schedule-001

Capability domain: **computer-control** · Task nature: **scheduled**

## Scenario
Set up a scheduled job that runs every day at 02:00 and deletes files older than 7 days from ~/Downloads/tmp/, logging what it removed to ~/cleanup.log.

## Notes
This task is part of the auto-seeded task bank (scripts/gen_tasks.py). The
neutral standard prompt (below, ADR-0016) is what every product receives — no
product-specific syntax. End-state assertions live in `tasks.T17_cleanup_schedule_001`.

