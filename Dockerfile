FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    EBAY_TRACKER_DB=/data/ebay_tracker.db

# Mount a folder holding watchlist.yaml here; the database is written beside it.
VOLUME /data

ENTRYPOINT ["ebay-tracker"]
CMD ["watch", "--watchlist", "/data/watchlist.yaml"]
