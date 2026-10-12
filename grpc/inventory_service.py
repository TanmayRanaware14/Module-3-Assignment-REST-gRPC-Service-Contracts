import os
import sys
import time
import logging
from concurrent import futures
from pathlib import Path

import grpc

sys.path.insert(0, str(Path(__file__).resolve().parent))

import inventory_pb2
import inventory_pb2_grpc

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

STOCK = {
    "item-1": 10,
    "item-2": 5,
}

DEFAULT_DELAY_SECONDS = float(os.environ.get("INVENTORY_DELAY_SECONDS", "0"))


def _wait(context, delay_seconds):
    """Sleep up to delay_seconds, but stop if the client deadline cancels the call."""
    if delay_seconds <= 0:
        return True
    logging.info(f"service=inventory-grpc method=CheckInventory action=delay delay_seconds={delay_seconds}")
    deadline = time.time() + delay_seconds
    while time.time() < deadline:
        if not context.is_active():
            logging.info(
                "service=inventory-grpc method=CheckInventory status=DEADLINE_EXCEEDED "
                "detail=client cancelled the slow call"
            )
            return False
        time.sleep(0.05)
    return True


class InventoryService(inventory_pb2_grpc.InventoryServiceServicer):
    def CheckInventory(self, request, context):
        start = time.time()
        delay = request.delay_seconds if request.delay_seconds else DEFAULT_DELAY_SECONDS
        if delay < 0:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "delay_seconds must be >= 0")

        if not _wait(context, delay):
            return inventory_pb2.CheckInventoryResponse()

        if request.quantity <= 0:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "quantity must be a positive integer")

        if request.item_id not in STOCK:
            logging.info(
                f"service=inventory-grpc method=CheckInventory status=NOT_FOUND "
                f"item_id={request.item_id} latency_ms={int((time.time() - start) * 1000)}"
            )
            context.abort(grpc.StatusCode.NOT_FOUND, f"item {request.item_id} not found")

        available_quantity = STOCK[request.item_id]
        if request.quantity > available_quantity:
            logging.info(
                f"service=inventory-grpc method=CheckInventory status=FAILED_PRECONDITION "
                f"item_id={request.item_id} quantity={request.quantity} "
                f"available_quantity={available_quantity} "
                f"latency_ms={int((time.time() - start) * 1000)}"
            )
            context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                (
                    f"insufficient quantity for {request.item_id}: "
                    f"requested {request.quantity}, available {available_quantity}"
                ),
            )

        logging.info(
            f"service=inventory-grpc method=CheckInventory status=OK item_id={request.item_id} "
            f"quantity={request.quantity} available_quantity={available_quantity} "
            f"latency_ms={int((time.time() - start) * 1000)}"
        )
        return inventory_pb2.CheckInventoryResponse(
            item_id=request.item_id,
            available=True,
            available_quantity=available_quantity,
        )


def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    inventory_pb2_grpc.add_InventoryServiceServicer_to_server(InventoryService(), server)
    server.add_insecure_port("127.0.0.1:50051")
    server.start()
    logging.info("service=inventory-grpc listening=127.0.0.1:50051")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
