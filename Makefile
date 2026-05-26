VENV_PYTHON = $(CURDIR)/.venv/bin/python
VIEWER_PORT = 5173

.PHONY: start stop install setup-agent

start:
	@echo "══ Rebuilding ElevenLabs agent..."
	@$(VENV_PYTHON) server/create_agent.py
	@echo "══ Killing old processes on port $(VIEWER_PORT)..."
	@lsof -ti:$(VIEWER_PORT) | xargs kill -9 2>/dev/null || true
	@sleep 0.3
	@echo "══ Starting viewer on http://localhost:$(VIEWER_PORT)..."
	cd viewer && npm run dev

stop:
	@lsof -ti:$(VIEWER_PORT) | xargs kill -9 2>/dev/null || true
	@echo "Stopped."

install:
	python3 -m venv .venv
	$(VENV_PYTHON) -m pip install --upgrade pip
	$(VENV_PYTHON) -m pip install websockets google-genai pydantic python-dotenv opencv-python-headless numpy requests
	cd viewer && npm install
	@echo "Done. Run 'make start' to launch."

setup-agent:
	@echo "Creating/updating ElevenLabs agent..."
	$(VENV_PYTHON) server/create_agent.py
	@echo "Agent ready."
