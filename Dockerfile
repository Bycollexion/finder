FROM python:3

# Run in unbuffered mode
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# Create and change to the app directory
WORKDIR /app

# Copy local code to the container image
COPY . ./

# Install project dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose the port
EXPOSE ${PORT}

# Run the web service on container startup
CMD gunicorn --workers=2 --bind=0.0.0.0:${PORT} main:app
