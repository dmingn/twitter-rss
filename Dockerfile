FROM python:3.10-slim AS base


FROM base AS export-requirements-txt

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR="off"

WORKDIR /export-requirements-txt

RUN pip install poetry

COPY pyproject.toml poetry.lock ./

RUN poetry export -f requirements.txt --without-hashes --output requirements.txt


FROM base AS install-requirements

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR="off"

WORKDIR /install-requirements

COPY --from=export-requirements-txt /export-requirements-txt/requirements.txt .

RUN pip install -r requirements.txt


FROM base

WORKDIR /twitter-rss

COPY --from=install-requirements /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages

COPY twitter-rss ./twitter-rss

ENTRYPOINT ["python", "-m", "uvicorn", "twitter-rss.main:app", "--host", "0.0.0.0"]
