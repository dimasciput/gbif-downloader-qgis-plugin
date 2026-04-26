# gbif-project-2026

Convert GBIF Darwin Core occurrence data (TSV) to GeoParquet, and query it with DuckDB.

## Requirements

### Go

Install Go 1.22+:

```bash
# Fedora / RHEL
sudo dnf install golang

# Or download from https://go.dev/dl/
# then add to your shell profile:
export PATH=$PATH:/usr/local/go/bin
```

Verify: `go version`

### GCC (required by go-duckdb — it uses CGO)

```bash
# Fedora / RHEL
sudo dnf install gcc

# Ubuntu / Debian
sudo apt install build-essential
```

### DuckDB CLI (optional — for ad-hoc querying outside Go)

The Go tools embed DuckDB, so the CLI is optional. Install it if you want a REPL:

```bash
# Fedora / RHEL — via the official binary
curl -fL https://github.com/duckdb/duckdb/releases/latest/download/duckdb_cli-linux-amd64.zip \
  -o /tmp/duckdb.zip
unzip /tmp/duckdb.zip -d /tmp
sudo mv /tmp/duckdb /usr/local/bin/duckdb
chmod +x /usr/local/bin/duckdb
```

Verify: `duckdb --version`

## Setup

```bash
go mod tidy        # downloads go-duckdb and its DuckDB amalgamation
```

> First run takes ~2 minutes — go-duckdb compiles DuckDB from source via CGO.

## Usage

### Convert TSV → GeoParquet

```bash
go run ./cmd/convert \
  -input  gbif_sample_data/occurrence.txt \
  -output occurrences.geoparquet
```

This will:
1. Load DuckDB's `spatial` extension
2. Read the tab-separated occurrence file
3. Build a `geometry` column (WKB point) from `decimalLongitude` / `decimalLatitude`
4. Write a GeoParquet file with embedded CRS metadata (EPSG:4326)

### Query the GeoParquet

Run the default preview (10 rows):

```bash
go run ./cmd/query -input occurrences.geoparquet
```

Run a custom SQL query (use `tbl` as the table name):

```bash
go run ./cmd/query -input occurrences.geoparquet \
  -q "SELECT countryCode, COUNT(*) AS n FROM tbl GROUP BY countryCode ORDER BY n DESC LIMIT 10"
```

Spatial query example:

```bash
go run ./cmd/query -input occurrences.geoparquet \
  -q "SELECT species, ST_AsText(geometry) AS wkt FROM tbl WHERE countryCode = 'AU' LIMIT 5"
```

### DuckDB CLI (optional)

```bash
duckdb
```

```sql
LOAD spatial;
SELECT gbifID, species, ST_AsText(geometry) AS wkt
FROM read_parquet('occurrences.geoparquet')
WHERE countryCode = 'AU'
LIMIT 10;
```

## Project structure

```
.
├── cmd/
│   ├── convert/main.go   -- TSV → GeoParquet pipeline
│   └── query/main.go     -- query GeoParquet via SQL
├── gbif_sample_data/
│   └── occurrence.txt    -- GBIF Darwin Core TSV (not committed)
├── go.mod
└── README.md
```
