# Lambda build for SAM (BuildMethod: makefile). Installs Linux arm64 wheels with uv, so no Docker is needed.
REQS := $(shell mktemp -t jhola-reqs)

build-JholaFunction:
	uv export --frozen --no-dev --no-hashes --no-emit-project -o $(REQS) >/dev/null
	uv pip install -q -r $(REQS) --target "$(ARTIFACTS_DIR)" --python-platform aarch64-manylinux_2_28 --python-version 3.12 --only-binary :all:
	cp -R src/jhola "$(ARTIFACTS_DIR)/"
	find "$(ARTIFACTS_DIR)" -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -f $(REQS)
