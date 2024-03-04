# Qualytics CLI

This is a CLI tool for working with Qualytics API. With this tool, you can manage your configurations, export checks, import checks, and more. It's built on top of the Typer CLI framework and uses the rich library for fancy terminal prints.

## Requirements

- Python 3.7+
- Packages:
  - `typer`
  - `os`
  - `json`
  - `requests`
  - `urllib3`
  - `re`
  - `rich`

## Installation

```bash
    pip install qualytics-cli
```

## Usage

### Help

```bash
qualytics --help
```

### Initializing the Configuration

You can set up your Qualytics URL and token using the `init` command:

```bash
qualytics init --url "https://your-qualytics.qualytics.io/" --token "YOUR_TOKEN_HERE"
```

| Option  | Type | Description                                           | Default | Required |
|---------|------|-------------------------------------------------------|---------|----------|
| `--url` | TEXT | The URL to be set. Example: https://your-qualytics.qualytics.io/ | None    | Yes      |
| `--token` | TEXT | The token to be set.                                 | None    | Yes      |

### Qualytics init help

```bash
qualytics init --help
```


### Display Configuration

To view the currently saved configuration:

```bash
qualytics show-config
```


### Export Checks

You can export checks to a file using the `checks export` command:

```bash
qualytics checks export --datastore DATASTORE_ID [--containers CONTAINER_IDS] [--tags TAG_NAMES] [--output LOCATION_TO_BE_EXPORTED]
```

By default, it saves the exported checks to `./qualytics/data_checks.json`. However, you can specify a different output path with the `--output` option.


| Option         | Type            | Description      | Default                            | Required |
|----------------|-----------------|------------------|------------------------------------|---------|
| `--datastore`  | INTEGER         | Datastore ID     | None                               | Yes     |
| `--containers` | List of INTEGER | Containers IDs   | None                               | No      |
| `--tags`       | List of TEXT    | Tag names    | None                               | No      |
| `--output`     | TEXT            | Output file path | ./qualytics/data_checks.json   | No      |


### Export Check Templates

Enables exporting check templates to the `_export_check_templates` table to an enrichment datastore.

```bash
qualytics checks export-templates --enrichment_datastore_id ENRICHMENT_DATASTORE_ID [--check_templates CHECK_TEMPLATE_IDS]
```

| Option        | Type     | Description                                                                | Default                            | Required |
|---------------|----------|----------------------------------------------------------------------------|------------------------------------|----------|
| `--enrichment_datastore_id` | INTEGER  | The ID of the enrichment datastore where check templates will be exported. | Yes      |
| `--check_templates`    | TEXT     | Comma-separated list of check template IDs or array-like format. Example: "1, 2, 3" or "[1,2,3]".| No       |


### Import Checks

To import checks from a file:


```bash
qualytics checks import --datastore DATASTORE_ID_LIST [--input LOCATION_FROM_THE_EXPORT]
```

By default, it reads the checks from `./qualytics/data_checks.json`. You can specify a different input file with the `--input` option.

**Note**: Any errors encountered during the importing of checks will be logged in `./qualytics/errors.log`.

| Option       | Type | Description                                                          | Default                       | Required |
|--------------|------|----------------------------------------------------------------------|-------------------------------|----------|
| `--datastore`| TEXT | Comma-separated list of Datastore IDs or array-like format. Example: 1,2,3,4,5 or "[1,2,3,4,5]" | None  | Yes      |
| `--input`    | TEXT | Input file path  | HOME/.qualytics/data_checks.json | None |


### Schedule Metadata Export:

Allows you to schedule exports of metadata from your datastores using a specified crontab expression.

```bash
qualytics schedule_app export-metadata --crontab "CRONTAB_EXPRESSION" --datastore "DATASTORE_ID" [--containers "CONTAINER_IDS"] --options "EXPORT_OPTIONS"
```

| Option       | Type | Description                                                          | Required |
|--------------|------|----------------------------------------------------------------------|---------|
| `--crontab`| TEXT | Crontab expression inside quotes, specifying when the task should run. Example: "0 * * * *"| Yes      |
| `--datastore`    | TEXT | The datastore ID | Yes      |
| `--containers`    | TEXT | Comma-separated list of container IDs or array-like format. Example: "1, 2, 3" or "[1,2,3]" | No      |
| `--options`    | TEXT | Comma-separated list of options to export or "all". Example: "anomalies, checks, field-profiles" | Yes      |


### Run a Catalog Operation on a Datastore

Allows you to trigger a catalog operation on any current datastore (datastore permission required by admin)

```bash
qualytics run catalog --datastore_id "DATSTORE_ID_LIST" --include --prune --recreate
```


| Option           | Type | Description                                                          | Required |
|------------------|------|----------------------------------------------------------------------|----------|
| `--datastore_id` | TEXT | Comma-separated list of Datastore IDs or array-like format. Example: 1,2,3,4,5 or "[1,2,3,4,5]"| Yes      |
| `--include`      | Text | Comma-separated list of include types or array-like format. Example: "table,view" or "[table,view]"| No       |
| `--prune`        | Bool | Prune the operation. Do not include if you want prune == false| No       |
| `----recreate`   | Bool | Recreate the operation. Do not include if you want recreate == false | No       |
