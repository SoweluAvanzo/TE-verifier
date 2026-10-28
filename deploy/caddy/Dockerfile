## =============================================================================
## deploy/caddy/Dockerfile — Caddy with the rate-limit plugin
## =============================================================================
## GUIDE STEP   9.0 (Caddy arrives in development; production pulls the same
##              image from 12.2, pushed by the release workflow)
## PURPOSE      The official `caddy` image does not include rate limiting.
##              Caddy plugins are compiled INTO the Caddy binary, so we build
##              a custom binary with `xcaddy` (Caddy's official build tool) and
##              the plugin github.com/mholt/caddy-ratelimit, then copy that
##              binary into the normal Caddy image.
## USED BY      compose.override.yml (`build: ./deploy/caddy` of the `caddy`
##              service, tagged te-caddy:local by compose.yml), and
##              .github/workflows/release.yml.template (builds and pushes it
##              as ghcr.io/soweluavanzo/te-verifier-caddy:<sha>).
## DEPENDS ON   Internet access at build time (downloads Go modules).
## WHY          Architecture §6: a coarse per-IP limit at the edge absorbs
##              floods before they reach Python; the precise per-user quotas
##              stay in the application (Redis). If you decide not to use the
##              plugin, delete this file, use `image: caddy:2.11.7` in
##              compose.yml and compose.prod.yml (and drop the `build:` of the
##              override and the Caddy steps of the release workflow), and
##              remove the `order rate_limit` and `rate_limit` blocks from
##              the Caddyfile.
## ACTIVATE     Uncomment, then `docker compose build caddy` and
##              `docker compose run --rm --no-deps caddy caddy list-modules | grep rate_limit`
##              (the module must be listed). Both images and the plugin are
##              pinned to exact versions; Dependabot proposes image updates
##              (.github/dependabot.yml.template), the plugin you bump by hand.
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your instructions between this list and the SOLUTION marker below.
## Lines starting with "|" are short illustrations, not the full file.
##
## Guide 9.0
## [ ] 1. Stage 1 from the official builder image of an exact Caddy version
##        (it contains Go and xcaddy), named `builder`, and build Caddy with
##        the plugin pinned to a commit (the plugin has no releases):
##          | FROM caddy:2.11.7-builder AS builder
##          | RUN xcaddy build --with github.com/mholt/caddy-ratelimit@<commit>
## [ ] 2. Stage 2 from the normal image of the SAME version (caddy:2.11.7);
##        copy /usr/bin/caddy from the builder stage over its own.
## [ ] 3. Check: `docker compose build caddy`, then
##          | docker compose run --rm --no-deps caddy \
##          |     caddy list-modules | grep rate_limit
##        (the module must be listed).
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## file. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

## Stage 1: the official builder image contains Go and xcaddy. Exact
## versions: a moving tag (caddy:2) would silently change what you run.
## The plugin has no release tags, so it is pinned to a commit of its
## repository (2026-06-12); xcaddy accepts module@commit.
FROM caddy:2.11.7-builder AS builder
RUN xcaddy build --with github.com/mholt/caddy-ratelimit@5625512f24f6f59d6f64fb3aafe5eecff0b286db

## Stage 2: the normal Caddy image, with its binary replaced by ours.
## Everything else (users, folders /data and /config, default command) stays
## the official one. Same version as the builder stage.
FROM caddy:2.11.7
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
