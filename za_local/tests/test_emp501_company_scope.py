"""Unit tests for the pure helpers in za_local.emp501_company_scope (no site data needed)."""

import unittest

from za_local.emp501_company_scope import (
	BREAK_GLASS_ROLES,
	DOCTYPE,
	allowed_companies_from_user_permissions,
	build_company_condition,
	company_allowed,
	foreign_or_missing_reference_found,
	is_break_glass,
	share_allowed,
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

	def test_share_allowed(self):
		self.assertFalse(share_allowed(1, "u", ["HR Manager"], "A", ["A"]))
		self.assertFalse(share_allowed(0, None, [], "A", ["A"]))
		self.assertTrue(share_allowed(0, "u", ["HR Manager"], "A", ["A"]))
		self.assertFalse(share_allowed(0, "u", ["HR Manager"], "B", ["A"]))
		self.assertFalse(share_allowed(0, "u", ["HR User"], "", ["A"]))
		self.assertFalse(share_allowed(0, "u", ["HR User"], None, ["A"]))
		self.assertFalse(share_allowed(0, "u", ["HR User"], "A", []))
		self.assertTrue(share_allowed(0, "u", ["System Manager"], "B", []))
		self.assertTrue(share_allowed(0, "Administrator", [], None, []))

	def test_foreign_or_missing_reference_found(self):
		known = {("EMP201 Submission", "own"), ("IRP5 Certificate", "own")}
		calls = []

		def exists(doctype, name, extra_filters):
			calls.append((doctype, name, extra_filters))
			return (doctype, name) in known

		own = ("EMP201 Submission", "own", {"company": "A", "docstatus": 1})
		self.assertFalse(foreign_or_missing_reference_found([], exists))
		self.assertFalse(foreign_or_missing_reference_found(None, exists))
		self.assertFalse(foreign_or_missing_reference_found([own, ("IRP5 Certificate", "own", {"company": "A"})], exists))
		self.assertEqual(calls[0], own)
		self.assertTrue(foreign_or_missing_reference_found([own, ("EMP201 Submission", "other", {"company": "A", "docstatus": 1})], exists))
		self.assertTrue(foreign_or_missing_reference_found([("IRP5 Certificate", "missing", {"company": "A"})], exists))
		self.assertTrue(foreign_or_missing_reference_found([("IRP5 Certificate", "missing", {}), ("EMP201 Submission", "missing", {})], exists))

	def test_foreign_or_missing_reference_skips_empty_names(self):
		def exists(doctype, name, extra_filters):
			raise AssertionError("exists called for an empty name")

		self.assertFalse(foreign_or_missing_reference_found([("EMP201 Submission", "", {}), ("IRP5 Certificate", None, {})], exists))


if __name__ == "__main__":
	unittest.main()
