FROM python:3.10-slim AS builder

RUN mkdir /app

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt /app/
COPY requirements/ /app/requirements/
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -r /app/requirements/production.txt

FROM python:3.10-slim

RUN useradd -m -r appuser && \
    mkdir /app && \
    chown -R appuser /app

COPY --from=builder /usr/local/lib/python3.10/site-packages/ /usr/local/lib/python3.10/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin

WORKDIR /app

COPY --chown=appuser:appuser . .

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN chmod +x /app/entrypoint.prod.sh

EXPOSE 8000

CMD ["/app/entrypoint.prod.sh"]
