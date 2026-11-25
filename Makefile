PY ?= python3
RUN = PYTHONPATH=src $(PY) -m

.PHONY: setup data test verify-data ingest validate replay

setup:
	$(PY) -m pip install -e ".[dev]"

data:
	$(RUN) halden.generator --out data

test:
	$(RUN) pytest -q

# Rebuild from scratch and confirm every file is byte-identical to the published build.
verify-data: data
	diff -u project_00_data_generator/expected_checksums_raw.sha256 data/raw/_checksums.sha256
	diff -u project_00_data_generator/expected_checksums_ground_truth.sha256 data/ground_truth/_checksums.sha256
	@echo "build matches the published checksums"

# Project 1. Safe to repeat: unchanged files are skipped.
ingest:
	$(RUN) halden.ingest run

# Fails if any check fails. The report it writes is committed, so `git diff` shows any drift.
validate:
	$(RUN) halden.ingest validate

replay:
	$(RUN) halden.ingest.replay
