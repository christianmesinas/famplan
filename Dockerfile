# Basisimage met Python 3.13 slim
FROM python:3.13-slim AS base
WORKDIR /app

# Installeer build dependencies en pip upgrade
RUN pip install --upgrade pip
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*  # Opruimen na installatie om imagegrootte te beperken

# Installeer Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopieer applicatie code
COPY . .

# Maak instance directory aan en zet permissies
RUN mkdir -p /app/instance
RUN chmod 755 /app/instance

# Development omgeving configuratie
FROM base AS development
ENV FLASK_APP=famplan.py
ENV FLASK_ENV=development

# Initialiseer database bij eerste keer opstarten
RUN flask db init || echo "Database already initialized"
RUN flask db migrate -m "Initial migration" || echo "Migration failed or not needed"
RUN flask db upgrade || echo "Database upgrade failed or not needed"

EXPOSE 5000
CMD ["flask", "run", "--host=0.0.0.0", "--port=5000", "--reload"]
# Met hot-reload voor ontwikkeling

# Productie omgeving configuratie
FROM base AS production
RUN pip install gunicorn pymysql cryptography  # Extra dependencies voor productie
ENV FLASK_APP=famplan.py

# Database setup voor productie
RUN flask db init || echo "Database already initialized"
RUN flask db migrate -m "Initial migration" || echo "Migration failed or not needed"
RUN flask db upgrade || echo "Database upgrade failed or not needed"

EXPOSE 5000
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "famplan:app"]
# Gunicorn voor betere performance