.PHONY: setup sync colmap train export view proxy demo validate validate-a validate-b validate-c validate-d

PYTHON ?= python3

# ============================================================
# Setup
# ============================================================

setup:
	$(PYTHON) -m pip install -r requirements.txt

# ============================================================
# Pipeline Stages
# ============================================================

sync:
	$(PYTHON) scripts/stage1_sync.py

colmap:
	$(PYTHON) scripts/stage2_colmap.py

colmap-sparse:
	$(PYTHON) scripts/stage2_colmap.py --sparse-only


train:
	$(PYTHON) scripts/stage3_4dgs.py

export:
	@echo "Export is part of stage3_4dgs.py — run 'make train'"

# ============================================================
# Viewer + Gemini
# ============================================================

view:
	$(PYTHON) scripts/stage4_viewer.py

proxy:
	$(PYTHON) server/gemini_proxy.py

demo: download-demo view

download-demo:
	$(PYTHON) scripts/download_demo_scene.py

# ============================================================
# Validation
# ============================================================

validate-a:
	$(PYTHON) scripts/validate_contracts.py a

validate-b:
	$(PYTHON) scripts/validate_contracts.py b

validate-c:
	$(PYTHON) scripts/validate_contracts.py c

validate-d:
	@echo "Contract D validation is POST-MVP"

validate:
	$(PYTHON) scripts/validate_contracts.py all
