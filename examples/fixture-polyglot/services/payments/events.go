package main

import (
	"context"
	"net/http"
	"strings"

	amqp "github.com/rabbitmq/amqp091-go"
)

var ch *amqp.Channel

func capture(ctx context.Context, orderID string) {
	_, _ = http.Post("https://api.adyen.com/v71/payments", "application/json", strings.NewReader(orderID))
	_ = ch.PublishWithContext(ctx, "payments", "payment.captured", false, false, amqp.Publishing{
		Body: []byte(orderID),
	})
}
