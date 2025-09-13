# Use an official Python runtime as a parent image
FROM python:3.11-slim

# --- NEW SECTION: Install dockerize ---
# Set an environment variable for the dockerize version
ENV DOCKERIZE_VERSION v0.7.0
# Download and install dockerize
RUN apt-get update && apt-get install -y wget && \
    wget -O dockerize-linux-amd64-$DOCKERIZE_VERSION.tar.gz https://github.com/jwilder/dockerize/releases/download/$DOCKERIZE_VERSION/dockerize-linux-amd64-$DOCKERIZE_VERSION.tar.gz && \
    tar -C /usr/local/bin -xzvf dockerize-linux-amd64-$DOCKERIZE_VERSION.tar.gz && \
    rm dockerize-linux-amd64-$DOCKERIZE_VERSION.tar.gz && \
    apt-get autoremove -y && apt-get clean -y && rm -rf /var/lib/apt/lists/*
# --- END NEW SECTION ---

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir psycopg[binary] pydantic pydantic-settings

# Copy the .gitignore file so the migration script can find the project root
COPY .gitignore .
# Copy the entire pete_e application code into the container
COPY ./pete_e ./pete_e

# Copy the migration script and schema
COPY migration.py .
# --- THIS IS THE CORRECTED LINE ---
COPY ./init-db/schema.sql .

# Copy the data files needed for the migration
COPY ./knowledge ./knowledge
COPY ./integrations ./integrations