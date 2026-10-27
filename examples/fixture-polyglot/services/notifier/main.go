package main

import (
	"os"

	"github.com/nats-io/nats.go"
)

func main() {
	nc, _ := nats.Connect(os.Getenv("NATS_URL"))
	nc.Subscribe("user.notify", func(m *nats.Msg) {
		alertTenant(nc, string(m.Data), m.Data)
	})
	select {}
}

// The subject depends on the tenant - it cannot be known without running this.
func alertTenant(nc *nats.Conn, tenantID string, data []byte) {
	nc.Publish("tenant."+tenantID+".alerts", data)
}
