"""Regression coverage for DEFECT-003: employer UIF and SDL missing from Salary Slips.

Root cause (za_local 945eb7c, the DEFECT-002 fix): the guard method was inserted
between ``self.apply_eti()`` and ``self.calculate_company_contributions()`` in
``ZASalarySlip.calculate_net_pay``. That left the call stranded at the end of
``guard_against_missing_prior_earnings_history``, after ``frappe.throw``, where it
can never run. Slips then carried no ``company_contribution`` rows, so employer UIF
and SDL were empty and ``total_company_contribution`` was never set.

The 252-test suite passed with the defect present, so nothing asserted slip-level
employer contributions before this file.

Fixture note: the shared e2e salary structure creates its UIF Employee deduction row
with a blank formula. HRMS evaluates that row to 0 and, because the component has
remove_if_zero_valued set, drops it before za_local's statutory step runs, so the
employee UIF row never reaches the slip. This file therefore builds its own salary
structure with formulas on all three statutory rows, and leaves the shared fixture
untouched.

Expected values are independent of the code under test: monthly UIF is 1% of
remuneration up to the 17,712 ceiling (1% of 17,712 = 177.12), and SDL is 1% of
remuneration. For a gross of 30,000 that gives UIF 177.12 (employee and employer)
and SDL 300.00.

Requires the isolated e2e_data test site (site name must contain "e2e").
"""

import inspect
import unittest

import frappe
from frappe.utils import flt

from za_local.overrides.salary_slip import ZASalarySlip
from za_local.tests.compat import UnitTestCase
from za_local.tests.e2e_data import (
	E2E_COMPANY,
	E2E_HOLIDAY_LIST,
	E2E_PAYROLL_PAYABLE,
	stage_payroll_masters,
)

UIF_EMPLOYER_COMPONENT = "UIF Employer Contribution"
UIF_EMPLOYEE_COMPONENT = "UIF Employee Contribution"
SDL_COMPONENT = "SDL Contribution"
STRUCTURE = "ZA Local E2E DEFECT003 Structure"
UIF_FORMULA = "(gross_pay * 0.01) if (gross_pay * 0.01) <= 177.12 else 177.12"
SDL_FORMULA = "gross_pay * 0.01"
SLIP_START = "2026-08-01"
SLIP_END = "2026-08-31"

BASE = 30000
EXPECTED_GROSS = 30000.00
EXPECTED_UIF = 177.12
EXPECTED_SDL = 300.00
EXPECTED_TOTAL_CONTRIBUTION = 477.12


def _income_tax_slab():
	return frappe.db.get_value(
		"Income Tax Slab",
		{"company": E2E_COMPANY, "effective_from": ["<=", "2026-03-01"], "docstatus": 1},
		"name",
		order_by="effective_from desc",
	)


def _ensure_structure():
	if frappe.db.exists("Salary Structure", STRUCTURE):
		return STRUCTURE
	doc = frappe.get_doc(
		{
			"doctype": "Salary Structure",
			"name": STRUCTURE,
			"company": E2E_COMPANY,
			"currency": "ZAR",
			"payroll_frequency": "Monthly",
			"payment_account": E2E_PAYROLL_PAYABLE,
		}
	)
	doc.append(
		"earnings",
		{"salary_component": "Basic", "amount_based_on_formula": 1, "formula": "base"},
	)
	doc.append("deductions", {"salary_component": "PAYE"})
	doc.append(
		"deductions",
		{
			"salary_component": UIF_EMPLOYEE_COMPONENT,
			"amount_based_on_formula": 1,
			"formula": UIF_FORMULA,
		},
	)
	doc.append(
		"company_contribution",
		{
			"salary_component": UIF_EMPLOYER_COMPONENT,
			"amount_based_on_formula": 1,
			"formula": UIF_FORMULA,
		},
	)
	doc.append(
		"company_contribution",
		{
			"salary_component": SDL_COMPONENT,
			"amount_based_on_formula": 1,
			"formula": SDL_FORMULA,
		},
	)
	doc.insert(ignore_permissions=True)
	doc.submit()
	return doc.name


def _ensure_employee(label, date_of_joining):
	email = f"e2e.defect003{label}@cohenix.test"
	existing = frappe.db.get_value("Employee", {"personal_email": email}, "name")
	if existing:
		return existing
	doc = frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": "E2E",
			"last_name": f"Defect003{label.capitalize()}",
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


def _ensure_assignment(employee, from_date, structure):
	existing = frappe.db.get_value(
		"Salary Structure Assignment",
		{"employee": employee, "salary_structure": structure, "docstatus": 1},
		"name",
	)
	if existing:
		return existing
	ssa = frappe.get_doc(
		{
			"doctype": "Salary Structure Assignment",
			"employee": employee,
			"salary_structure": structure,
			"from_date": from_date,
			"company": E2E_COMPANY,
			"base": BASE,
			"income_tax_slab": _income_tax_slab(),
		}
	)
	ssa.insert(ignore_permissions=True)
	ssa.submit()
	return ssa.name


def _build_slip(employee):
	# Remove any draft left by an earlier run so the period is free.
	frappe.db.delete("Salary Slip", {"employee": employee, "start_date": SLIP_START, "docstatus": 0})
	return frappe.get_doc(
		{
			"doctype": "Salary Slip",
			"employee": employee,
			"company": E2E_COMPANY,
			"posting_date": SLIP_END,
			"start_date": SLIP_START,
			"end_date": SLIP_END,
			"payroll_frequency": "Monthly",
		}
	)


def _row(rows, component):
	return next((row for row in rows or [] if row.salary_component == component), None)


class TestDefect003CompanyContributions(UnitTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.local.lang = "en"
		site = frappe.local.site or ""
		if not frappe.conf.developer_mode or "e2e" not in site.lower():
			raise unittest.SkipTest(
				"DEFECT-003 regression fixtures require the isolated e2e_data test "
				"site (same guard as za_local.tests.e2e_data._require_isolated_test_site)."
			)
		stage_payroll_masters()
		_ensure_structure()

	def setUp(self):
		frappe.set_user("Administrator")

	def _slip_for(self, label):
		# Joins inside the fiscal year, so the DEFECT-002 guard is out of scope and the
		# only variable is whether company contributions are calculated.
		employee = _ensure_employee(label, "2026-07-15")
		_ensure_assignment(employee, "2026-07-15", STRUCTURE)
		slip = _build_slip(employee)
		slip.insert(ignore_permissions=True)
		return slip

	def test_slip_carries_employer_uif_and_sdl(self):
		"""A monthly slip must carry employer UIF and SDL rows with statutory amounts."""
		slip = self._slip_for("contrib")

		employer_uif = _row(slip.company_contribution, UIF_EMPLOYER_COMPONENT)
		sdl = _row(slip.company_contribution, SDL_COMPONENT)
		employee_uif = _row(slip.deductions, UIF_EMPLOYEE_COMPONENT)

		self.assertIsNotNone(employer_uif, "employer UIF row missing from company_contribution")
		self.assertIsNotNone(sdl, "SDL row missing from company_contribution")
		self.assertIsNotNone(employee_uif, "employee UIF deduction row missing from deductions")

		self.assertEqual(flt(slip.gross_pay, 2), EXPECTED_GROSS)
		self.assertEqual(flt(employer_uif.amount, 2), EXPECTED_UIF)
		self.assertEqual(flt(sdl.amount, 2), EXPECTED_SDL)
		self.assertEqual(flt(employee_uif.amount, 2), EXPECTED_UIF)
		self.assertEqual(flt(slip.total_company_contribution, 2), EXPECTED_TOTAL_CONTRIBUTION)

	def test_resave_does_not_duplicate_company_contribution_rows(self):
		"""calculate_company_contributions clears and rebuilds; a re-save must not stack rows."""
		slip = self._slip_for("resave")
		first_count = len(slip.company_contribution)
		self.assertEqual(first_count, 2)

		slip.save(ignore_permissions=True)
		self.assertEqual(len(slip.company_contribution), first_count)
		self.assertEqual(
			flt(slip.total_company_contribution, 2), EXPECTED_TOTAL_CONTRIBUTION
		)

	def test_company_contributions_call_is_not_stranded_in_guard(self):
		"""Structural guard for this exact misplacement; needs no database.

		The call must be reachable from calculate_net_pay and must not sit in the
		DEFECT-002 guard, whose last statement is frappe.throw.
		"""
		net_pay_source = inspect.getsource(ZASalarySlip.calculate_net_pay)
		guard_source = inspect.getsource(ZASalarySlip.guard_against_missing_prior_earnings_history)

		self.assertIn("self.calculate_company_contributions()", net_pay_source)
		self.assertNotIn("calculate_company_contributions", guard_source)
