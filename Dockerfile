FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install . \
    && playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright

RUN useradd --create-home omniclaw \
    && mkdir -p /data/browser_state \
    && chown -R omniclaw /data
USER omniclaw

EXPOSE 8080
CMD ["omniclaw", "run"]