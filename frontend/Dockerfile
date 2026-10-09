# Build context: repo root (see scripts/docker/smoke.sh / container-smoke.yml)
FROM node:22-slim AS deps-build
RUN apt-get update && apt-get install -y --no-install-recommends bash python3 && rm -rf /var/lib/apt/lists/*
RUN corepack enable
WORKDIR /app

COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./frontend/
RUN cd frontend && pnpm install --frozen-lockfile

COPY scripts/check_i18n.sh scripts/check_help_docs.sh ./scripts/
COPY locales ./locales
COPY docs/TA_ONBOARDING_GUIDE.md ./docs/TA_ONBOARDING_GUIDE.md
COPY frontend ./frontend

ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
ENV NEXT_OUTPUT=standalone

RUN cd frontend && pnpm run build

FROM node:22-slim AS runner
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
WORKDIR /app/frontend

COPY --from=deps-build /app/frontend/.next/standalone ./
COPY --from=deps-build /app/frontend/.next/static ./.next/static
COPY --from=deps-build /app/frontend/public ./public
COPY --from=deps-build /app/locales ../locales

USER node
EXPOSE 3000
CMD ["node", "server.js"]
