# E203-Based INT8 MAC Accelerator — clean-room demo
# `make` is optional: `python3 run_regress.py` does exactly the same thing.

PY ?= python3

.PHONY: help lint parse vectors check sim regress ci clean

help:
	@echo "Targets (python3 + iverilog only, no other dependencies):"
	@echo "  make help      this message"
	@echo "  make lint      structural lint -> results/lint_report.txt"
	@echo "  make parse     optional real grammar parse (needs pyverilog)"
	@echo "  make vectors   regenerate deterministic vectors -> vectors/gen/"
	@echo "  make check     independent golden verification + checker mutation test"
	@echo "  make sim       compile and run the 6 Verilog testbenches (needs iverilog)"
	@echo "  make regress   full pipeline -> results/regression_summary.md"
	@echo "  make ci        full pipeline, RTL simulation mandatory (used by CI)"
	@echo "  make clean     remove generated corpora, dumps, logs and .vvp files"

lint:
	$(PY) model/rtl_lint.py

parse:
	$(PY) model/verilog_parse_check.py

vectors:
	$(PY) model/gen_vectors.py

check:
	$(PY) model/check_results.py --verify-vectors --selftest

sim:
	$(PY) run_regress.py --sim-only

regress:
	$(PY) run_regress.py

ci:
	$(PY) run_regress.py --strict

clean:
	rm -f build/*.vvp results/dump_*.csv results/tb_*.log
	rm -f vectors/gen/*.hex vectors/gen/manifest.csv
	rm -f results/lint_report.txt results/regression_summary.md
