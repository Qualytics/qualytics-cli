# Computed Fields

Computed fields are user-defined derived columns that apply transformations to existing fields in a container. They are created through the Qualytics API and are fully supported in the config export/import pipeline.

## How Computed Fields Work

A computed field defines a transformation on one or more source fields within a container. After creation, the container must be profiled to materialize the field record, after which quality checks can target it.

## Transformation Types

| Type | Description | Source Fields | Key Properties |
|------|-------------|---------------|----------------|
| `cast` | Cast to a different data type | 1 field | `target_type` (Spark SQL type), `format` (optional date pattern) |
| `cleanedEntityName` | Strip business suffixes from entity names | 1 string field | `drop_from_suffix/prefix/interior`, `terms_to_drop/ignore` |
| `convertFormattedNumeric` | Strip formatting from numeric strings | 1 string field | (none) |
| `customExpression` | Arbitrary Spark SQL expression | none (must be null) | `column_expression` (required) |

## In Config Export/Import

Computed fields are automatically included when you export configuration. They live alongside their parent container:

```
datastores/
  order_analytics/
    containers/
      accounts/
        _container.yaml
        computed_fields/
          cleaned_company_name.yaml
          full_name.yaml
```

### Exported YAML

```yaml
# computed_fields/cleaned_company_name.yaml
name: cleaned_company_name
transformation: cleanedEntityName
source_fields:
  - company_name
properties:
  drop_from_suffix: true
  drop_from_prefix: false
  drop_from_interior: false
  terms_to_drop:
    - Inc.
    - Corp.
    - LLC
  terms_to_ignore: []
```

```yaml
# computed_fields/full_name.yaml
name: full_name
transformation: customExpression
source_fields: null
properties:
  column_expression: "CONCAT(first_name, ' ', last_name)"
```

```yaml
# computed_fields/amount_int.yaml
name: amount_int
transformation: cast
source_fields:
  - amount_str
properties:
  target_type: integer
```

### Import behavior

- Computed fields are imported **after containers** and **before quality checks**
- Matched by `name` within the parent container
- **Existing field** -- updated via PUT
- **New field** -- created via POST
- The container must exist in the target environment first
- After import, profile the container to materialize the field records

### Selective export/import

```bash
# Export only computed fields
qualytics config export --datastore-id 1 --include computed_fields

# Import only computed fields (containers must already exist)
qualytics config import --input ./qualytics-config --include computed_fields
```

## Fields Stripped on Export

The following internal fields are removed to keep the YAML portable:

- `id` -- auto-generated
- `container_id` -- resolved by container name on import
- `last_editor_id` / `last_editor` -- operational metadata
