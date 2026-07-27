# input/ — T2

Holds the starting workbook `sales.xlsx` handed to each product. For this pilot
the concrete file is provided at run time by the operator; only the layout
contract matters for browsing:

- Sheet `Q1` with a numeric column C spanning rows 2..13 (the values to total).
- C14 is empty at start (the cell the product must fill).

Starting materials may be faked — the dirty-data regime (`meta.json`) governs
whether/how the data is dirtied.
