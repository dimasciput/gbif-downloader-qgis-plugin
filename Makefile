PLUGIN_NAME := gbif_downloader
DIST_DIR := dist
PACKAGE := $(DIST_DIR)/$(PLUGIN_NAME).zip

.PHONY: package clean

package:
	rm -rf build/$(PLUGIN_NAME) $(PACKAGE)
	mkdir -p build/$(PLUGIN_NAME) $(DIST_DIR)
	cp -R __init__.py metadata.txt plugin.py dock_widget.py credentials_dialog.py \
		gbif_api.py icon.svg gui tab_action tab_downloads build/$(PLUGIN_NAME)/
	find build/$(PLUGIN_NAME) -type d -name __pycache__ -prune -exec rm -rf {} +
	find build/$(PLUGIN_NAME) -type f -name '*.py[co]' -delete
	cd build && zip -qr ../$(PACKAGE) $(PLUGIN_NAME)
	rm -rf build/$(PLUGIN_NAME)
	@echo "Created $(PACKAGE)"

clean:
	rm -rf build dist
