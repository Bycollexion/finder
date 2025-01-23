# Use Python 3.9 slim image
FROM python:3.9-slim

# Run in unbuffered mode
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# Create and change to the app directory
WORKDIR /app

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc python3-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy local code to the container image
COPY . .

# Run the web service on container startup using Railway's PORT
CMD gunicorn main:app --bind 0.0.0.0:$PORT --workers 4 --threads 8 --timeout 0
