"""Stock check over gRPC.

The generated stubs are built at deploy time from a .proto that lives in a
different repository, so nothing here proves which service answers the call.
"""

import grpc

from .generated import inventory_pb2_grpc


def reserve_stock(channel_target, sku, quantity):
    channel = grpc.insecure_channel(channel_target)
    stub = inventory_pb2_grpc.InventoryServiceStub(channel)
    return stub.Reserve(sku=sku, quantity=quantity)
