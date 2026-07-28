# T21-web-dirty-extract-001

Capability domain: **browser-web** · Task nature: **dirty-data**

## Scenario
Open the messy product listing page at input/target-url.txt. Extract name, price, and rating for all products into output/products.csv. The HTML is inconsistent: some prices in spans, some in divs, missing ratings, and ad rows mixed in.

## Notes
This task is part of the auto-seeded task bank (scripts/gen_tasks.py). The
neutral standard prompt (below, ADR-0016) is what every product receives — no
product-specific syntax. End-state assertions live in `tasks.T21_web_dirty_extract_001`.

## Dirty data (铁律: 材料可假, 脏数据必真)
- prices in varying tags (span/div)
- some products missing ratings
- advertisement rows interleaved
- inconsistent currency formatting

