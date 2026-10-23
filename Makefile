.PHONY: install test run figures demo clean

install:
	python3 -m pip install -r requirements.txt

test:
	python3 -m pytest -q

run:
	python3 -m privfuse.experiments.run_all

figures:
	python3 -m privfuse.cli figures

demo:
	python3 -m privfuse.cli demo --requests 2000

clean:
	rm -rf results/figures/*.png results/*.csv results/*.json .pytest_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
