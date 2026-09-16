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

Set `QUALYTICS_CONFIG_HOME` to point the CLI at an alternate configuration directory — useful for keeping side-by-side profiles, one per deployment:

```bash
QUALYTICS_CONFIG_HOME=~/.qualytics-uat qualytics auth init --url "https://uat.example.qualytics.io" --token "..."
QUALYTICS_CONFIG_HOME=~/.qualytics-uat qualytics datastores list
```

## Environment Variables

The CLI loads environment variables from a `.env` file in your working directory (via `python-dotenv`).

### Instance override

`QUALYTICS_URL` and `QUALYTICS_TOKEN`, set together, take precedence over the saved configuration for that invocation — no re-login needed when working against a second instance (setting only one of the two is an error). `QUALYTICS_SSL_VERIFY=false` disables certificate verification for the env-configured instance. Run them in a subshell or via [direnv](https://direnv.net/) to keep tokens out of your shell history:

```bash
(export QUALYTICS_URL="https://uat.example.qualytics.io" QUALYTICS_TOKEN="$(cat /secure/uat-token)"
 qualytics checks export --datastore-id 4 --output ./uat-checks)
```

You can also use `${ENV_VAR}` syntax in any CLI flag that accepts sensitive values:

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

### API path override

The CLI assumes the API is served under `/api` on your instance (true for all deployments). When targeting an API served from a different path — such as a local controlplane running bare on `http://localhost:8000` — set `QUALYTICS_API_PATH` to the actual prefix, or to an empty string for a root-served API:

```bash
# Local controlplane with no /api prefix
QUALYTICS_API_PATH= qualytics doctor

# Persist it for every invocation
echo 'QUALYTICS_API_PATH=' >> ~/.qualytics/.env
```
