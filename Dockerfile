FROM python:3.12-slim

WORKDIR /app

# Copy requirements first for better caching
COPY ./api/requirements.txt .
RUN pip install -r requirements.txt

# Copy the rest of the api directory
COPY ./api .

EXPOSE 8080

CMD ["uvicorn", "wsgi:application", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
