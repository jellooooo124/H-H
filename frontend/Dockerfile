# Research/demo only. Package versions should be locked after the first successful online install.
FROM node:22-alpine AS web-build
WORKDIR /work
COPY frontend/package.json ./package.json
COPY frontend/vite.config.js frontend/index.html frontend/patient.html ./
COPY frontend/src ./src
RUN npm install --no-audit --no-fund && npm run build

FROM nginx:1.27-alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=web-build /work/dist /usr/share/nginx/html
EXPOSE 80
