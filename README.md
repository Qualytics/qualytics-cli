# Qualytics CLI

This is a CLI tool for working with the Qualytics API. With this tool, you can manage your configurations, export checks, import checks, and more. It's built on top of the Typer CLI framework and uses the Rich library for enhanced terminal outputs.

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

| Option         | Type            | Description        | Default                            | Required |
|----------------|-----------------|--------------------|------------------------------------|----------|
| `--datastore`  | INTEGER         | Datastore ID       | None                               | Yes      |
| `--containers` | List of INTEGER | Containers IDs     | None                               | No       |
| `--tags`       | List of TEXT    | Tag names          | None                               | No       |
| `--output`     | TEXT            | Output file path   | ./qualytics/data_checks.json       | No       |

### Export Check Templates

You can export check templates to the `_export_check_templates` table to an enrichment datastore.

```bash
qualytics checks export-templates --enrichment_datastore_id ENRICHMENT_DATASTORE_ID [--check_templates CHECK_TEMPLATE_IDS]
```

| Option                   | Type     | Description                                                                | Required |
|--------------------------|----------|----------------------------------------------------------------------------|----------|
| `--enrichment_datastore_id` | INTEGER  | The ID of the enrichment datastore where check templates will be exported. | Yes      |
| `--check_templates`       | TEXT     | Comma-separated list of check template IDs or array-like format. Example: "1, 2, 3" or "[1,2,3]".| No       |

### Import Checks

To import checks from a file:

```bash
qualytics checks import --datastore DATASTORE_ID_LIST [--input LOCATION_FROM_THE_EXPORT]
```

By default, it reads the checks from `./qualytics/data_checks.json`. You can specify a different input file with the `--input` option.

**Note**: Any errors encountered during the importing of checks will be logged in `./qualytics/errors.log`.

| Option       | Type | Description                                                                  | Default                       | Required |
|--------------|------|------------------------------------------------------------------------------|-------------------------------|----------|
| `--datastore`| TEXT | Comma-separated list of Datastore IDs or array-like format. Example: 1,2,3,4,5 or "[1,2,3,4,5]" | None | Yes      |
| `--input`    | TEXT | Input file path                                                              | HOME/.qualytics/data_checks.json | No       |



### Import Check Templates

You can import check templates from a file using the `checks import-templates` command:

```bash
qualytics checks import-templates [--input LOCATION_OF_CHECK_TEMPLATES]
```

By default, it reads the check templates from `./qualytics/data_checks_template.json`. You can specify a different input file with the `--input` option.

| Option    | Type | Description                  | Default                               | Required |
|-----------|------|------------------------------|---------------------------------------|----------|
| `--input` | TEXT | Input file path               | ./qualytics/data_checks_template.json | No       |

### Schedule Metadata Export

Allows you to schedule exports of metadata from your datastores using a specified crontab expression.

```bash
qualytics schedule export-metadata --crontab "CRONTAB_EXPRESSION" --datastore "DATASTORE_ID" [--containers "CONTAINER_IDS"] --options "EXPORT_OPTIONS"
```

| Option       | Type | Description                                                          | Required |
|--------------|------|----------------------------------------------------------------------|----------|
| `--crontab`  | TEXT | Crontab expression inside quotes, specifying when the task should run. Example: "0 * * * *" | Yes      |
| `--datastore`| TEXT | The datastore ID                                                     | Yes      |
| `--containers`| TEXT | Comma-separated list of container IDs or array-like format. Example: "1, 2, 3" or "[1,2,3]" | No       |
| `--options`  | TEXT | Comma-separated list of options to export or "all". Example: "anomalies, checks, field-profiles" | Yes      |

### Run a Catalog Operation on a Datastore

Allows you to trigger a catalog operation on any current datastore (requires admin permissions on the datastore).

```bash
qualytics run catalog --datastore "DATASTORE_ID_LIST" --include "INCLUDE_LIST" --prune --recreate --background
```

| Option         | Type | Description                                                                                         | Required |
|----------------|------|-----------------------------------------------------------------------------------------------------|----------|
| `--datastore`  | TEXT | Comma-separated list of Datastore IDs or array-like format. Example: 1,2,3,4,5 or "[1,2,3,4,5]"     | Yes      |
| `--include`    | TEXT | Comma-separated list of include types or array-like format. Example: "table,view" or "[table,view]" | No       |
| `--prune`      | BOOL | Prune the operation. Do not include if you want prune == false                                      | No       |
| `--recreate`   | BOOL | Recreate the operation. Do not include if you want recreate == false                                | No       |
| `--background` | BOOL | Starts the catalog but does not wait for the operation to finish                                    | No       |

### Run a Profile Operation on a Datastore

Allows you to trigger a profile operation on any current datastore (requires admin permissions on the datastore).

```bash
qualytics run profile --datastore "DATASTORE_ID_LIST" --container_names "CONTAINER_NAMES_LIST" --container_tags "CONTAINER_TAGS_LIST"
--inference_threshold "INFERENCE_THRESHOLD" --infer_as_draft --max_records_analyzed_per_partition "MAX_RECORDS_ANALYZED_PER_PARTITION"
--max_count_testing_sample "MAX_COUNT_TESTING_SAMPLE" --percent_testing_threshold "PERCENT_TESTING_THRESHOLD" --high_correlation_threshold
"HIGH_CORRELATION_THRESHOLD" --greater_than_time "GREATER_THAN_TIME" --greater_than_batch "GREATER_THAN_BATCH" --histogram_max_distinct_values
"HISTOGRAM_MAX_DISTINCT_VALUES" --background
```

| Option                                 | Type     | Description                                                                                                                                      | Required |
|----------------------------------------|----------|--------------------------------------------------------------------------------------------------------------------------------------------------|----------|
| `--datastore`                          | TEXT     | Comma-separated list of Datastore IDs or array-like format. Example: 1,2,3,4,5 or "[1,2,3,4,5]"                                                  | Yes      |
| `--container_names`                    | TEXT     | Comma-separated list of container names or array-like format. Example: "container1,container2" or "[container1,container2]"                      | No       |
| `--container_tags`                     | TEXT     | Comma-separated list of container tags or array-like format. Example: "tag1,tag2" or "[tag1,tag2]"                                               | No       |
| `--inference_threshold`                | INT      | Inference quality checks threshold in profile from 0 to 5. Do not include if inference_threshold == 0                                             | No       |
| `--infer_as_draft`                     | BOOL     | Infer all quality checks in profile as DRAFT. Do not include if you want infer_as_draft == False                                                 | No       |
| `--max_records_analyzed_per_partition` | INT      | Number of max records analyzed per partition                                                                                                     | No       |
| `--max_count_testing_sample`           | INT      | The number of records accumulated during profiling for validation of inferred checks. Capped at 100,000                                           | No       |
| `--percent_testing_threshold`          | FLOAT    | Percent of testing threshold                                                                                                                     | No       |
| `--high_correlation_threshold`         | FLOAT    | Number of correlation threshold                                                                                                                  | No       |
| `--greater_than_time`                  | DATETIME | Only include rows where the incremental field's value is greater than this time. Use one of these formats %Y-%m-%dT%H:%M:%S or %Y-%m-%d %H:%M:%S | No       |
| `--greater_than_batch`                 | FLOAT    | Only include rows where the incremental field's value is greater than this number                                                                | No       |
| `--histogram_max_distinct_values`      | INT      | Number of max distinct values in the histogram                                                                                                   | No       |
| `--background`                         | BOOL     | Starts the profile operation but does not wait for the operation to finish                                                                       | No       |


### Run a Scan Operation on a Datastore

Allows you to trigger a scan operation on a datastore (requires admin permissions on the datastore).

```bash
qualytics run scan --datastore "DATASTORE_ID_LIST" --container_names "CONTAINER_NAMES_LIST" --container_tags "CONTAINER_TAGS_LIST"
--incremental --remediation --max_records_analyzed_per_partition "MAX_RECORDS_ANALYZED_PER_PARTITION" --enrichment_source_record_limit
--greater_than_time "GREATER_THAN_TIME" --greater_than_batch "GREATER_THAN_BATCH" --background
```

| Option                                 | Type     | Description                                                                                                                                      | Required |
|----------------------------------------|----------|--------------------------------------------------------------------------------------------------------------------------------------------------|----------|
| `--datastore`                          | TEXT     | Comma-separated list of Datastore IDs or array-like format. Example: 1,2,3,4,5 or "[1,2,3,4,5]"                                                  | Yes      |
| `--container_names`                    | TEXT     | Comma-separated list of container names or array-like format. Example: "container1,container2" or "[container1,container2]"                      | No       |
| `--container_tags`                     | TEXT     | Comma-separated list of container tags or array-like format. Example: "tag1,tag2" or "[tag1,tag2]"                                                | No       |
| `--incremental`                        | BOOL     | Process only new or updated records since the last incremental scan                                                                              | No       |
| `--remediation`                        | TEXT     | Replication strategy for source tables in the enrichment datastore. Either 'append', 'overwrite', or 'none'                                      | No       |
| `--max_records_analyzed_per_partition` | INT      | Number of max records analyzed per partition. Value must be greater than or equal to 0                                                           | No       |
| `--enrichment_source_record_limit`     | INT      | Limit of enrichment source records per run. Value must be greater than or equal to -1                                                            | No       |
| `--greater_than_time`                  | DATETIME | Only include rows where the incremental field's value is greater than this time. Use one of these formats %Y-%m-%dT%H:%M:%S or %Y-%m-%d %H:%M:%S | No       |
| `--greater_than_batch`                 | FLOAT    | Only include rows where the incremental field's value is greater than this number                                                                | No       |
| `--background`                         | BOOL     | Starts the scan operation but does not wait for the operation to finish                                                                          | No       |

### Check Operation Status

Allows a user to check an operation's status. Useful if a user triggered an operation but had it running in the background.

```bash
qualytics operation check_status --ids "OPERATION_IDS"
```

| Option  | Type     | Description                                                                                                               | Required |
|---------|----------|---------------------------------------------------------------------------------------------------------------------------|----------|
| `--ids` | TEXT     | Comma-separated list of Operation IDs or array-like format. Example: 1,2,3,4,5 or "[1,2,3,4,5]"                           | Yes      |
