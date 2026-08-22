package kafka

import (
	"context"
	"os"

	"github.com/segmentio/kafka-go"
)

// NewOrderWriter publishes every accepted order for downstream consumers.
func NewOrderWriter(brokers []string) *kafka.Writer {
	return kafka.NewWriter(kafka.WriterConfig{
		Brokers: brokers,
		Topic:   "orders.created",
	})
}

// PublishOrder keys on the order id so a single order stays partition-ordered.
func PublishOrder(ctx context.Context, w *kafka.Writer, orderID string, payload []byte) error {
	return w.WriteMessages(ctx, kafka.Message{
		Topic: "orders.created",
		Key:   []byte(orderID),
		Value: payload,
	})
}

func brokerList() string {
	return os.Getenv("KAFKA_BROKER")
}
