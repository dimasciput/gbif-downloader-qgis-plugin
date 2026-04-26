package main

import (
	"database/sql"
	"flag"
	"fmt"
	"log"
	"os"
	"strings"

	_ "github.com/marcboeker/go-duckdb"
)

func main() {
	input := flag.String("input", "occurrences.geoparquet", "Path to GeoParquet file")
	query := flag.String("q", "", "SQL query to run (use 'tbl' as the table alias)")
	flag.Parse()

	if _, err := os.Stat(*input); err != nil {
		log.Fatalf("input file not found: %s", *input)
	}

	db, err := sql.Open("duckdb", "")
	if err != nil {
		log.Fatalf("failed to open duckdb: %v", err)
	}
	defer db.Close()

	for _, q := range []string{"INSTALL spatial", "LOAD spatial"} {
		if _, err := db.Exec(q); err != nil {
			log.Fatalf("%s: %v", q, err)
		}
	}

	viewSQL := fmt.Sprintf("CREATE VIEW tbl AS SELECT * FROM read_parquet(%q)", *input)
	if _, err := db.Exec(viewSQL); err != nil {
		log.Fatalf("failed to create view: %v", err)
	}

	finalQuery := *query
	if finalQuery == "" {
		finalQuery = `
			SELECT gbifID, species, countryCode,
			       ST_AsText(geometry) AS wkt
			FROM tbl
			LIMIT 10
		`
	}

	rows, err := db.Query(finalQuery)
	if err != nil {
		log.Fatalf("query failed: %v", err)
	}
	defer rows.Close()

	cols, _ := rows.Columns()
	fmt.Println(strings.Join(cols, "\t"))
	fmt.Println(strings.Repeat("-", 80))

	vals := make([]any, len(cols))
	ptrs := make([]any, len(cols))
	for i := range vals {
		ptrs[i] = &vals[i]
	}

	for rows.Next() {
		if err := rows.Scan(ptrs...); err != nil {
			log.Fatalf("scan: %v", err)
		}
		parts := make([]string, len(cols))
		for i, v := range vals {
			if v == nil {
				parts[i] = "NULL"
			} else {
				parts[i] = fmt.Sprintf("%v", v)
			}
		}
		fmt.Println(strings.Join(parts, "\t"))
	}
}
