# Use Python 3.12 slim image for smaller size
FROM python:3.12-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies required for the application
RUN apt-get update && apt-get install -y \
    # Required for video processing and streaming
    ffmpeg \
    # Required for some Python packages compilation
    gcc \
    g++ \
    # Required for network operations
    curl \
    wget \
    # Required for some dependencies
    pkg-config \
    # Clean up apt cache to reduce image size
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy project files
COPY pyproject.toml MANIFEST.in requirements.txt ./
COPY src/ ./src/

# Install Python dependencies
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install -e .

# Create necessary directories
RUN mkdir -p /app/downloads /app/data

# Expose port for web interface
EXPOSE 8080

# Set default command to run with web interface options
CMD ["aniworld", "-w", "-wA", "-wN", "-wE", "-wP", "8080", "-o", "/app/downloads"]
