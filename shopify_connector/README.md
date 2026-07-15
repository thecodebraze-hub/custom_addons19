# Shopify Connector

Production-ready foundation module for integrating Odoo 19 with Shopify stores.

## Overview

**Shopify Connector** provides the core infrastructure required to connect Odoo with Shopify, including store configuration, queue management, logging, webhook registration placeholders, and a service layer ready for future API integration.

This release is a clean, installable foundation. OAuth, API calls, and synchronization logic are intentionally not implemented yet.

## Features

- Shopify store instance management per company
- Secure credential fields with manager-only access
- Connection status tracking and chatter integration
- Queue model for asynchronous sync jobs
- Structured API and sync logging
- Webhook registration records
- Dashboard, stores, queue, logs, and settings menus
- Placeholder service layer (`ApiClient`, `OAuthService`, `WebhookService`)
- Public health-check endpoint at `/shopify/status`
- Scheduled job placeholders for future sync operations

## Requirements

- Odoo 19.0 Community
- Python 3.12+

## Dependencies

- `base`
- `mail`
- `web`

## Installation

1. Copy the `shopify_connector` folder into your Odoo addons path.
2. Update the apps list from **Apps**.
3. Search for **Shopify Connector** and click **Install**.

## Configuration

1. Assign users to **Shopify User** or **Shopify Manager** security groups.
2. Open **Shopify → Stores** and create a store record.
3. Enter the store URL, API credentials, and company mapping.
4. Use the header buttons to connect, disconnect, or test the connection once integration is implemented.

## Security Groups

| Group | Permissions |
|-------|-------------|
| Shopify User | Read-only access to connector data |
| Shopify Manager | Full create, read, update, and delete access |

## Module Structure

```
shopify_connector/
├── constants.py
├── controllers/
├── data/
├── models/
├── security/
├── services/
├── static/
├── tests/
├── views/
└── wizard/
```

## Development Roadmap

- Shopify OAuth authorization flow
- Admin API client implementation
- Product, customer, order, and inventory synchronization
- Webhook processing and retry logic
- Dashboard KPIs and operational metrics

## Author

**CodeBraze (PVT) Ltd**  
Website: https://codebraze.lk

## License

Odoo Proprietary License v1.0 (`OPL-1`). A valid license purchased from
CodeBraze (PVT) Ltd, typically through Odoo Apps, is required.
