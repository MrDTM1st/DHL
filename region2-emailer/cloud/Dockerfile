# Build from the region2-emailer/cloud/ directory as context.
#
# --- stage 1: build the React dashboard into one self-contained index.html ---
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# --- stage 2: the Python control plane (stdlib only) ---
FROM python:3.12-slim
WORKDIR /app
COPY server.py .
# The built UI; server.py serves it at "/" (falls back to its inline page if absent).
COPY --from=web /web/dist/index.html ./web_index.html
ENV PORT=8080
EXPOSE 8080
CMD ["python", "server.py"]
