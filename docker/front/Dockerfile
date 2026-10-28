# Frontend del comedor: build de Vite servido con nginx. Contexto: la raíz.
FROM node:22-alpine AS build
WORKDIR /front
COPY comedorfront/package.json comedorfront/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY comedorfront/ ./
# La URL de la API queda fija en el build: la que usa el NAVEGADOR.
ARG VITE_API_URL=/api
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY docker/front/nginx.conf /etc/nginx/conf.d/default.conf
COPY docker/front/nginx-rutas.conf /etc/nginx/comedor-rutas.conf
COPY --from=build /front/dist /usr/share/nginx/html
EXPOSE 80 443
