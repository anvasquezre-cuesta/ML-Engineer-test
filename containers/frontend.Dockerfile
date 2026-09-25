# syntax=docker/dockerfile:1.7
# Audit viewer: static files plus pdf.js on nginx. Build context: the repository root.

FROM node:22.23.3-alpine AS pdfjs
ARG PDFJS_VERSION=6.3.289
WORKDIR /pdfjs
# npm pack verifies the tarball against the registry's integrity hash.
RUN npm pack "pdfjs-dist@${PDFJS_VERSION}" --silent \
    && tar -xzf "pdfjs-dist-${PDFJS_VERSION}.tgz" \
    && mkdir out \
    && cp package/build/pdf.min.mjs package/build/pdf.worker.min.mjs package/LICENSE out/ \
    && cp -r package/wasm package/cmaps package/standard_fonts package/iccs out/

FROM nginxinc/nginx-unprivileged:1.29.8-alpine
ENV API_UPSTREAM=http://api:8000
COPY containers/frontend.nginx.conf.template /etc/nginx/templates/default.conf.template
COPY frontend/index.html frontend/app.js frontend/boxes.js frontend/styles.css /usr/share/nginx/html/
COPY --from=pdfjs /pdfjs/out /usr/share/nginx/html/vendor/pdfjs/
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD ["wget", "-q", "-O", "/dev/null", "http://127.0.0.1:8080/frontend-health"]
