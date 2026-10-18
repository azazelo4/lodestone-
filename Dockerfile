# Closed network? Point the bases at your registry mirror:
#   docker build --build-arg NODE_IMAGE=harbor.local/docker-hub/library/node:22-alpine \
#                --build-arg PYTHON_IMAGE=harbor.local/docker-hub/library/python:3.12-slim \
#                --build-arg NPM_REGISTRY=https://nexus.local/repository/npm-proxy/ \
#                --build-arg PIP_INDEX_URL=https://nexus.local/repository/pip-proxy/simple .
ARG NODE_IMAGE=node:22-alpine
ARG PYTHON_IMAGE=python:3.12-slim

FROM ${NODE_IMAGE} AS web
ARG NPM_REGISTRY=https://registry.npmjs.org/
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --registry "$NPM_REGISTRY" --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM ${PYTHON_IMAGE}
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_TRUSTED_HOST=""
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    LODESTONE_STATIC_DIR=/app/static
WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --index-url "$PIP_INDEX_URL" ${PIP_TRUSTED_HOST:+--trusted-host "$PIP_TRUSTED_HOST"} \
    -r requirements.txt
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
COPY --from=web /web/dist ./static
COPY deploy/entrypoint.sh /entrypoint.sh
RUN useradd -u 10001 -r -s /usr/sbin/nologin lodestone && chmod +x /entrypoint.sh
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
ENTRYPOINT ["/entrypoint.sh"]
CMD ["serve"]
