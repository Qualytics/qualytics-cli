# Getting Started

## Authentication

### Browser-based login (recommended)

```bash
qualytics auth login --url "https://your-instance.qualytics.io/"
```

This opens your Qualytics login page in a browser and receives the token automatically.

### Manual token configuration

```bash
qualytics auth init --url "https://your-instance.qualytics.io/" --token "YOUR_TOKEN"
```

For self-signed certificates:

```bash
qualytics auth init --url "https://..." --token "..." --no-verify-ssl
```

### Check your status

```bash
qualytics auth status
```

Shows your connected URL, masked token, expiry, and SSL settings.

### Health check

```bash
qualytics doctor
```

Runs connectivity and configuration checks to verify everything is working.

## Configuration File

Configuration is saved to `~/.qualytics/config.yaml`. This file stores your URL, token, and SSL settings. You can edit it directly or use the `auth` commands above.

## Environment Variables

The CLI loads environment variables from a `.env` file in your working directory (via `python-dotenv`). You can use `${ENV_VAR}` syntax in any CLI flag that accepts sensitive values:

```bash
export QUALYTICS_URL="https://your-instance.qualytics.io/"
export QUALYTICS_TOKEN="your-jwt-token"
qualytics auth init --url '${QUALYTICS_URL}' --token '${QUALYTICS_TOKEN}'
```

### Secrets management

The CLI never stores credentials in plaintext. Sensitive flags support `${ENV_VAR}` syntax, resolved from environment variables at runtime.

**Supported on these flags:** `--host`, `--username`, `--password`, `--access-key`, `--secret-key`, `--uri`, `--token`

```bash
export PG_USER=analyst
export PG_PASS=s3cret

qualytics connections create --type postgresql --name prod-pg \
  --host db.example.com --username '${PG_USER}' --password '${PG_PASS}'
```

**In CI/CD pipelines (GitHub Actions):**

```bash
qualytics connections create --type postgresql --name prod-pg \
  --host "${{ secrets.PG_HOST }}" --password "${{ secrets.PG_PASS }}"
```

### Banner suppression

Set `QUALYTICS_NO_BANNER=1` or `CI=true` to suppress the startup banner (useful in scripts and CI/CD).
