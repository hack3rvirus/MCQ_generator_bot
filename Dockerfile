# Use the official Python image
FROM python:3.11.9-slim

# Install system dependencies for Tesseract and Poppler
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    libtesseract-dev \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy the project files
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose the port for the webhook
EXPOSE 8000

# Set environment variable for unbuffered output
ENV PYTHONUNBUFFERED=1

# Run the bot
CMD ["python", "bot.py"]