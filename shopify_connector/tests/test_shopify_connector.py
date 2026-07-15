# -*- coding: utf-8 -*-

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestShopifyConnector(TransactionCase):
    """Validate the Shopify Connector foundation module."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.ShopifyInstance = cls.env["shopify.instance"]
        cls.ShopifyLog = cls.env["shopify.log"]
        cls.ShopifyQueue = cls.env["shopify.queue"]
        cls.ShopifyWebhook = cls.env["shopify.webhook"]

    def test_create_shopify_instance(self):
        """A Shopify store instance can be created with required fields."""
        instance = self.ShopifyInstance.create({
            "name": "Test Store",
            "store_url": "test-brand.myshopify.com",
            "company_id": self.env.company.id,
        })
        self.assertEqual(instance.connection_status, "disconnected")
        self.assertTrue(instance.active)

    def test_connection_actions_delegate_to_service(self):
        """Connection actions remain callable through the service layer."""
        instance = self.ShopifyInstance.create({
            "name": "Service Store",
            "store_url": "service-brand.myshopify.com",
            "company_id": self.env.company.id,
        })
        self.assertTrue(instance.action_connect())
        self.assertTrue(instance.action_disconnect())
        self.assertTrue(instance.action_test_connection())

    def test_log_and_queue_sequences(self):
        """Log and queue records receive sequence-based references."""
        instance = self.ShopifyInstance.create({
            "name": "Sequence Store",
            "store_url": "sequence-brand.myshopify.com",
            "company_id": self.env.company.id,
        })
        log = self.ShopifyLog.create({
            "instance_id": instance.id,
            "level": "info",
            "message": "Test log entry",
        })
        queue = self.ShopifyQueue.create({
            "instance_id": instance.id,
            "job_type": "product",
        })
        self.assertTrue(log.name.startswith("SLOG/"))
        self.assertTrue(queue.name.startswith("SJOB/"))

    def test_company_instance_count(self):
        """Company records expose the number of linked Shopify stores."""
        self.ShopifyInstance.create({
            "name": "Company Store",
            "store_url": "company-brand.myshopify.com",
            "company_id": self.env.company.id,
        })
        self.env.company.invalidate_recordset()
        self.assertGreaterEqual(self.env.company.shopify_instance_count, 1)

    def test_status_controller_route_is_registered(self):
        """The public status endpoint is registered in the routing table."""
        routing_map = self.env["ir.http"].routing_map()
        rules = [rule.rule for rule in routing_map.iter_rules()]
        self.assertIn("/shopify/status", rules)
