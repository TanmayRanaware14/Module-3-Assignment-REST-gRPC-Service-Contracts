import logging
import sys
import time
import uuid
from pathlib import Path

import grpc
from flask import Flask, jsonify, request

sys.path.insert(0, str(Path(__file__).resolve().parent))

import inventory_pb2
import inventory_pb2_grpc

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
app = Flask(__name__)

INVENTORY_TARGET = "127.0.0.1:50051"
# Per-call deadline for Order -> Inventory. Longer inventory work exceeds it.
GRPC_DEADLINE_SECONDS = 1.0

channel = grpc.insecure_channel(INVENTORY_TARGET)
stub = inventory_pb2_grpc.InventoryServiceStub(channel)


@app.get("/health")
def health():
    return jsonify(status="ok", service="order-grpc")


@app.post("/orders")
def create_order():
    start = time.time()
    body = request.get_json(silent=True) or {}
    item_id = body.get("item_id")
    quantity = body.get("quantity")

    if not isinstance(item_id, str) or not item_id:
        return jsonify(error="item_id is required"), 400
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        return jsonify(error="quantity must be a positive integer"), 400

    grpc_request = inventory_pb2.CheckInventoryRequest(
        item_id=item_id,
        quantity=quantity,
        delay_seconds=float(body.get("delay_seconds", 0)),
    )

    try:
        inventory = stub.CheckInventory(grpc_request, timeout=GRPC_DEADLINE_SECONDS)
    except grpc.RpcError as exc:
        code = exc.code()
        details = exc.details()
        latency_ms = int((time.time() - start) * 1000)
        logging.info(
            f"service=order-grpc endpoint=/orders grpc_status={code.name} "
            f"item_id={item_id} detail={details} order_service=running latency_ms={latency_ms}"
        )
        if code == grpc.StatusCode.DEADLINE_EXCEEDED:
            return (
                jsonify(
                    status="failed",
                    reason="inventory deadline exceeded",
                    grpc_status=code.name,
                    deadline_seconds=GRPC_DEADLINE_SECONDS,
                    order_service="running",
                ),
                504,
            )
        if code == grpc.StatusCode.NOT_FOUND:
            http_status = 404
        elif code == grpc.StatusCode.FAILED_PRECONDITION:
            http_status = 409
        else:
            http_status = 502
        return (
            jsonify(
                status="rejected",
                reason=details,
                grpc_status=code.name,
                item_id=item_id,
                quantity=quantity,
                order_service="running",
            ),
            http_status,
        )

    order_id = f"ord-{uuid.uuid4().hex[:8]}"
    logging.info(
        f"service=order-grpc endpoint=/orders grpc_status=OK order_id={order_id} "
        f"item_id={item_id} quantity={quantity} available_quantity={inventory.available_quantity} "
        f"latency_ms={int((time.time() - start) * 1000)}"
    )
    return (
        jsonify(
            order_id=order_id,
            item_id=item_id,
            quantity=quantity,
            status="accepted",
            grpc_status="OK",
            inventory={
                "item_id": inventory.item_id,
                "available": inventory.available,
                "available_quantity": inventory.available_quantity,
            },
        ),
        201,
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=6002, threaded=True)
