package main

import (
	"log"
	"net/http"
	"os"
)

var ordersURL = os.Getenv("ORDERS_API_URL")

func main() {
	http.HandleFunc("/charges", handleCharge)
	log.Fatal(http.ListenAndServe(":8080", nil))
}

// handleCharge re-reads the order to check the amount - a callback into its caller.
func handleCharge(w http.ResponseWriter, r *http.Request) {
	resp, err := http.Get(ordersURL + "/orders/" + r.URL.Query().Get("order"))
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()
	capture(r.Context(), r.URL.Query().Get("order"))
}
