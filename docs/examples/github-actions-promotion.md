# Quality Checks Promotion with GitHub Actions

This guide shows how to version quality checks in Git and automatically promote them across environments (Dev → Test → Prod) using GitHub Actions.

## Repository Structure

```
your-repo/
  checks/
    orders/
      notnull__order_id.yaml
      between__total_amount.yaml
    customers/
      matchespattern__email.yaml
      isunique__customer_id.yaml
  .github/
    workflows/
      promote-checks.yml
```

## Exported Check Format

Each file in `checks/` is a portable quality check definition:

```yaml
# checks/orders/notnull__order_id.yaml
rule_type: notNull
description: Order ID must not be null
container: orders
fields:
  - order_id
coverage: 1.0
filter: null
properties: {}
tags:
  - data-quality
  - orders
status: Active
additional_metadata:
  _qualytics_check_uid: orders__notnull__order_id
```

Checks are **portable** — they reference containers by name (not ID), so the same file works across any datastore that has a matching container.

## Workflow: Dev → Test → Prod

### Step 1: Export checks from Dev

```bash
pip install qualytics-cli
qualytics init --url "$QUALYTICS_URL" --token "$QUALYTICS_TOKEN"

# Export all checks from the Dev datastore
qualytics checks export --datastore-id $DEV_DATASTORE_ID --output ./checks/
```

### Step 2: Commit and push

```bash
git add checks/
git commit -m "Update quality checks from Dev"
git push origin main
```

### Step 3: Review via Pull Request

Open a PR. Reviewers can see exactly which checks changed in the diff — each check is a separate YAML file, so changes are clear and reviewable.

### Step 4: Automated promotion on merge

The GitHub Actions workflow below handles the rest.

## GitHub Actions Workflow

```yaml
# .github/workflows/promote-checks.yml
name: Promote Quality Checks

on:
  push:
    branches: [main]
    paths: ['checks/**']
  release:
    types: [published]

jobs:
  promote-to-test:
    if: github.event_name == 'push'
    runs-on: ubuntu-latest
    environment: test
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install Qualytics CLI
        run: pip install qualytics-cli

      - name: Configure Qualytics
        run: qualytics init --url "${{ secrets.QUALYTICS_URL }}" --token "${{ secrets.QUALYTICS_TOKEN }}"

      - name: Import checks to Test
        run: qualytics checks import --datastore-id ${{ vars.TEST_DATASTORE_ID }} --input ./checks/

  promote-to-prod:
    if: github.event_name == 'release'
    runs-on: ubuntu-latest
    environment: production
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install Qualytics CLI
        run: pip install qualytics-cli

      - name: Configure Qualytics
        run: qualytics init --url "${{ secrets.QUALYTICS_URL }}" --token "${{ secrets.QUALYTICS_TOKEN }}"

      - name: Import checks to Prod
        run: qualytics checks import --datastore-id ${{ vars.PROD_DATASTORE_ID }} --input ./checks/
```

## Environment Setup

### GitHub Secrets (per environment)

| Secret | Description |
|--------|-------------|
| `QUALYTICS_URL` | Qualytics instance URL (e.g., `https://qualytics.example.com/`) |
| `QUALYTICS_TOKEN` | API token for the Qualytics instance |

### GitHub Variables (per environment)

| Variable | Description |
|----------|-------------|
| `TEST_DATASTORE_ID` | Datastore ID in the Test environment |
| `PROD_DATASTORE_ID` | Datastore ID in the Production environment |

### Setting Up GitHub Environments

1. Go to **Settings → Environments** in your GitHub repository
2. Create `test` and `production` environments
3. Add the secrets and variables listed above to each environment
4. Optionally add **required reviewers** to `production` for manual approval before Prod deployments

## Multi-Datastore Import

To import checks to multiple datastores in a single step:

```bash
qualytics checks import \
  --datastore-id $DATASTORE_1 \
  --datastore-id $DATASTORE_2 \
  --datastore-id $DATASTORE_3 \
  --input ./checks/
```

## Dry Run

Preview what would change before actually importing:

```bash
qualytics checks import \
  --datastore-id $PROD_DATASTORE_ID \
  --input ./checks/ \
  --dry-run
```

Output:
```
Loaded 15 check definitions from ./checks/
[DRY RUN] Importing to datastore 42...
          Import Summary
┏━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━┓
┃ Datastore ID ┃ Created ┃ Updated ┃ Failed ┃
┡━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━┩
│ 42           │ 10      │ 5       │ 0      │
└──────────────┴─────────┴─────────┴────────┘
```

## Upsert Behavior

Import uses **upsert** (create-or-update) logic:

- Each check has a stable `_qualytics_check_uid` in its `additional_metadata`
- On import, the CLI matches UIDs against existing checks in the target datastore
- **Match found** → update the existing check
- **No match** → create a new check
- Container names are resolved to IDs within each target datastore

This means you can safely re-import the same checks multiple times — existing checks are updated, new ones are created, and nothing is duplicated.
