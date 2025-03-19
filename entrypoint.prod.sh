#!/bin/sh

export DJANGO_READ_DOT_ENV_FILE=True
export DJANGO_SETTINGS_MODULE=config.settings.production

python manage.py collectstatic --noinput
python manage.py migrate --noinput
python -m gunicorn config.asgi:application \
        --bind 0.0.0.0:8000 \
        --workers 4 \
        -k uvicorn.workers.UvicornWorker
