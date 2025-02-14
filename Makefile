__VERSION__ = "1.0.0-alpha.2"

bump:
	bump2version --allow-dirty --current-version $(__VERSION__) patch Makefile custom_components/heating_degree_days/manifest.json

lint:
	ruff check custom_components --fix

install_dev:
	pip install -r requirements-dev.txt
