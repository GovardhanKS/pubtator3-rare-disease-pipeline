# Paths and layout are hard-coded. The build date is not - it is read from an
# HTTP header at ingest and carried through the database. Baking a date in would
# reintroduce exactly the problem this project exists to solve.
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir duckdb httpx fastapi "gradio>=5" uvicorn pandas

COPY ingest/ ingest/
COPY query/ query/
COPY app/ app/
COPY experiments/ experiments/
COPY gold/ gold/

ENV PUBTATOR_DATA=/data
VOLUME /data
EXPOSE 7860
CMD ["python3", "app/main.py"]
