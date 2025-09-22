FROM python:3.11-slim

WORKDIR /app

# Install docker-cli + curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    docker.io curl && \
    rm -rf /var/lib/apt/lists/*

COPY valheim_bot.py /app/valheim_bot.py

RUN pip install docker requests

CMD ["python3", "valheim_bot.py"]

