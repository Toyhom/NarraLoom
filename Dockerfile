FROM node:22-bookworm-slim AS frontend
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json vite.config.js ./
COPY web ./web
RUN npm run build

FROM python:3.11-slim-bookworm
WORKDIR /app
COPY pyproject.toml README.md LICENSE NOTICE.md ./
COPY licenses ./licenses
COPY src ./src
RUN python -m pip install --no-cache-dir '.[avatar]'
COPY --from=frontend /build/web/dist /app/web/dist
WORKDIR /workspace
EXPOSE 18090
ENTRYPOINT ["narraloom", "serve", "--workspace", "/workspace", "--web-dist", "/app/web/dist", "--host", "0.0.0.0"]
