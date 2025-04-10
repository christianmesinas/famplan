FROM python:3.13-slim AS base
WORKDIR /app
RUN pip install --upgrade pip
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

FROM base AS development
ENV FLASK_APP=famplan.py
ENV FLASK_ENV=development
EXPOSE 5000
CMD ["flask", "run", "--host=0.0.0.0", "--port=5000", "--reload"]

FROM base AS production
RUN pip install gunicorn pymysql cryptography
ENV FLASK_APP=famplan.py
EXPOSE 5000
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "famplan:app"]