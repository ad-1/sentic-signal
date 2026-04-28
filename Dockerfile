# Multi-stage Dockerfile for Sentic-Signal
FROM python:3.13-slim AS builder

# Set working directory
WORKDIR /app

# Copy pyproject.toml first for better caching
COPY pyproject.toml ./

# Install build dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip install --upgrade pip && pip install --no-cache-dir -e ".[dev]"

# Final stage
FROM python:3.13-slim

# Set working directory
WORKDIR /app

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash appuser
USER appuser
WORKDIR /home/appuser

# Copy the installed dependencies and source code from builder stage
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /app/src /app/src

# Copy entrypoint script (if needed)
COPY --chown=appuser:appuser ./.env.example .env.example

# Set environment variables
ENV PYTHONPATH=/app/src
ENV PATH=/home/appuser/.local/bin:$PATH

# Use the installed entry point script
CMD ["sentic-signal"]
