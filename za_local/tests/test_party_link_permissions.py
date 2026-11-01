from unittest import TestCase

from za_local.party_link_permissions import (
	build_party_link_condition,
	party_allowed,
	restrictions_from_user_permissions,
)


def fake_escape(value):
	return "'" + str(value).replace("\\", "\\\\").replace("'", "\\'") + "'"


GROUPS_ONLY = {
	"Customer": {"groups": ["Customers A", "Customers A Sub"], "names": None},
	"Supplier": {"groups": ["Suppliers A"], "names": None},
}


class TestPartyLinkSqlBuilder(TestCase):
	def test_unrestricted_returns_empty(self):
		self.assertEqual(build_party_link_condition("Contact", {"Customer": None, "Supplier": None}, fake_escape), "")
		self.assertEqual(build_party_link_condition("Address", {}, fake_escape), "")

	def test_other_doctype_returns_empty(self):
		self.assertEqual(build_party_link_condition("Customer", GROUPS_ONLY, fake_escape), "")

	def test_groups_condition_for_contact(self):
		sql = build_party_link_condition("Contact", GROUPS_ONLY, fake_escape)
		self.assertEqual(sql.count("not exists (select 1 from `tabDynamic Link` dl"), 2)
		self.assertIn("dl.`parent` = `tabContact`.`name`", sql)
		self.assertIn("dl.`parenttype` = 'Contact'", sql)
		self.assertIn("inner join `tabCustomer` p", sql)
		self.assertIn("inner join `tabSupplier` p", sql)
		self.assertIn("p.`customer_group` in ('Customers A', 'Customers A Sub')", sql)
		self.assertIn("p.`supplier_group` in ('Suppliers A')", sql)
		# strict off: a blank group stays readable
		self.assertIn("ifnull(p.`customer_group`, '') = ''", sql)

	def test_strict_drops_blank_group(self):
		sql = build_party_link_condition("Address", GROUPS_ONLY, fake_escape, strict=True)
		self.assertIn("dl.`parent` = `tabAddress`.`name`", sql)
		self.assertNotIn("ifnull", sql)

	def test_only_restricted_party_type_is_filtered(self):
		sql = build_party_link_condition(
			"Contact", {"Customer": {"groups": ["G"], "names": None}, "Supplier": None}, fake_escape
		)
		self.assertIn("`tabCustomer`", sql)
		self.assertNotIn("`tabSupplier`", sql)

	def test_names_and_empty_lists(self):
		sql = build_party_link_condition(
			"Contact", {"Customer": {"groups": None, "names": ["Cust 1"]}, "Supplier": {"groups": [], "names": []}},
			fake_escape, strict=True,
		)
		self.assertIn("p.`name` in ('Cust 1')", sql)
		self.assertIn("not (1 = 0 and 1 = 0)", sql)

	def test_values_are_escaped(self):
		sql = build_party_link_condition(
			"Contact", {"Customer": {"groups": ["x') or 1=1 -- "], "names": None}, "Supplier": None}, fake_escape
		)
		self.assertIn("in ('x\\') or 1=1 -- ')", sql)


class TestPartyAllowed(TestCase):
	def test_rules(self):
		r = {"groups": ["G1"], "names": None}
		self.assertTrue(party_allowed("C", "G1", r))
		self.assertFalse(party_allowed("C", "G2", r))
		self.assertTrue(party_allowed("C", None, r))
		self.assertFalse(party_allowed("C", None, r, strict=True))
		self.assertTrue(party_allowed("C", "G9", None))
		self.assertFalse(party_allowed("C2", "G1", {"groups": ["G1"], "names": ["C"]}))


class TestRestrictionsFromUserPermissions(TestCase):
	def test_applicable_for_and_absence(self):
		perms = {
			"Company": [{"doc": "Co A"}],
			"Customer Group": [
				{"doc": "G1", "applicable_for": None, "hide_descendants": 0},
				{"doc": "G2", "applicable_for": "Sales Invoice", "hide_descendants": 0},
			],
			"Supplier Group": [{"doc": "S1", "applicable_for": "Purchase Invoice"}],
		}
		out = restrictions_from_user_permissions(perms)
		self.assertEqual(out["Customer"], {"groups": [("G1", 0)], "names": None})
		self.assertEqual(out["Supplier"], {"groups": None, "names": None})
