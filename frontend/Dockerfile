# syntax=docker/dockerfile:1.7

FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

COPY index.html ./
COPY src ./src

ARG VITE_API_BASE_URL=""
ARG VITE_MAX_UPLOAD_MB=20
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_MAX_UPLOAD_MB=${VITE_MAX_UPLOAD_MB}

RUN npm run build


FROM nginxinc/nginx-unprivileged:1.29-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD wget --quiet --output-document=- http://127.0.0.1:8080/healthz >/dev/null || exit 1
