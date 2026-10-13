FROM node:22-alpine AS web-build
WORKDIR /work
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/vite.config.js frontend/index.html frontend/patient.html ./
COPY frontend/src ./src
RUN npm run build

FROM nginx:1.27-alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=web-build /work/dist /usr/share/nginx/html
EXPOSE 80
