FROM mcr.microsoft.com/playwright/python:v1.58.0-noble
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY *.py config.json ./
ENV PYTHONUNBUFFERED=1 DATA_DIR=/data
CMD ["python", "server.py"]
