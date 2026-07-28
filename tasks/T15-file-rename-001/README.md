# T15-file-rename-001

Capability domain: **computer-control** · Task nature: **simple**

## Scenario
In the folder input/photos/, rename all .jpg files to the pattern 'YYYY-MM-DD_NNN.jpg' using each file's capture date (from EXIF), NNN a zero-padded sequence per day. Leave non-image files untouched.

## Notes
This task is part of the auto-seeded task bank (scripts/gen_tasks.py). The
neutral standard prompt (below, ADR-0016) is what every product receives — no
product-specific syntax. End-state assertions live in `tasks.T15_file_rename_001`.

