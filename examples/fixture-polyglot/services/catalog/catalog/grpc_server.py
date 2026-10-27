from concurrent import futures

import grpc

from . import inventory_pb2_grpc


class InventoryServicer(inventory_pb2_grpc.InventoryServicer):
    def Reserve(self, request, context):
        return None


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    inventory_pb2_grpc.add_InventoryServicer_to_server(InventoryServicer(), server)
    server.add_insecure_port("[::]:50051")
    server.start()
