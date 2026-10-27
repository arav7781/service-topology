package com.shop.orders;

import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.PostMapping;

@FeignClient(name = "payments")
public interface PaymentsClient {
    @PostMapping("/charges")
    Charge charge(ChargeRequest request);
}
