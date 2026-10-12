# Module 3: REST and gRPC Service Contracts

Two services, implemented twice:

| Role | REST | gRPC |
|------|------|------|
| **Order** | `http://127.0.0.1:6000` | `http://127.0.0.1:6002` (accepts the order, then calls Inventory over gRPC) |
| **Inventory** | `http://127.0.0.1:6001` | `127.0.0.1:50051` |

The Order service accepts an order with `item_id` and `quantity`. It asks the Inventory service whether that item and quantity are available. The REST version does that with JSON over HTTP. The gRPC version does the same check with the contract in `grpc/inventory.proto`.

In-memory stock:

| `item_id` | Available quantity |
|-----------|--------------------|
| `item-1` | 10 |
| `item-2` | 5 |

Order gives up on Inventory after **1 second** in both versions (`timeout=1.0` for REST, a 1 second gRPC deadline). A request can pass `delay_seconds` so Inventory waits before answering. `delay_seconds: 3` is longer than that 1 second limit and is how the timeout and deadline cases are demonstrated.

## Prerequisites

- Python 3.9+
- `curl`

## Setup

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Generated stubs `grpc/inventory_pb2.py` and `grpc/inventory_pb2_grpc.py` are already in the repo. Regenerate them after editing the proto file:

```bash
python -m grpc_tools.protoc -I grpc --python_out=grpc --grpc_python_out=grpc grpc/inventory.proto
```

Leave `.venv` activated in every terminal below. REST and gRPC use different ports, so both pairs can run at the same time.

## Run the REST version

Terminal 1, Inventory:

```bash
python rest/inventory_service.py
```

Terminal 2, Order:

```bash
python rest/order_service.py
```

`POST /inventory/check` on port 6001 reads JSON and returns JSON. Order calls it with a 1 second timeout.

| Inventory result | HTTP status |
|------------------|-------------|
| Requested quantity is in stock | `200` |
| Item does not exist | `404` |
| Item exists, quantity is too high | `409` |
| Inventory is slower than 1 second | Order returns `504` |

### Successful REST request and response

```bash
curl -i -X POST http://127.0.0.1:6000/orders \
  -H 'Content-Type: application/json' \
  -d '{"item_id":"item-1","quantity":2}'
```

```text
HTTP/1.1 201 CREATED
Content-Type: application/json

{"inventory":{"available":true,"available_quantity":10,"item_id":"item-1"},"item_id":"item-1","order_id":"ord-a44ce399","quantity":2,"status":"accepted"}
```

Order log:

```text
service=order-rest endpoint=/orders status=accepted order_id=ord-a44ce399 item_id=item-1 quantity=2 latency_ms=7
```

Inventory log:

```text
service=inventory-rest endpoint=/inventory/check status=200 item_id=item-1 quantity=2 available_quantity=10 latency_ms=0
```

A quantity that is too large is rejected with `409` and the Order process stays up:

```bash
curl -i -X POST http://127.0.0.1:6000/orders \
  -H 'Content-Type: application/json' \
  -d '{"item_id":"item-1","quantity":100}'
```

```text
HTTP/1.1 409 CONFLICT

{"inventory_status":409,"item_id":"item-1","order_service":"running","quantity":100,"reason":"insufficient quantity","status":"rejected"}
```

### REST timeout handling

Inventory is told to wait 3 seconds, which is longer than Order's 1 second timeout:

```bash
curl -i -X POST http://127.0.0.1:6000/orders \
  -H 'Content-Type: application/json' \
  -d '{"item_id":"item-1","quantity":2,"delay_seconds":3}'
```

```text
HTTP/1.1 504 GATEWAY TIMEOUT

{"order_service":"running","reason":"inventory service timed out","status":"failed","timeout_seconds":1.0}
```

Order log (`latency_ms=1003`, then the process is still serving):

```text
service=order-rest endpoint=/orders status=timeout item_id=item-1 timeout_seconds=1.0 order_service=running latency_ms=1003
```

Inventory log. The delay starts, and the HTTP response is only written after the full 3 seconds, which is after Order has already returned `504`:

```text
service=inventory-rest endpoint=/inventory/check action=delay delay_seconds=3.0
service=inventory-rest endpoint=/inventory/check status=200 item_id=item-1 quantity=2 available_quantity=10 latency_ms=3005
```

### Order stays running after the REST timeout

Immediately after the `504`:

```bash
curl -i http://127.0.0.1:6000/health
```

```text
HTTP/1.1 200 OK

{"service":"order-rest","status":"ok"}
```

```bash
curl -i -X POST http://127.0.0.1:6000/orders \
  -H 'Content-Type: application/json' \
  -d '{"item_id":"item-2","quantity":1}'
```

```text
HTTP/1.1 201 CREATED

{"inventory":{"available":true,"available_quantity":5,"item_id":"item-2"},"item_id":"item-2","order_id":"ord-464c7e7f","quantity":1,"status":"accepted"}
```

Order log after the timeout, including the next health check and the next accepted order:

```text
service=order-rest endpoint=/orders status=timeout item_id=item-1 timeout_seconds=1.0 order_service=running latency_ms=1003
127.0.0.1 - - [12/Oct/2026 11:09:34] "GET /health HTTP/1.1" 200 -
service=order-rest endpoint=/orders status=accepted order_id=ord-464c7e7f item_id=item-2 quantity=1 latency_ms=2
```

## Run the gRPC version

The contract is `grpc/inventory.proto`: `InventoryService.CheckInventory`. Order on port 6002 accepts the same JSON order body, then calls Inventory at `127.0.0.1:50051` with a **1 second deadline** (`timeout=1.0` on the stub).

Terminal 3, Inventory:

```bash
python grpc/inventory_service.py
```

Terminal 4, Order:

```bash
python grpc/order_service.py
```

| Inventory result | gRPC status | Order HTTP status |
|------------------|-------------|-------------------|
| Requested quantity is in stock | `OK` | `201` |
| Item does not exist | `NOT_FOUND` | `404` |
| Item exists, quantity is too high | `FAILED_PRECONDITION` | `409` |
| Call exceeds the 1 second deadline | `DEADLINE_EXCEEDED` | `504` |

### Successful gRPC request and response

```bash
curl -i -X POST http://127.0.0.1:6002/orders \
  -H 'Content-Type: application/json' \
  -d '{"item_id":"item-1","quantity":2}'
```

```text
HTTP/1.1 201 CREATED

{"grpc_status":"OK","inventory":{"available":true,"available_quantity":10,"item_id":"item-1"},"item_id":"item-1","order_id":"ord-146875bb","quantity":2,"status":"accepted"}
```

Order log:

```text
service=order-grpc endpoint=/orders grpc_status=OK order_id=ord-146875bb item_id=item-1 quantity=2 available_quantity=10 latency_ms=1
```

Inventory log:

```text
service=inventory-grpc method=CheckInventory status=OK item_id=item-1 quantity=2 available_quantity=10 latency_ms=0
```

When the item is unavailable, Inventory returns `FAILED_PRECONDITION` instead of a normal response:

```bash
curl -i -X POST http://127.0.0.1:6002/orders \
  -H 'Content-Type: application/json' \
  -d '{"item_id":"item-1","quantity":100}'
```

```text
HTTP/1.1 409 CONFLICT

{"grpc_status":"FAILED_PRECONDITION","item_id":"item-1","order_service":"running","quantity":100,"reason":"insufficient quantity for item-1: requested 100, available 10","status":"rejected"}
```

Inventory log:

```text
service=inventory-grpc method=CheckInventory status=FAILED_PRECONDITION item_id=item-1 quantity=100 available_quantity=10 latency_ms=0
```

An unknown item returns `NOT_FOUND` (`item item-999 not found`).

### gRPC deadline handling

```bash
curl -i -X POST http://127.0.0.1:6002/orders \
  -H 'Content-Type: application/json' \
  -d '{"item_id":"item-1","quantity":2,"delay_seconds":3}'
```

```text
HTTP/1.1 504 GATEWAY TIMEOUT

{"deadline_seconds":1.0,"grpc_status":"DEADLINE_EXCEEDED","order_service":"running","reason":"inventory deadline exceeded","status":"failed"}
```

Order log. The stub deadline fires at about 1 second and the process keeps running:

```text
service=order-grpc endpoint=/orders grpc_status=DEADLINE_EXCEEDED item_id=item-1 detail=Deadline Exceeded order_service=running latency_ms=1007
```

Inventory log. It starts the 3 second delay, then sees the client cancel and stops:

```text
service=inventory-grpc method=CheckInventory action=delay delay_seconds=3.0
service=inventory-grpc method=CheckInventory status=DEADLINE_EXCEEDED detail=client cancelled the slow call
```

### Order stays running after the gRPC deadline

```bash
curl -i http://127.0.0.1:6002/health
```

```text
HTTP/1.1 200 OK

{"service":"order-grpc","status":"ok"}
```

```bash
curl -i -X POST http://127.0.0.1:6002/orders \
  -H 'Content-Type: application/json' \
  -d '{"item_id":"item-2","quantity":1}'
```

```text
HTTP/1.1 201 CREATED

{"grpc_status":"OK","inventory":{"available":true,"available_quantity":5,"item_id":"item-2"},"item_id":"item-2","order_id":"ord-0c316988","quantity":1,"status":"accepted"}
```

Order log after `DEADLINE_EXCEEDED`, including the next health check and the next accepted order:

```text
service=order-grpc endpoint=/orders grpc_status=DEADLINE_EXCEEDED item_id=item-1 detail=Deadline Exceeded order_service=running latency_ms=1007
127.0.0.1 - - [12/Oct/2026 11:09:42] "GET /health HTTP/1.1" 200 -
service=order-grpc endpoint=/orders grpc_status=OK order_id=ord-0c316988 item_id=item-2 quantity=1 available_quantity=5 latency_ms=1
```

## REST vs gRPC

REST was the smaller implementation: Inventory is one Flask route, the body is a JSON object, and curl shows the status code directly, with no code generation. gRPC needed `inventory.proto` plus generated stubs before Order could call `CheckInventory`, and the same outcomes came back as the status codes `OK`, `NOT_FOUND`, and `FAILED_PRECONDITION`. The REST client passes `timeout=1.0` to `requests` and catches `requests.Timeout`, which here returned `504` at `latency_ms=1003` while Inventory was still inside its 3 second sleep and later logged `latency_ms=3005`. The gRPC client passes that same 1 second as a per-call deadline and receives `StatusCode.DEADLINE_EXCEEDED` (logged at `latency_ms=1007`), and the Inventory server can see that cancellation on the RPC context and stop waiting. Both Order processes stayed up after the failure: each `GET /health` returned `200`, and each accepted a later order for `item-2`. REST left the JSON shape and status codes in the handlers, while gRPC made the fields and the error statuses part of a shared generated API, with the extra proto and stub step.
