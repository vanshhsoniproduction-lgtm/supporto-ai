"""
test_landing_page.py - Regression and link resolution tests for the redesigned landing page.
Verifies:
1. Renders public landing page with HTTP 200.
2. Every link and button on the landing page resolves to a real target (no broken or dead hrefs).
3. Hash anchors resolve to real IDs in the DOM.
4. No fake marketing filler (no 'Book demo', pricing, newsletter, testimonials, 'enterprise-grade').
5. Embedded chat widget iframe points to a real public_key endpoint.
"""
import re
from html.parser import HTMLParser
from django.test import TestCase, Client
from apps.workspaces.models import Workspace, WorkspaceSettings


class LinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.element_ids = set()

    def handle_starttag(self, tag, attrs):
        attr_dict = dict(attrs)
        if "id" in attr_dict:
            self.element_ids.add(attr_dict["id"])
        if tag == "a" and "href" in attr_dict:
            self.links.append(attr_dict["href"])


class LandingPageTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.shopease = Workspace.objects.create(name="ShopEase", slug="shopease")
        WorkspaceSettings.objects.create(workspace=self.shopease, support_email="support@shopease.com")
        self.expressbeas = Workspace.objects.create(name="ExpressBeas", slug="expressbeas")
        WorkspaceSettings.objects.create(workspace=self.expressbeas, support_email="support@expressbeas.in")

    def test_landing_page_renders_cleanly(self):
        """Landing page renders with 200 OK and expected headline."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode("utf-8")

        # Check required headline
        self.assertIn("Reads chats, calls and emails; answers from your FAQs and order data; hands risky cases to a human", content)
        # Check required sections
        self.assertIn("How it works", content)
        self.assertIn("Our Customers", content)
        # Check footer
        self.assertIn("Supporto AI", content)
        self.assertIn("Hackathon 2.5", content)
        self.assertIn("github.com/vanshhsoniproduction-lgtm/supporto-ai", content)

    def test_no_fake_filler_or_unsubstantiated_claims(self):
        """Must not contain fake book demo, pricing, newsletter, testimonials or hype words."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        content_lower = resp.content.decode("utf-8").lower()

        forbidden_terms = [
            "book demo",
            "pricing",
            "newsletter",
            "trusted by",
            "testimonials",
            "zero hallucination",
            "enterprise-grade",
            "revolutionary",
            "fortune 500",
        ]
        for term in forbidden_terms:
            self.assertNotIn(term, content_lower, f"Forbidden term '{term}' found on landing page!")

    def test_every_link_and_button_resolves(self):
        """
        HARD RULE: Every link and button must work.
        Checks that every href on the landing page resolves to an existing DOM ID or a valid HTTP route.
        """
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode("utf-8")

        parser = LinkExtractor()
        parser.feed(html)

        self.assertGreater(len(parser.links), 0, "Landing page should have navigational links.")

        for href in parser.links:
            # 1. Anchor links (e.g. #try-it)
            if href.startswith("#"):
                target_id = href[1:]
                self.assertIn(target_id, parser.element_ids, f"Anchor '{href}' references non-existent id '{target_id}' in page!")

            # 2. External links (e.g. GitHub repo)
            elif href.startswith("http://") or href.startswith("https://"):
                self.assertTrue(href.startswith("https://github.com/"), f"Unexpected external link '{href}'")

            # 3. Internal routes
            else:
                target_url = href.split("?")[0]
                target_resp = self.client.get(target_url)
                self.assertIn(
                    target_resp.status_code,
                    [200, 301, 302],
                    f"Link '{href}' failed to resolve! Status code: {target_resp.status_code}"
                )

    def test_customer_storefront_links_resolve(self):
        """The landing page features ExpressBeas and ShopEase customer cards linking to their live storefront demos."""
        resp = self.client.get("/")
        content = resp.content.decode("utf-8")

        self.assertIn("ExpressBeas", content)
        self.assertIn("ShopEase", content)
        self.assertIn(f"/widget/{self.shopease.public_key}/demo/", content)
        self.assertIn(f"/widget/{self.expressbeas.public_key}/demo/", content)

        # Test storefront routes resolve 200 and contain the support widget
        se_resp = self.client.get(f"/widget/{self.shopease.public_key}/demo/")
        self.assertEqual(se_resp.status_code, 200)
        self.assertIn(f"/widget/{self.shopease.public_key}/", se_resp.content.decode("utf-8"))

        eb_resp = self.client.get(f"/widget/{self.expressbeas.public_key}/demo/")
        self.assertEqual(eb_resp.status_code, 200)
        self.assertIn(f"/widget/{self.expressbeas.public_key}/", eb_resp.content.decode("utf-8"))

