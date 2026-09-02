# Dyla Research Agent

Dyla is a research agent that will collect and ground answers in evidence.

## Setup

1. Create a virtual environment and install the package with development dependencies:

   ```bash
   python -m venv .venv
   .venv/bin/pip install -e '.[dev]'
   ```

2. Copy `.env.example` to `.env` and replace its fake values with credentials from your local Azure resources. Keep `.env` local; it is ignored by Git and must never be committed.

3. Run the test suite:

   ```bash
   .venv/bin/pytest -q
   ```

Configuration is loaded from environment variables or the optional local `.env` file. Required Azure OpenAI and Azure AI Search settings are validated when `load_settings()` is called.
