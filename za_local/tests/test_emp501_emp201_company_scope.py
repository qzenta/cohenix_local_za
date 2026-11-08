"""G-8: linked EMP201 reads in EMP501 Reconciliation are limited to the reconciliation Company (E1), and
invalid linked references are refused at submit (E2). In-memory only: no database writes, no commits."""

import unittest
from unittest import mock

import frappe

from za_local.sa_payroll.doctype.emp501_reconciliation.emp501_reconciliation import EMP501Reconciliation


def _doc(company, linked_names):
	doc = frappe.new_doc("EMP501 Reconciliation")
	doc.company = company
	for name in linked_names:
		doc.append("emp201_submissions", {"emp201_submission": name})
	return doc


def _coverage(expected_names, duplicate_periods=None):
	return {
		"missing_periods": [],
		"duplicate_periods": duplicate_periods or [],
		"linked_submissions": [frappe._dict(name=name) for name in expected_names],
	}


def _rows(names):
	return [frappe._dict(name=name) for name in names]


class TestEMP501LinkedEMP201CompanyScope(unittest.TestCase):
	def test_linked_rows_query_is_company_filtered(self):
		doc = _doc("RC Payroll Co", ["EMP201-A", "EMP201-B"])
		with mock.patch("frappe.get_all", return_value=[]) as get_all:
			doc._get_linked_emp201_rows()
		filters = get_all.call_args.kwargs["filters"]
		self.assertEqual(filters["company"], "RC Payroll Co")
		self.assertEqual(filters["name"], ["in", ["EMP201-A", "EMP201-B"]])
		self.assertEqual(filters["docstatus"], 1)

	def test_no_linked_names_means_no_query(self):
		doc = _doc("RC Payroll Co", [])
		with mock.patch("frappe.get_all") as get_all:
			self.assertEqual(doc._get_linked_emp201_rows(), [])
		get_all.assert_not_called()

	def _validate(self, linked_names, expected_names, actual_names, duplicate_periods=None):
		doc = _doc("RC Payroll Co", linked_names)
		with (
			mock.patch.object(
				EMP501Reconciliation,
				"validate_emp201_period_coverage",
				return_value=_coverage(expected_names, duplicate_periods),
			),
			mock.patch.object(
				EMP501Reconciliation, "_get_linked_emp201_rows", return_value=_rows(actual_names)
			),
		):
			doc.validate_linked_emp201_references()

	def test_own_company_references_pass(self):
		self._validate(["A", "B"], ["A", "B"], ["A", "B"])

	def test_foreign_reference_is_refused_and_named(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._validate(["A", "B", "FOREIGN"], ["A", "B"], ["A", "B"])
		message = str(ctx.exception)
		self.assertIn("Invalid EMP201 reference", message)
		self.assertIn("FOREIGN", message)

	def test_draft_and_nonexistent_references_are_refused(self):
		for bad_name in ("DRAFT-ONE", "DELETED-ONE"):
			with self.assertRaises(frappe.ValidationError) as ctx:
				self._validate(["A", "B", bad_name], ["A", "B"], ["A", "B"])
			self.assertIn(bad_name, str(ctx.exception))

	def test_invalid_reference_is_reported_before_missing_and_unexpected(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._validate(["FOREIGN"], ["A", "B"], [])
		message = str(ctx.exception)
		self.assertIn("Invalid EMP201 reference", message)
		self.assertNotIn("Missing linked EMP201 declarations", message)

	def test_missing_expected_submission_is_still_detected(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._validate(["A"], ["A", "B"], ["A"])
		self.assertIn("Missing linked EMP201 declarations: B", str(ctx.exception))

	def test_duplicate_reference_is_still_detected(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._validate(["A", "A", "B"], ["A", "B"], ["A", "B"])
		self.assertIn("Duplicate EMP201 references: A", str(ctx.exception))

	def test_unexpected_period_is_still_detected(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._validate(["A", "B"], ["A"], ["A", "B"])
		self.assertIn("EMP201 declarations outside this period: B", str(ctx.exception))

	def test_duplicate_periods_are_still_refused_first(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			self._validate(["A"], ["A"], ["A"], duplicate_periods=["period"])
		self.assertIn("Duplicate submitted EMP201 declarations exist", str(ctx.exception))


if __name__ == "__main__":
	unittest.main()
