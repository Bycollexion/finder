FROM python:3.9-slim

WORKDIR /app

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc python3-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# Expose the port
EXPOSE 8000

# Use gunicorn with proper logging
CMD gunicorn --bind 0.0.0.0:$PORT --log-level debug --access-logfile - --error-logfile - main:app
