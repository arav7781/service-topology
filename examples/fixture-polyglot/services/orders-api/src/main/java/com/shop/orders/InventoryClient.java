package com.shop.orders;

import io.grpc.ManagedChannelBuilder;
import org.springframework.beans.factory.annotation.Value;
import shop.inventory.InventoryGrpc;
import shop.inventory.ReserveRequest;

public class InventoryClient {
    private final InventoryGrpc.InventoryBlockingStub stub;

    public InventoryClient(@Value("${inventory.address}") String address) {
        var channel = ManagedChannelBuilder.forTarget(address).usePlaintext().build();
        this.stub = InventoryGrpc.newBlockingStub(channel);
    }

    public boolean reserve(String sku, int quantity) {
        return stub.reserve(ReserveRequest.newBuilder().setSku(sku).setQuantity(quantity).build()).getOk();
    }
}
