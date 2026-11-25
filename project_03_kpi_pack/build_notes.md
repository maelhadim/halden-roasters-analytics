# Build notes: project 3

These are the problems I hit while building the pack, in the order they happened.

**MRR was off in one month, and I had to prove why.** My first comparison with the ground
truth matched MRR to the penny in 29 months and was 61.48 GBP high in June 2025. A gap in the
last month of the data looked like the same edge as project 1's paid orders, but "probably the
same thing" is not a reason. I wrote a query that lists the subscriptions active at the end of
June in one source and not the other, and prices them the way the pack does. There were two,
and together they come to exactly 61.48. The query now runs in every validation.

**Negative zero in the CSV files.** The revenue bridge had cells written as `-0`. They come
from rounding small negative numbers, and pandas writes them faithfully. Excel reads `-0` as
0, so the numbers were fine, but a reader of the CSV would wonder what a negative zero
means. Adding 0.0 to every float column before writing turns -0.0 into 0.0.

**Backslashes in the M scripts.** The first generated scripts had `"\\"` in the folder path,
because I wrote them through a Python f-string and escaped the backslash twice. M has no escape
sequences: `"\\"` in M is two backslashes. A test now checks there are none.

**The overall check ignored errors.** The first version said PASS if no check said FAIL. Then
one check returned `#VALUE!`: `ABS` over a whole column included the header text. That check
was neither PASS nor FAIL, so the overall result was PASS. It now says PASS only if every check
says PASS, and the column sum uses `SUMIF`, which skips text.

**A rate's change looked like a percentage change.** The churn rate fell from 7.95% to 5.81%,
and the Change column showed "-2.14%". A reader could take that as a 2.14% relative fall.
For rates the column now shows percentage points: "-2.14 pp".

**A coloured cell that should not have been.** In a PDF export from LibreOffice, the
"Active subscription accounts" change was shaded green, though accounts are meant to be
neutral. I evaluated the conditional format's own formula in a cell on the same recalculated
copy, and it returned FALSE. The rule in the file is right, and LibreOffice's PDF export drew
something its own calculation did not. I left the rule as it is and added it to the checks
for the first Excel run.

**Two builds, two different files.** The plan was to commit the workbook and have CI rebuild
it and compare. Two builds of the same data differed: an `.xlsx` is a zip, and openpyxl
stamps every part, and the file's "modified" property, with the build time. Rewriting the zip
with one fixed time, and the property with one fixed date, made builds byte-identical.

**Hidden helper cells.** The Summary sheet needs the row of the selected month, the month
before and the year-ago month. I put them in a hidden column instead of repeating a `MATCH`
in each of 33 formulas. Anyone who unhides columns J to L can see how the lookups work.
