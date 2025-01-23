FROM python:3.9-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set environment variables
ENV PORT=8080
ENV PYTHONUNBUFFERED=1
ENV GUNICORN_CMD_ARGS="--config=gunicorn.conf.py --bind=0.0.0.0:8080 --workers=4 --timeout=120 --access-logfile=- --error-logfile=- --log-level=debug"

# Expose port
EXPOSE 8080

# Start gunicorn
CMD ["gunicorn", "main:app"]
