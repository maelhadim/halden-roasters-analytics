# Runbook: project 0

## Build the data

```bash
make setup
make data
```

A normal build takes about 110 seconds and ends with a line like:

```
INFO  halden.generator done in 106.2s: files=2959 bytes=133713807 defects=17025
```

If the file count or the byte count is different, the build is not the published one. Run
`make verify-data` to see which files differ.

## Check a build

```bash
make verify-data
```

This rebuilds and runs `diff` against the committed checksums. No output from `diff`, followed
by `build matches the published checksums`, means every file is byte-identical. Any other
output names the files that changed.

## Rerun safely

Rerunning is always safe. The generator builds into `data/_build_<timestamp>/` and only
replaces `data/raw` and `data/ground_truth` after every file has been written. If the build
fails, the error is logged, the temporary folder is deleted and the existing data is left as
it was.

There is one gap. The final swap replaces `raw` and then `ground_truth`, and these are two
separate steps. If the process is killed between them, `raw` is new and `ground_truth` is
old. `make verify-data` catches this. The fix is to run `make data` again.

## When something fails

| Symptom | Likely cause | What to do |
| --- | --- | --- |
| `ModuleNotFoundError: faker` | Dependencies not installed | `make setup` |
| Checksums differ after changing nothing | A different version of pandas, numpy or Faker | Install the versions pinned in `pyproject.toml` |
| Checksums differ after a code change | Expected. Every random draw after the change shifts | Rebuild, rerun `make test`, then update the checksum files and every number quoted in the docs. `test_docs_match_build.py` lists the ones that no longer match |
| `test_every_catalogued_defect_is_present` fails | A defect in the catalogue no longer occurs in the files | Fix the exporter, or remove the defect from the catalogue and the README |
| Build is much slower than 2 minutes | Usually the exporters, which run row by row | Expected on slow machines; nothing is wrong |

## Changing a parameter

1. Change `src/halden/generator/config.py`.
2. `make data && make test`.
3. Copy `data/raw/_checksums.sha256` and `data/ground_truth/_checksums.sha256` over the two
   `expected_checksums_*.sha256` files in this folder.
4. Update the numbers in the README until `test_docs_match_build.py` passes.
5. Add a line to `docs/change_log.md`. If a later project already uses the data, rerun it too.
