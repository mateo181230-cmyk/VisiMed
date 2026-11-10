FROM nginx:alpine

ARG WEB_DIST_DIR=deployments/vps-20261030-r33/web

COPY infra/web.nginx.conf /etc/nginx/conf.d/default.conf
COPY ${WEB_DIST_DIR} /usr/share/nginx/html

EXPOSE 80
