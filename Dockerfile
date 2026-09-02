# Backend: Python + FastAPI + Playwright + Chromium
# Uses Microsoft's official Playwright image which bundles all system deps.

FROM mcr.microsoft.com/playwright/python:v1.52.0-noble AS base

WORKDIR /app

# System deps for cryptography wheel and dnspython
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install only Chromium (the only browser the project uses)
RUN playwright install chromium

# Copy application code
COPY app/ app/
COPY Rules/ Rules/
COPY config.yaml policy.yaml ./

# Create working directories
RUN mkdir -p artifacts .cache vendor

# The server binds to 0.0.0.0 inside the container so Docker can forward it.
# This does NOT change the authorization model: the operator is still
# responsible for not exposing this to the public internet without access control.
ENV AGENTQA_HOST=0.0.0.0
ENV AGENTQA_PORT=8000
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Health check against the /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["python", "-m", "app.api.server"]
