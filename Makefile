PY ?= python3

.PHONY: setup data test verify-data

setup:
	$(PY) -m pip install -e ".[dev]"

data:
	PYTHONPATH=src $(PY) -m halden.generator --out data

test:
	PYTHONPATH=src $(PY) -m pytest -q

# Rebuild from scratch and confirm every file is byte-identical to the published build.
verify-data: data
	diff -u project_00_data_generator/expected_checksums_raw.sha256 data/raw/_checksums.sha256
	diff -u project_00_data_generator/expected_checksums_ground_truth.sha256 data/ground_truth/_checksums.sha256
	@echo "build matches the published checksums"
