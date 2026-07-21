FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Create a non-root user for production security
RUN useradd -m -s /bin/bash appuser

# Set the working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create data directory and set permissions BEFORE copying code
RUN mkdir -p /app/data && chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Copy application code with proper ownership
COPY --chown=appuser:appuser . .

# Expose the port the app runs on
EXPOSE 8000

ENV CRM_DB_PATH=/app/data/crm.sqlite3
ENV CHECKPOINTS_DB_PATH=/app/data/checkpoints.sqlite3

# Run the FastAPI app with Uvicorn
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
