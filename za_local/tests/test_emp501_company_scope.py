"""Unit tests for the pure helpers in za_local.emp501_company_scope (no site data needed)."""

import unittest

from za_local.emp501_company_scope import (
	BREAK_GLASS_ROLES,
	DOCTYPE,
	allowed_companies_from_user_permissions,
	build_company_condition,
	company_allowed,
	is_break_glass,
)


def esc(value):
	return "'" + value.replace("'", "''") + "'"


class TestEMP501CompanyScope(unittest.TestCase):
	def test_doctype(self):
		self.assertEqual(DOCTYPE, "EMP501 Reconciliation")

	def test_allowed_companies_applicability(self):
		perms = {
			"Company": [
				{"doc": "A", "applicable_for": None},
				{"doc": "B", "applicable_for": "EMP501 Reconciliation"},
				{"doc": "C", "applicable_for": "EMP201 Submission"},
				{"doc": "D", "applicable_for": "Sales Invoice"},
				{"doc": "", "applicable_for": None},
			]
		}
		self.assertEqual(allowed_companies_from_user_permissions(perms), ["A", "B"])
		self.assertEqual(allowed_companies_from_user_permissions({}), [])
		self.assertEqual(allowed_companies_from_user_permissions(None), [])

	def test_condition_fails_closed(self):
		self.assertEqual(build_company_condition([], esc), "1 = 0")
		self.assertEqual(build_company_condition(["", None], esc), "1 = 0")
		cond = build_company_condition(["RC Payroll Co", "RC Bank Co"], esc)
		self.assertIn("in ('RC Payroll Co', 'RC Bank Co')", cond)
		self.assertIn("ifnull(`tabEMP501 Reconciliation`.`company`, '') != ''", cond)

	def test_condition_escapes(self):
		self.assertIn("'O''Co'", build_company_condition(["O'Co"], esc))

	def test_company_allowed_excludes_empty_and_null(self):
		self.assertTrue(company_allowed("A", ["A"]))
		self.assertFalse(company_allowed("B", ["A"]))
		self.assertFalse(company_allowed("", ["A", ""]))
		self.assertFalse(company_allowed(None, ["A"]))
		self.assertFalse(company_allowed("A", []))

	def test_break_glass(self):
		# Governance ruling of 9 Nov 2026: Administrator and System Manager only; HR roles never.
		self.assertEqual(BREAK_GLASS_ROLES, ("System Manager",))
		self.assertTrue(is_break_glass("Administrator", []))
		self.assertTrue(is_break_glass("u", ["System Manager"]))
		self.assertTrue(is_break_glass("u", ["HR User", "System Manager"]))
		self.assertFalse(is_break_glass("u", ["HR Manager"]))
		self.assertFalse(is_break_glass("u", ["HR User"]))
		self.assertFalse(is_break_glass("u", ["HR Manager", "HR User", "Payroll Manager"]))
		self.assertFalse(is_break_glass("u", []))
		self.assertFalse(is_break_glass("u", None))


if __name__ == "__main__":
	unittest.main()
