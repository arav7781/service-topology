package main

import (
	"net/http"
	"strings"
)

// chargeCard talks to the payment provider directly; there is no gateway.
func chargeCard(client *http.Client, token string) (*http.Response, error) {
	req, err := http.NewRequest("POST", "https://api.stripe.com/v1/charges", strings.NewReader(token))
	if err != nil {
		return nil, err
	}
	return client.Do(req)
}
