import os
import time
import logging

from flask import Flask, jsonify, request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
app = Flask(__name__)

# In-memory stock. quantity must be <= the value to be available.
STOCK = {
    "item-1": 10,
    "item-2": 5,
}

# Temporary slowdown used to demonstrate the Order service timeout.
# A per-request delay_seconds overrides this value.
DEFAULT_DELAY_SECONDS = float(os.environ.get("INVENTORY_DELAY_SECONDS", "0"))


def _delay_seconds(body):
    if "delay_seconds" in body:
        return float(body["delay_seconds"])
    return DEFAULT_DELAY_SECONDS


@app.get("/health")
def health():
    return jsonify(status="ok", service="inventory-rest")


@app.post("/inventory/check")
def check_inventory():
    start = time.time()
    body = request.get_json(silent=True) or {}
    item_id = body.get("item_id")
    quantity = body.get("quantity")

    if not isinstance(item_id, str) or not item_id:
        return jsonify(error="item_id is required"), 400
    if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
        return jsonify(error="quantity must be a positive integer"), 400

    delay = _delay_seconds(body)
    if delay < 0:
        return jsonify(error="delay_seconds must be >= 0"), 400
    if delay > 0:
        logging.info(
            f"service=inventory-rest endpoint=/inventory/check action=delay delay_seconds={delay}"
        )
        time.sleep(delay)

    if item_id not in STOCK:
        logging.info(
            f"service=inventory-rest endpoint=/inventory/check status=404 item_id={item_id} "
            f"latency_ms={int((time.time() - start) * 1000)}"
        )
        return jsonify(item_id=item_id, available=False, error="item not found"), 404

    available_quantity = STOCK[item_id]
    if quantity > available_quantity:
        logging.info(
            f"service=inventory-rest endpoint=/inventory/check status=409 item_id={item_id} "
            f"quantity={quantity} available_quantity={available_quantity} "
            f"latency_ms={int((time.time() - start) * 1000)}"
        )
        return (
            jsonify(
                item_id=item_id,
                available=False,
                available_quantity=available_quantity,
                error="insufficient quantity",
            ),
            409,
        )

    logging.info(
        f"service=inventory-rest endpoint=/inventory/check status=200 item_id={item_id} "
        f"quantity={quantity} available_quantity={available_quantity} "
        f"latency_ms={int((time.time() - start) * 1000)}"
    )
    return jsonify(
        item_id=item_id,
        available=True,
        available_quantity=available_quantity,
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=6001, threaded=True)
