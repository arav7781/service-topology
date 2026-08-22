// Package main is the orders service entrypoint. Fixture code: it does not run.
package main

import (
	"database/sql"
	"log"
	"net/http"
	"os"
)

const defaultDSN = "postgres://orders:secret@orders-db:5432/orders?sslmode=disable"

func main() {
	dsn := os.Getenv("POSTGRES_DSN")
	if dsn == "" {
		dsn = defaultDSN
	}
	db, err := sql.Open("postgres", dsn)
	if err != nil {
		log.Fatal(err)
	}
	defer db.Close()

	http.HandleFunc("/orders/", handleOrder)
	log.Fatal(http.ListenAndServe(":8080", nil))
}

func handleOrder(w http.ResponseWriter, r *http.Request) {
	w.WriteHeader(http.StatusOK)
}
