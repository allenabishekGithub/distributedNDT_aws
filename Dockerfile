FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better Docker layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY ndt_manager.py .
COPY resource_monitor.py .
COPY deployment_manager.py .
COPY instance_provisioner.py .
COPY config.yaml .

# Create directories
RUN mkdir -p /app/logs /app/data /app/topologies

# Create non-root user
RUN useradd -m -u 1000 ndt && chown -R ndt:ndt /app
USER ndt

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["python", "ndt_manager.py"]