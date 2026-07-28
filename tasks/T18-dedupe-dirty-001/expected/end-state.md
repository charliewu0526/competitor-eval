# Expected end-state — T18-dedupe-dirty-001

The folder input/messy-dir/ has nested subfolders with duplicate files (same content, different names), empty folders, and .DS_Store junk. Produce a deduplicated flat copy in output/clean-dir/ keeping one copy of each unique file; remove junk.

All primary assertions must hold.
