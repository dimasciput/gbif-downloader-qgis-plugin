PLUGIN_NAME := gbif_downloader
BUILD_DIR := build
DIST_DIR := dist
PACKAGE := $(DIST_DIR)/$(PLUGIN_NAME).zip
PLUGIN_FILES := \
	LICENSE \
	__init__.py \
	metadata.txt \
	plugin.py \
	dock_widget.py \
	credentials_dialog.py \
	compat.py \
	gbif_api.py \
	gbif-downloader-icon.png \
	gui \
	tab_action \
	tab_downloads

.PHONY: all package check clean docs docs-serve docs-clean

all: package

package:
	@test -f metadata.txt
	@test -f __init__.py
	@command -v zip >/dev/null
	rm -rf $(BUILD_DIR)/$(PLUGIN_NAME) $(PACKAGE)
	mkdir -p $(BUILD_DIR)/$(PLUGIN_NAME) $(DIST_DIR)
	cp -R $(PLUGIN_FILES) $(BUILD_DIR)/$(PLUGIN_NAME)/
	find $(BUILD_DIR)/$(PLUGIN_NAME) -type d -name __pycache__ -prune -exec rm -rf {} +
	find $(BUILD_DIR)/$(PLUGIN_NAME) -type f -name '*.py[co]' -delete
	cd $(BUILD_DIR) && zip -qr ../$(PACKAGE) $(PLUGIN_NAME)
	rm -rf $(BUILD_DIR)/$(PLUGIN_NAME)
	@echo "Created $(PACKAGE)"

check: package
	@unzip -t $(PACKAGE) >/dev/null
	@unzip -l $(PACKAGE) | grep -q '$(PLUGIN_NAME)/metadata.txt'
	@unzip -l $(PACKAGE) | grep -q '$(PLUGIN_NAME)/__init__.py'
	@echo "$(PACKAGE) is ready for QGIS plugin installation"

docs:
	@command -v mkdocs >/dev/null || pip install mkdocs-material
	mkdocs build --strict

docs-serve:
	@command -v mkdocs >/dev/null || pip install mkdocs-material
	mkdocs serve

docs-clean:
	rm -rf site/

clean:
	rm -rf $(BUILD_DIR) $(DIST_DIR) site/
