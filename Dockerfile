FROM python:3.13.0-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gcc \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh

ENV PATH="/root/.local/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV XDG_CACHE_HOME=/tmp/.cache

WORKDIR /app

COPY . .

RUN uv sync --frozen --no-dev \
    && groupadd --gid 10001 telescan \
    && useradd --uid 10001 --gid telescan --no-create-home \
      --home-dir /app --shell /usr/sbin/nologin telescan \
    && chown -R telescan:telescan /app

USER telescan

CMD ["/app/.venv/bin/python", "main.py"]
