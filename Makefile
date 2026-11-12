# E203-Based INT8 MAC Accelerator - clean-room demo
# `make` is optional: the Python drivers do exactly the same thing.

PY ?= python3

.PHONY: help lint parse vectors check sim regress synth gatelevel full ci clean

help:
	@echo "Targets (python3 + iverilog + yosys; no PDK, no vendor library):"
	@echo "  make help       this message"
	@echo "  make lint       structural lint -> results/lint_report.txt"
	@echo "  make parse      optional real grammar parse (needs pyverilog)"
	@echo "  make vectors    regenerate deterministic vectors -> vectors/gen/"
	@echo "  make check      independent golden verification + checker mutation test"
	@echo "  make sim        compile and run the 6 Verilog testbenches (needs iverilog)"
	@echo "  make regress    full RTL pipeline -> results/regression_summary.md"
	@echo "  make synth      real generic-cell synthesis -> results/synthesis_report.md"
	@echo "  make gatelevel  replay synthesised netlists -> results/gatelevel_report.md"
	@echo "  make full       regress + synth + gatelevel (the complete evidence chain)"
	@echo "  make ci         same as full but every step is mandatory (used by CI)"
	@echo "  make clean      remove generated corpora, dumps, logs, netlists and .vvp files"

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

synth:
	$(PY) syn/run_synth.py

gatelevel:
	$(PY) run_gatelevel.py

full: regress synth gatelevel

ci:
	$(PY) run_regress.py --strict
	$(PY) syn/run_synth.py --strict
	$(PY) run_gatelevel.py --strict

clean:
	rm -f build/*.vvp results/dump_*.csv results/tb_*.log
	rm -f results/gl_dump_*.csv results/gl_tb_*.log
	rm -f vectors/gen/*.hex vectors/gen/manifest.csv
	rm -f results/lint_report.txt results/parse_report.txt
	rm -f results/regression_summary.md results/synthesis_report.md
	rm -f results/gatelevel_report.md
	rm -f syn/out/*
	rm -rf build/gl_run
