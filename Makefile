.PHONY: install test api llm ui meta perf baseline dataset

install:
	pip install -r requirements.txt && playwright install chromium

test:        ## everything
	python -m pytest -q

api:         ## REST API + SQL data validation
	python -m pytest api_tests -q

llm:         ## golden/safety/multi-turn evals + DeepEval layer + regression gate
	python -m pytest llm_eval -q

ui:          ## Playwright browser tests
	python -m pytest ui_tests -q

meta:        ## prove the suite catches injected bugs
	python -m pytest meta_tests -q

perf:
	python perf/load_test.py

dataset:     ## regenerate datasets from the seed data
	python -m llm_eval.build_dataset

baseline:    ## record a new baseline from a known-good build (review before committing!)
	python -m llm_eval.make_baseline
