# Dev image: the Vite dev server. src/ is bind-mounted by compose.override.yml.
#
# The build context is this directory, not the repo root. That is only possible
# because there is exactly one frontend and no shared workspace package to
# reach for — see PLAN.md §2.2. It keeps the context small and means the API
# and the web app are built the same way.
FROM node:22-slim

# pnpm ships with Node via corepack. Pinned so the lockfile stays valid.
RUN corepack enable && corepack prepare pnpm@9.15.0 --activate

WORKDIR /app

# Manifests first, so the install layer caches until a dependency changes.
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .

EXPOSE 5173
CMD ["pnpm", "dev"]
