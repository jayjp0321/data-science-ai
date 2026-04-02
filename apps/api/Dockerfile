FROM python:3.11-slim

WORKDIR /app

# Copy entire project (important for imports)
COPY . .

# Install curl for health checks (if needed)
RUN apt-get update && apt-get install -y curl

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose port (documentation only)
EXPOSE 8000

# Start server
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]