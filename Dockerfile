# --- stage 1: build the React dashboard into one self-contained index.html ---
FROM node:22-slim AS web
WORKDIR /web
COPY region2-emailer/cloud/web/package.json region2-emailer/cloud/web/package-lock.json ./
RUN npm ci
COPY region2-emailer/cloud/web/ ./
RUN npm run build

# --- stage 2: the Python control plane (stdlib only) ---
FROM python:3.12-slim
WORKDIR /app
COPY region2-emailer/cloud/server.py .
# The built UI; server.py serves it at "/" (falls back to its inline page if absent).
COPY --from=web /web/dist/index.html ./web_index.html
# PWA assets (manifest, service worker, icons) from the build's public/ dir.
COPY --from=web /web/dist/ ./web_dist/
ENV PORT=8080
EXPOSE 8080
CMD ["python", "server.py"]
