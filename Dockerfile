FROM python:3.13.0-slim

RUN apt-get update && apt-get install -y make curl gcc && apt-get clean

RUN curl -LsSf https://astral.sh/uv/install.sh | sh

ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

COPY . .

RUN uv sync --frozen

CMD ["make", "run"]