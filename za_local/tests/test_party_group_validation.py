"""Gate B tests for za_local.party_group_validation.

Run from frappe-bench/sites with the bench env python (the site has no allow_tests, as for the Contact and Address hook):
    ../env/bin/python -m unittest -v za_local.tests.test_party_group_validation

TestRuleLogic needs no site. TestHookOnSite connects to acceptance-dev.localhost (QZ_TEST_SITE overrides) and rolls back
after every test, so nothing it creates is committed. The REST HTTP path is tested separately from the host
(evidence script b5_rest_check.py); here frappe.client.insert, the whitelisted method behind it, is called in-process.
"""

import os
import secrets
from types import SimpleNamespace
from unittest import TestCase, skipIf

from za_local.party_group_validation import blanks_group, is_blank, message

SITE = os.environ.get("QZ_TEST_SITE", "acceptance-dev.localhost")
GROUPS = {"Customer": ("customer_group", "Matrix Customers A"), "Supplier": ("supplier_group", "Matrix Suppliers A")}
LEGACY_BLANK = {"Customer": "Matrix Customer A blank", "Supplier": "Matrix Supplier A blank"}
NON_ADMIN = "user.a@example.test"


class TestRuleLogic(TestCase):
	def test_blank_values(self):
		self.assertTrue(is_blank(None))
		self.assertTrue(is_blank(""))
		self.assertTrue(is_blank("   "))
		self.assertFalse(is_blank("Matrix Customers A"))

	def test_insert_blank_rejected_insert_set_accepted(self):
		self.assertTrue(blanks_group(True, None, None, False))
		self.assertTrue(blanks_group(True, "", None, False))
		self.assertFalse(blanks_group(True, "G", None, False))

	def test_update_to_blank_rejected(self):
		self.assertTrue(blanks_group(False, "", "G", True))
		self.assertTrue(blanks_group(False, None, "G", True))

	def test_legacy_blank_not_blanked_by_this_save_allowed(self):
		self.assertFalse(blanks_group(False, None, None, True))
		self.assertFalse(blanks_group(False, "G", None, True))

	def test_update_without_previous_state_and_blank_rejected(self):
		self.assertTrue(blanks_group(False, None, None, False))

	def test_message_is_clear(self):
		self.assertEqual(message("Customer", "X"), "Customer Group is required. Choose a Customer Group for Customer X before saving.")
		self.assertIn("Supplier Group is required", message("Supplier", None))


@skipIf(
	os.environ.get("GITHUB_ACTIONS") == "true",
	"bench-only: needs the acceptance-dev site and Matrix fixtures, and destroys the shared frappe context",
)
class TestHookOnSite(TestCase):
	@classmethod
	def setUpClass(cls):
		import frappe

		cls.frappe = frappe
		frappe.init(site=SITE, sites_path=os.environ.get("QZ_SITES_PATH", "/home/frappe/frappe-bench/sites"))
		frappe.connect()
		hooks = frappe.get_hooks("doc_events")
		cls.registered = {
			dt: hooks.get(dt, {}).get("validate", []) for dt in ("Customer", "Supplier")
		}

	@classmethod
	def tearDownClass(cls):
		cls.frappe.db.rollback()
		cls.frappe.destroy()

	def setUp(self):
		self.frappe.set_user("Administrator")

	def tearDown(self):
		self.frappe.set_user("Administrator")
		self.frappe.db.rollback()

	def new_party(self, doctype, with_group, name=None):
		f = self.frappe
		name = name or f"B5 Test {doctype} {secrets.token_hex(3)}"
		values = {"doctype": doctype, ("customer_name" if doctype == "Customer" else "supplier_name"): name}
		if doctype == "Customer":
			values["customer_type"] = "Company"
		if with_group:
			values[GROUPS[doctype][0]] = GROUPS[doctype][1]
		return f.get_doc(values)

	def assert_rejected(self, fn, doctype):
		f = self.frappe
		with self.assertRaises(f.ValidationError) as ctx:
			fn()
		self.assertIn(f"{GROUPS[doctype][0].replace('_', ' ').title()} is required", str(ctx.exception))

	def test_hooks_registered(self):
		self.assertIn("za_local.party_group_validation.validate_customer_group", self.registered["Customer"])
		self.assertIn("za_local.custom.customer.validate", self.registered["Customer"])
		self.assertIn("za_local.party_group_validation.validate_supplier_group", self.registered["Supplier"])

	def test_insert_blank_rejected_as_administrator(self):
		for dt in ("Customer", "Supplier"):
			with self.subTest(dt):
				self.assert_rejected(lambda: self.new_party(dt, False).insert(), dt)
				self.frappe.db.rollback()

	def test_insert_with_group_accepted(self):
		for dt in ("Customer", "Supplier"):
			with self.subTest(dt):
				doc = self.new_party(dt, True).insert()
				self.assertTrue(self.frappe.db.exists(dt, doc.name))

	def test_update_to_blank_rejected(self):
		for dt in ("Customer", "Supplier"):
			with self.subTest(dt):
				doc = self.new_party(dt, True).insert()
				doc = self.frappe.get_doc(dt, doc.name)
				doc.set(GROUPS[dt][0], None)
				self.assert_rejected(doc.save, dt)
				self.frappe.db.rollback()

	def test_insert_blank_rejected_for_non_admin_user(self):
		for dt in ("Customer", "Supplier"):
			with self.subTest(dt):
				self.frappe.set_user(NON_ADMIN)
				self.assert_rejected(lambda: self.new_party(dt, False).insert(ignore_permissions=True), dt)
				self.frappe.set_user("Administrator")
				self.frappe.db.rollback()

	def test_rest_method_frappe_client_insert_rejected(self):
		from frappe.client import insert

		for dt in ("Customer", "Supplier"):
			with self.subTest(dt):
				payload = self.new_party(dt, False).as_dict()
				self.assert_rejected(lambda: insert(payload), dt)
				self.frappe.db.rollback()

	def test_data_import_insert_record_rejected(self):
		"""Importer.insert_record is the per-row insert of the Data Import loop (insert type). The loop itself commits each
		successful row, so the real function is driven with a minimal importer stand-in instead of a full import job."""
		f = self.frappe
		from frappe.core.doctype.data_import.importer import Importer

		for dt in ("Customer", "Supplier"):
			with self.subTest(dt):
				stub = SimpleNamespace(doctype=dt, data_import=f.new_doc("Data Import"), _uses_tree_aliases=False,
									   _tree_parent_field=None)
				row = f._dict({k: v for k, v in self.new_party(dt, False).as_dict().items()
							   if k in ("customer_name", "supplier_name", "customer_type")})
				self.assert_rejected(lambda: Importer.insert_record(stub, row), dt)
				f.db.rollback()
				row[GROUPS[dt][0]] = GROUPS[dt][1]
				doc = Importer.insert_record(stub, row)
				self.assertTrue(f.db.exists(dt, doc.name))
				f.db.rollback()

	def test_existing_blank_record_unchanged_and_still_saveable(self):
		f = self.frappe
		for dt in ("Customer", "Supplier"):
			with self.subTest(dt):
				name = LEGACY_BLANK[dt]
				if not f.db.exists(dt, name):
					self.skipTest(f"{name} not on this site")
				self.assertTrue(is_blank(f.db.get_value(dt, name, GROUPS[dt][0])))
				doc = f.get_doc(dt, name)
				doc.save()  # no change to the group: legacy blank, allowed (rolled back in tearDown)
				f.db.rollback()
