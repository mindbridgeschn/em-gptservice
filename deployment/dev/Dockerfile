# Use official Python slim image
  FROM python:3.10.11-slim

  # Set working directory
  WORKDIR /app

  # hadolint ignore=DL3008
  RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential \
  curl \
  && rm -rf /var/lib/apt/lists/*

  # Copy requirements first (for Docker caching)
  COPY requirements.txt .

  # Install Python dependencies
  RUN pip install --no-cache-dir -r requirements.txt

  # Copy application code
  COPY . .

  # Expose FastAPI port
  EXPOSE 8000

  # Command to run FastAPI app
  ENTRYPOINT ["uvicorn", "main:app", "--proxy-headers", "--forwarded-allow-ips", "*", "--host", "0.0.0.0", "--port", "8000"]

#CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8001"]