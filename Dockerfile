# Use an official Python runtime as the base image
FROM python:3.13-slim

# Set the working directory in the container
WORKDIR /app

# Update pip to the latest version
RUN pip install --upgrade pip

# Install build dependencies for compiling C extensions (e.g., greenlet)
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container
COPY requirements.txt .

# Install all dependencies in one step
RUN pip install --no-cache-dir -r requirements.txt gunicorn pymysql cryptography

# Copy the application code into the container
COPY app app
COPY migrations migrations
COPY famplan.py config.py boot.sh app.db ./

# Make the boot.sh script executable
RUN chmod a+x boot.sh

# Set environment variables
ENV FLASK_APP=famplan.py

# Compile translations (if applicable)
#RUN flask translate compile

# Expose port 5000
EXPOSE 5000

# Define the entrypoint to run the boot.sh script
ENTRYPOINT ["./boot.sh"]