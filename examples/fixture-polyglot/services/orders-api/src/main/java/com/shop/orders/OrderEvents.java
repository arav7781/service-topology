package com.shop.orders;

import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Component;

@Component
public class OrderEvents {
    private final KafkaTemplate<String, Object> events;

    public OrderEvents(KafkaTemplate<String, Object> events) {
        this.events = events;
    }

    public void placed(Order order) {
        events.send(Topics.ORDER_PLACED, order.id(), order);
        events.send(Topics.ORDER_AUDIT, order.id(), order);
    }
}
