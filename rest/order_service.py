import logging
import time
import uuid

import requests
from flask import Flask, jsonify, request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
app = Flask(__name__)

INVENTORY_URL = "http://127.0.0.1:6001/inventory/check"
# Order -> Inventory timeout. A slower inventory response is treated as a failure.
INVENTORY_TIMEOUT_SECONDS = 1.0


@app.get("/health")
def health():
    return jsonify(status="ok", service="order-rest")


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

    payload = {"item_id": item_id, "quantity": quantity}
    if "delay_seconds" in body:
        payload["delay_seconds"] = body["delay_seconds"]

    try:
        response = requests.post(INVENTORY_URL, json=payload, timeout=INVENTORY_TIMEOUT_SECONDS)
    except requests.Timeout:
        logging.info(
            f"service=order-rest endpoint=/orders status=timeout item_id={item_id} "
            f"timeout_seconds={INVENTORY_TIMEOUT_SECONDS} order_service=running "
            f"latency_ms={int((time.time() - start) * 1000)}"
        )
        return (
            jsonify(
                status="failed",
                reason="inventory service timed out",
                timeout_seconds=INVENTORY_TIMEOUT_SECONDS,
                order_service="running",
            ),
            504,
        )
    except requests.RequestException as exc:
        logging.info(
            f'service=order-rest endpoint=/orders status=error error="{exc}" '
            f"order_service=running latency_ms={int((time.time() - start) * 1000)}"
        )
        return (
            jsonify(
                status="failed",
                reason="inventory service unavailable",
                error=str(exc),
                order_service="running",
            ),
            503,
        )

    data = response.json()
    if response.status_code == 200 and data.get("available"):
        order_id = f"ord-{uuid.uuid4().hex[:8]}"
        logging.info(
            f"service=order-rest endpoint=/orders status=accepted order_id={order_id} "
            f"item_id={item_id} quantity={quantity} latency_ms={int((time.time() - start) * 1000)}"
        )
        return (
            jsonify(
                order_id=order_id,
                item_id=item_id,
                quantity=quantity,
                status="accepted",
                inventory=data,
            ),
            201,
        )

    reason = data.get("error", "item unavailable")
    status = 404 if response.status_code == 404 else 409
    logging.info(
        f"service=order-rest endpoint=/orders status=rejected item_id={item_id} "
        f"inventory_status={response.status_code} reason={reason} order_service=running "
        f"latency_ms={int((time.time() - start) * 1000)}"
    )
    return (
        jsonify(
            status="rejected",
            reason=reason,
            item_id=item_id,
            quantity=quantity,
            inventory_status=response.status_code,
            order_service="running",
        ),
        status,
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=6000, threaded=True)
