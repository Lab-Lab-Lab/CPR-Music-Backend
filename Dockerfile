FROM python:3.10

WORKDIR /app

COPY requirements/ requirements/
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

ENV NUM_WORKERS=4

ARG SOCKFILE

CMD ["sh", "-c", "gunicorn config.asgi:application \
    --name django-backend \
    --workers $NUM_WORKERS \
    -k uvicorn.workers.UvicornWorker \
    --bind unix:$SOCKFILE \
    --log-level=debug \
    --log-file=/app/logs/gunicorn.log"]
