FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Create non-root user for runtime security.
RUN useradd --create-home --shell /bin/bash appuser

# Copy only files required to build and run the package.
COPY pyproject.toml README.md ./
COPY src ./src

# Install production package (non-editable).
RUN pip install --upgrade pip && pip install --no-cache-dir .

USER appuser

CMD ["sentic-signal"]
