FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY api/ api/

ENV PORT=8000

CMD cd api && gunicorn test_app:app --bind 0.0.0.0:$PORT
