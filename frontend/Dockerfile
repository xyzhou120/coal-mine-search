# ============================================================
# 前端构建镜像（多阶段构建）
# Stage 1: 构建 Vue3 应用
# Stage 2: Nginx 提供静态文件服务
# ============================================================

# ── Stage 1: Build ──────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

# 配置 npm 使用国内镜像
RUN npm config set registry https://registry.npmmirror.com

COPY package.json .
RUN npm install

COPY . .
RUN npm run build

# ── Stage 2: Serve ──────────────────────────────────────────
FROM nginx:alpine

# 复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 复制 Nginx 配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
