"""Unit tests for the pure helpers in za_local.emp201_company_scope (no site data needed)."""

import unittest

from za_local.emp201_company_scope import (
	allowed_companies_from_user_permissions,
	build_company_condition,
	company_allowed,
	is_list_doc_exempt,
	is_report_exempt,
)


def esc(value):
	return "'" + value.replace("'", "''") + "'"


class TestEMP201CompanyScope(unittest.TestCase):
	def test_allowed_companies_applicability(self):
		perms = {
			"Company": [
				{"doc": "A", "applicable_for": None},
				{"doc": "B", "applicable_for": "EMP201 Submission"},
				{"doc": "C", "applicable_for": "Sales Invoice"},
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
		self.assertIn("ifnull(`tabEMP201 Submission`.`company`, '') != ''", cond)

	def test_condition_escapes(self):
		self.assertIn("'O''Co'", build_company_condition(["O'Co"], esc))

	def test_company_allowed_excludes_empty_and_null(self):
		self.assertTrue(company_allowed("A", ["A"]))
		self.assertFalse(company_allowed("B", ["A"]))
		self.assertFalse(company_allowed("", ["A", ""]))
		self.assertFalse(company_allowed(None, ["A"]))
		self.assertFalse(company_allowed("A", []))

	def test_exemptions(self):
		self.assertTrue(is_list_doc_exempt("Administrator", []))
		self.assertTrue(is_list_doc_exempt("u", ["Accounts User"]))
		self.assertTrue(is_list_doc_exempt("u", ["HR Manager", "Payroll Manager"]))
		self.assertFalse(is_list_doc_exempt("u", ["HR Manager"]))
		self.assertFalse(is_list_doc_exempt("u", ["HR Manager", "System Manager"]))
		self.assertTrue(is_report_exempt("Administrator"))
		self.assertFalse(is_report_exempt("u"))


if __name__ == "__main__":
	unittest.main()
