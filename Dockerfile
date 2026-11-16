FROM mcr.microsoft.com/playwright/python:v1.58.0-noble
WORKDIR /app
COPY claude_invite_railway/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY claude_invite_railway/*.py claude_invite_railway/config.json ./
ENV PYTHONUNBUFFERED=1 DATA_DIR=/data
CMD ["python", "server.py"]
