# Frontend image — build the SPA, serve it with nginx, and reverse-proxy /api to
# the backend (mirroring the Vite dev proxy, including stripping the /api prefix).
# Serving the SPA and the API from one origin means no CORS and no code change.
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
