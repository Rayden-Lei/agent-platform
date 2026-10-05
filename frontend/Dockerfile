FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
# 作为模板放进 templates/：官方镜像启动时用 envsubst 渲染到 conf.d/default.conf（替换 EMBED_ALLOWED_ORIGINS，docs/15 PB-07）。
# 给空的默认值：变量没定义时 envsubst 不替换，nginx 会把它当成未知变量起不来
ENV EMBED_ALLOWED_ORIGINS=""
COPY nginx.conf /etc/nginx/templates/default.conf.template
EXPOSE 80
