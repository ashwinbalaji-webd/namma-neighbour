FROM python:3.12-slim

ENV DJANGO_SETTINGS_MODULE=config.settings.development

WORKDIR /app

COPY requirements/development.txt requirements/development.txt
COPY requirements/base.txt requirements/base.txt
RUN pip install --no-cache-dir -r requirements/development.txt

COPY . .

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
