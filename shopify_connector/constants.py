# -*- coding: utf-8 -*-
"""Shared constants for the Shopify Connector module."""

DEFAULT_API_VERSION = "2025-01"

SHOPIFY_API_VERSIONS = [
    "2024-10",
    "2025-01",
    "2025-04",
    "2025-07",
    "2025-10",
]

CONNECTION_STATUS_DISCONNECTED = "disconnected"
CONNECTION_STATUS_CONNECTED = "connected"
CONNECTION_STATUS_ERROR = "error"

CONNECTION_STATUS_SELECTION = [
    (CONNECTION_STATUS_DISCONNECTED, "Disconnected"),
    (CONNECTION_STATUS_CONNECTED, "Connected"),
    (CONNECTION_STATUS_ERROR, "Error"),
]

LOG_LEVEL_DEBUG = "debug"
LOG_LEVEL_INFO = "info"
LOG_LEVEL_WARNING = "warning"
LOG_LEVEL_ERROR = "error"

LOG_LEVEL_SELECTION = [
    (LOG_LEVEL_DEBUG, "Debug"),
    (LOG_LEVEL_INFO, "Info"),
    (LOG_LEVEL_WARNING, "Warning"),
    (LOG_LEVEL_ERROR, "Error"),
]

QUEUE_STATE_PENDING = "pending"
QUEUE_STATE_PROCESSING = "processing"
QUEUE_STATE_DONE = "done"
QUEUE_STATE_FAILED = "failed"

QUEUE_STATE_SELECTION = [
    (QUEUE_STATE_PENDING, "Pending"),
    (QUEUE_STATE_PROCESSING, "Processing"),
    (QUEUE_STATE_DONE, "Done"),
    (QUEUE_STATE_FAILED, "Failed"),
]

JOB_TYPE_PRODUCT = "product"
JOB_TYPE_CUSTOMER = "customer"
JOB_TYPE_ORDER = "order"
JOB_TYPE_INVENTORY = "inventory"
JOB_TYPE_WEBHOOK = "webhook"

JOB_TYPE_SELECTION = [
    (JOB_TYPE_PRODUCT, "Product"),
    (JOB_TYPE_CUSTOMER, "Customer"),
    (JOB_TYPE_ORDER, "Order"),
    (JOB_TYPE_INVENTORY, "Inventory"),
    (JOB_TYPE_WEBHOOK, "Webhook"),
]

SEQUENCE_CODE_LOG = "shopify.log"
SEQUENCE_CODE_QUEUE = "shopify.queue"
