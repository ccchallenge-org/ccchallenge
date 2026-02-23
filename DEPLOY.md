# Deployment

**Stack:** Docker Compose (Caddy + FastAPI) on Azure VM `ccchallenge-vm` in `ccc-rg` (northeurope).

## SSH

```bash
ssh azureuser@20.234.92.236
cd ccchallenge
```

## Deploy latest code

```bash
git pull && sudo docker compose up -d --build
```

## Logs

```bash
sudo docker compose logs -f app      # application
sudo docker compose logs -f caddy    # reverse proxy / TLS
```

## Restart

```bash
sudo docker compose restart
```

## Seed reviews (one-time)

Requires `curations/` to be copied into the container and `pdftotext` installed:

```bash
sudo docker cp curations ccchallenge-app-1:/app/curations
sudo docker exec ccchallenge-app-1 bash -c "apt-get update -qq && apt-get install -y -qq poppler-utils curl"
sudo docker exec ccchallenge-app-1 python -m backend.services.seed_reviews
```

## Environment

`.env` on the VM at `~/ccchallenge/.env`. See `.env.example` for required variables.

## DNS

A record for `ccchallenge.org` → `20.234.92.236` (Cloudflare, DNS only / grey cloud).
Caddy handles TLS via Let's Encrypt automatically.
