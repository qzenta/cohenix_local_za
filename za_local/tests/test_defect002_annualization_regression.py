"""Regression coverage for DEFECT-002: PAYE annualization for employees with
missing (not absent) prior Salary Slip history.

Reproduces the exact scenario from FOP-LAB-003-FINDING-first-slip-annualization.md
- an employee whose date_of_joining predates the current Payroll Period but who
has zero submitted Salary Slips for the elapsed months of that period - and
confirms the fix's fail-closed guard plus the widened opening-balance honouring
in za_local.overrides.salary_slip.ZASalarySlip.
"""

import calendar
import unittest

import frappe
from frappe.utils import flt

from za_local.tests.compat import UnitTestCase
from za_local.tests.e2e_data import (
	E2E_COMPANY,
	E2E_HOLIDAY_LIST,
	E2E_SALARY_STRUCTURE,
	stage_payroll_masters,
)


def _income_tax_slab():
	return frappe.db.get_value(
		"Income Tax Slab",
		{"company": E2E_COMPANY, "effective_from": ["<=", "2026-03-01"], "docstatus": 1},
		"name",
		order_by="effective_from desc",
	)


def _ensure_employee(label, date_of_joining):
	email = f"e2e.defect002{label}@cohenix.test"
	existing = frappe.db.get_value("Employee", {"personal_email": email}, "name")
	if existing:
		return existing
	doc = frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": "E2E",
			"last_name": f"Defect002{label.capitalize()}",
			"gender": "Male",
			"date_of_birth": "1990-01-01",
			"date_of_joining": date_of_joining,
			"company": E2E_COMPANY,
			"status": "Active",
			"personal_email": email,
			"holiday_list": E2E_HOLIDAY_LIST,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_assignment(employee, from_date, base=45000):
	existing = frappe.db.get_value(
		"Salary Structure Assignment",
		{"employee": employee, "salary_structure": E2E_SALARY_STRUCTURE, "docstatus": 1},
		"name",
	)
	if existing:
		return existing
	ssa = frappe.get_doc(
		{
			"doctype": "Salary Structure Assignment",
			"employee": employee,
			"salary_structure": E2E_SALARY_STRUCTURE,
			"from_date": from_date,
			"company": E2E_COMPANY,
			"base": base,
			"income_tax_slab": _income_tax_slab(),
		}
	)
	ssa.insert(ignore_permissions=True)
	ssa.submit()
	return ssa.name


def _build_slip(employee, start_date, end_date):
	return frappe.get_doc(
		{
			"doctype": "Salary Slip",
			"employee": employee,
			"company": E2E_COMPANY,
			"posting_date": end_date,
			"start_date": start_date,
			"end_date": end_date,
			"payroll_frequency": "Monthly",
		}
	)


class TestDefect002AnnualizationGuard(UnitTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.local.lang = "en"
		site = frappe.local.site or ""
		if not frappe.conf.developer_mode or "e2e" not in site.lower():
			raise unittest.SkipTest(
				"DEFECT-002 regression fixtures require the isolated e2e_data test "
				"site (same guard as za_local.tests.e2e_data._require_isolated_test_site)."
			)
		stage_payroll_masters()

	def setUp(self):
		frappe.set_user("Administrator")

	def test_guard_fires_for_missing_history_with_predating_join(self):
		"""DEFECT-002's exact reproduction: date_of_joining predates the fiscal
		year, zero prior submitted slips, no opening balance -> must fail closed,
		never silently compute PAYE on the wrong (remaining-periods-only) basis."""
		employee = _ensure_employee("guard", "2020-01-01")
		_ensure_assignment(employee, "2026-08-01")

		slip = _build_slip(employee, "2026-08-01", "2026-08-31")
		try:
			with self.assertRaises(frappe.ValidationError) as ctx:
				slip.insert(ignore_permissions=True)
			self.assertIn(
				"no submitted Salary Slips exist for the elapsed months", str(ctx.exception)
			)
		finally:
			# insert() throws mid-way through compute_net_pay, after the row is
			# already written - clean up the phantom draft so a re-run of this
			# test (or the next test reusing this employee) doesn't collide on
			# "Salary Slip ... already created for this period".
			frappe.db.delete("Salary Slip", {"employee": employee, "start_date": "2026-08-01"})
			frappe.db.commit()

	def test_opening_balance_is_honoured_once_supplied(self):
		"""Once HR supplies the opening balance the fix's widened get_opening_for
		honours it and the slip proceeds on the correct full-year basis, instead
		of the old code's silent 0 for any assignment predating the fiscal year."""
		employee = _ensure_employee("opening", "2020-01-01")
		assignment = _ensure_assignment(employee, "2026-08-01")
		frappe.db.set_value(
			"Salary Structure Assignment",
			assignment,
			{"taxable_earnings_till_date": 225000, "tax_deducted_till_date": 40000},
		)

		slip = _build_slip(employee, "2026-08-01", "2026-08-31")
		slip.insert(ignore_permissions=True)

		self.assertEqual(flt(slip.previous_taxable_earnings), 225000.0)
		self.assertEqual(flt(slip.annual_taxable_amount), 540000.0)

	def test_guard_does_not_fire_for_genuinely_new_employee(self):
		"""An employee whose date_of_joining falls within the current fiscal
		year is out of scope for this guard - remaining-periods annualization
		is the applicable (and untouched) basis for them."""
		employee = _ensure_employee("newhire", "2026-07-15")
		_ensure_assignment(employee, "2026-07-15")

		slip = _build_slip(employee, "2026-08-01", "2026-08-31")
		slip.insert(ignore_permissions=True)

		self.assertEqual(flt(slip.annual_taxable_amount), 315000.0)

	def test_guard_does_not_fire_for_first_period_of_fiscal_year(self):
		"""A slip covering the Payroll Period's own first sub-period (March)
		can never have 'missing' elapsed-year history - zero previous earnings
		is correct there regardless of date_of_joining, and must not raise."""
		employee = _ensure_employee("firstperiod", "2020-01-01")
		_ensure_assignment(employee, "2026-03-01")

		slip = _build_slip(employee, "2026-03-01", "2026-03-31")
		slip.insert(ignore_permissions=True)

		self.assertEqual(flt(slip.annual_taxable_amount), 540000.0)

	def test_guard_does_not_fire_with_real_prior_slip_history(self):
		"""The core regression guard against DEFECT-002: an employee who
		predates the fiscal year but has real submitted Salary Slip history for
		the elapsed months must annualize on the full-year basis unaffected -
		matching the exact-arithmetic figure for R45,000/month with 5 prior
		months. The August slip's PAYE is R9,275.58 when computed exactly from
		the SARS bracket table (independent Decimal oracle:
		defect004/H-oracle_defect002.py). The earlier R9,275.64 figure in the
		original MULTI-001 finding was not exact: it carried the DEFECT-004 cents
		over-deduction from Income Tax Slab band tops ending in .99."""
		employee = _ensure_employee("history", "2020-01-01")
		_ensure_assignment(employee, "2026-03-01")

		for month in range(3, 8):
			last_day = calendar.monthrange(2026, month)[1]
			start = f"2026-{month:02d}-01"
			end = f"2026-{month:02d}-{last_day:02d}"
			if frappe.db.exists("Salary Slip", {"employee": employee, "start_date": start}):
				continue
			s = _build_slip(employee, start, end)
			s.insert(ignore_permissions=True)
			s.submit()

		slip = _build_slip(employee, "2026-08-01", "2026-08-31")
		slip.insert(ignore_permissions=True)

		self.assertEqual(flt(slip.previous_taxable_earnings), 225000.0)
		self.assertEqual(flt(slip.annual_taxable_amount), 540000.0)
		paye_row = next(row for row in slip.deductions if row.salary_component == "PAYE")
		# August 2026 slip PAYE. Expected value from the independent Decimal oracle
		# defect004/H-oracle_defect002.py (month-by-month Mar to Aug: 9275.58, .58, .58,
		# .58, .59, .58). places=2 means within 0.005.
		self.assertAlmostEqual(flt(paye_row.amount), 9275.58, places=2)
