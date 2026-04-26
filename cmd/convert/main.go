package main

import (
	"database/sql"
	"flag"
	"fmt"
	"log"
	"os"

	_ "github.com/marcboeker/go-duckdb"
)

func main() {
	input := flag.String("input", "gbif_sample_data/occurrence.txt", "Path to GBIF occurrence TSV file")
	output := flag.String("output", "occurrences.geoparquet", "Path to output GeoParquet file")
	flag.Parse()

	if _, err := os.Stat(*input); err != nil {
		log.Fatalf("input file not found: %s", *input)
	}

	db, err := sql.Open("duckdb", "")
	if err != nil {
		log.Fatalf("failed to open duckdb: %v", err)
	}
	defer db.Close()

	steps := []string{
		"INSTALL spatial",
		"LOAD spatial",
	}

	copySQL := fmt.Sprintf(`
		COPY (
			SELECT
				*,
				ST_Point(
					TRY_CAST(decimalLongitude AS DOUBLE),
					TRY_CAST(decimalLatitude  AS DOUBLE)
				) AS geometry
			FROM read_csv(%q,
				delim     = '\t',
				header    = true,
				nullstr   = '',
				all_varchar = true
			)
			WHERE TRY_CAST(decimalLatitude  AS DOUBLE) IS NOT NULL
			  AND TRY_CAST(decimalLongitude AS DOUBLE) IS NOT NULL
		)
		TO %q (FORMAT PARQUET)
	`, *input, *output)

	steps = append(steps, copySQL)

	for _, q := range steps {
		if _, err := db.Exec(q); err != nil {
			log.Fatalf("query failed:\n%s\n\nerror: %v", q, err)
		}
	}

	fmt.Printf("written: %s\n", *output)
}
