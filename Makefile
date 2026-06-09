__VERSION__ = "1.1.0"

bump:
	bump2version --allow-dirty --current-version $(__VERSION__) patch Makefile custom_components/heating_cooling_degree_days/manifest.json

lint:
	ruff check custom_components --fix

install_dev:
	pip install -r requirements-dev.txt
