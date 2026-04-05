FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the beckn protocol library
COPY ../../packages/beckn-protocol /packages/beckn-protocol

# Copy application code
COPY . .

# Set Python path to include beckn protocol library
ENV PYTHONPATH="/app:/packages/beckn-protocol"

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
