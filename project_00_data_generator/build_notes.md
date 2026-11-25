# Build notes: project 0

These are the problems I actually hit while building the generator, written down as they
happened.

**The ECB site was blocked.** I planned to use real ECB reference rates. The build environment's
network proxy refused the connection to the ECB, both the main site and its data API. I
switched to a synthetic rate series. In hindsight that is the better design anyway: a build
that depends on a download is not fully reproducible.

**pandas turned `None` into `NaN`, and my checks didn't notice.** The first full build crashed
with `NaTType does not support astimezone`. When I build a DataFrame from dicts, a `None` in a
column of dates or strings can come back as `NaN` or `NaT`, and `NaN is not None` is `True`. So
`if r.end_type is not None` let active subscriptions through as if they had ended. I replaced
every such check with `pd.notna()`. It is a mistake that does not raise an error in most
places. It just gives you wrong rows quietly, which is worse.

**One order fell outside the window.** My first completeness test said one true order was in no
shop file. In that build it was created at 23:26 UTC on 30 June 2025, which is 00:26 on 1 July in London, so
it belongs to a file after the data window. The data was right and the test was wrong. It is
the same London-versus-UTC problem that project 1 has to solve, and I hit it in my own test
before any pipeline existed.

**A defect I claimed was never there.** I listed "character outside Windows-1252" as a defect
of the fulfilment files, but Faker's German names all fit in Windows-1252, so it never happened.
The test that checks every catalogued defect exists in the files caught it. I added a small share
of Polish and Turkish names to the German customers (letters like ł, ş and ğ), which is realistic
for Germany and makes the defect real. Without that test, the README would have described a
problem the data did not have.

**A duplicate dictionary key.** The nickname table had `"Johannes"` twice. Python keeps the last
value silently, so one nickname never appeared. Small, but it is exactly the kind of thing a
linter catches and a reader does not.

**Changing the name pool changed every number.** Adding the Polish and Turkish names took extra
random draws, so every later draw shifted. People went from 20,116 to 20,127 and every count
moved. It happened again when I replaced Faker's invented town names with real cities: 20,127
became 20,142. That is why I wrote `test_docs_match_build.py`: the README numbers are checked against the
build, so they cannot go stale without a failing test.

**Faker's town names gave the game away.** Looking at the first shop files, the cities were
things like "South Margarettown". Anyone opening a file would know it was generated in a
second. I replaced them with a weighted list of real cities per country. Streets and
postcodes are still Faker's and do not match the city, which is a known limitation.

**What I would do differently.** The exporters loop over rows in Python and take about 80 of
the 110 seconds. That is fine for 30 months of data. For a much bigger company I would write the
files with vectorised pandas or DuckDB instead.
