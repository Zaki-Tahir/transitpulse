# syntax=docker/dockerfile:1
FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Static files behind nginx, running as a non-root user on port 8080.
FROM nginxinc/nginx-unprivileged:1.29-alpine
ENV API_UPSTREAM=http://api:8000
COPY deploy/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
