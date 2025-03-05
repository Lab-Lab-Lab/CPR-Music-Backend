FROM python:3.10

WORKDIR /app

COPY requirements/ requirements/
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN mkdir -p /app/asgi.sock

CMD ["gunicorn", "--workers", "4", "--bind", "unix:/app/asgi.sock", "config.asgi:application"]
