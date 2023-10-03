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
    pip install qualytics
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
qualytics checks export --datastore DATASTORE_ID
```

By default, it saves the exported checks to `./qualytics/data_checks.json`. However, you can specify a different output path with the `--output` option.


| Option        | Type     | Description                  | Default                            | Required |
|---------------|----------|------------------------------|------------------------------------|----------|
| `--datastore` | INTEGER  | Datastore ID                 | None                               | Yes      |
| `--output`    | TEXT     | Output file path             | ./qualytics/data_checks.json   | No       |


### Import Checks

To import checks from a file:


```bash
qualytics checks import --datastore DATASTORE_ID_LIST
```

By default, it reads the checks from `./qualytics/data_checks.json`. You can specify a different input file with the `--input` option.

**Note**: Any errors encountered during the importing of checks will be logged in `./qualytics/errors.log`.

| Option       | Type | Description                                                          | Default                           | Required |
|--------------|------|----------------------------------------------------------------------|-----------------------------------|----------|
| `--datastore`| TEXT | Comma-separated list of Datastore IDs or array-like format. Example: 1,2,3,4,5 or "[1,2,3,4,5]" | None                              | Yes      |
| `--input`    | TEXT | Input file path  