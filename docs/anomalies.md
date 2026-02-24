# Anomalies

Anomalies are data quality issues detected during scan operations. The CLI lets you list, inspect, update, archive, and delete anomalies.

## Commands

| Command | Description |
|---------|-------------|
| `anomalies get` | Get an anomaly by `--id` |
| `anomalies list` | List anomalies for a `--datastore-id`, filterable by status, type, date |
| `anomalies update` | Update status to `Active` or `Acknowledged` (single or bulk) |
| `anomalies archive` | Soft-delete with status: `Resolved`, `Invalid`, `Duplicate`, `Discarded` |
| `anomalies delete` | Hard-delete anomalies (single or bulk) |

## Listing Anomalies

```bash
# List all anomalies for a datastore
qualytics anomalies list --datastore-id 1

# Filter by status
qualytics anomalies list --datastore-id 1 --status Active

# Filter by date range
qualytics anomalies list --datastore-id 1 \
  --start-date 2026-01-01 --end-date 2026-01-31
```

## Inspecting an Anomaly

```bash
qualytics anomalies get --id 42
```

## Updating Status

```bash
# Acknowledge a single anomaly
qualytics anomalies update --id 42 --status Acknowledged

# Bulk update
qualytics anomalies update --ids 42,43,44 --status Active
```

## Archiving

Archive anomalies with a resolution status:

```bash
# Mark as resolved
qualytics anomalies archive --id 42 --status Resolved

# Mark as invalid (false positive)
qualytics anomalies archive --id 42 --status Invalid
```

Available archive statuses: `Resolved`, `Invalid`, `Duplicate`, `Discarded`.

## Deleting

```bash
# Delete a single anomaly
qualytics anomalies delete --id 42

# Bulk delete
qualytics anomalies delete --ids 42,43,44
```
