# Frontend image — build the SPA, serve it with nginx, and reverse-proxy /api to
# the backend (mirroring the Vite dev proxy, including stripping the /api prefix).
# Serving the SPA and the API from one origin means no CORS and no code change.
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
# Point the SPA directly at the backend endpoint at build time. Empty (default)
# falls back to same-origin "/api" for the nginx-proxy deployment.
ARG VITE_API_URL=""
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
