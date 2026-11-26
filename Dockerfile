FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    TZ=Europe/Madrid

# tzdata is needed for zoneinfo("Europe/Madrid") on slim images
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 app

WORKDIR /app
COPY --chown=app:app server.py core.py store.py gtfsrt.py lurraldebus.py villavesa.py sources.py staticfeeds.py region.py ./
COPY --chown=app:app feeds ./feeds
COPY --chown=app:app static ./static
RUN mkdir -p /app/data && chown app:app /app/data

USER app
VOLUME /app/data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/agencies', timeout=4)" || exit 1

CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8000"]
