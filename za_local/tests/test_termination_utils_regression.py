"""
DEFECT-001 regression test (Gap G, FOP-LAB-003).

calculate_leave_payout_on_termination() previously queried a nonexistent
Leave Allocation.total_leave_days column and always raised OperationalError.
The fix replaces that raw SQL with hrms's own get_leave_balance_on(), which
correctly nets out leave already taken rather than returning the total ever
allocated.

This test reproduces the exact empirical case used to diagnose and validate
the fix: an employee allocated 10 days of an "Annual"-matching leave type,
who has then taken 4 of those days. The correct remaining balance is 6 days,
not 10 - a naive column-name-only fix would have returned 10 (the pre-fix
regression this test guards against).
"""

import frappe
from frappe.utils import flt

from za_local.tests.compat import UnitTestCase
from za_local.utils.termination_utils import calculate_leave_payout_on_termination


class TestLeavePayoutOnTermination(UnitTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls._build_company()
		cls._build_fiscal_year()
		cls._build_employee()
		cls._build_salary_structure_assignment()
		cls._build_holiday_list_assignment()
		cls._build_leave_type()

	@classmethod
	def _build_company(cls):
		cls.company = "REGTEST Leave Payout Co"
		if not frappe.db.exists("Company", cls.company):
			frappe.get_doc({
				"doctype": "Company",
				"company_name": cls.company,
				"abbr": "RLPC",
				"default_currency": "ZAR",
				"country": "South Africa",
			}).insert(ignore_permissions=True)
			frappe.db.commit()

	@classmethod
	def _build_fiscal_year(cls):
		if not frappe.db.exists("Fiscal Year", "2026-2027"):
			fy = frappe.get_doc({
				"doctype": "Fiscal Year",
				"year": "2026-2027",
				"year_start_date": "2026-03-01",
				"year_end_date": "2027-02-28",
				"companies": [{"company": cls.company}],
			})
			fy.insert(ignore_permissions=True)
		else:
			fy = frappe.get_doc("Fiscal Year", "2026-2027")
			if not any(c.company == cls.company for c in fy.companies):
				fy.append("companies", {"company": cls.company})
				fy.save(ignore_permissions=True)
		frappe.db.commit()

	@classmethod
	def _build_employee(cls):
		employee_number = "REGTEST-LEAVEPAYOUT-001"
		existing = frappe.db.get_value("Employee", {"employee_number": employee_number}, "name")
		if existing:
			cls.employee = existing
			return
		emp = frappe.get_doc({
			"doctype": "Employee",
			"employee_number": employee_number,
			"first_name": "RegTest",
			"last_name": "LeavePayout",
			"company": cls.company,
			"date_of_joining": "2024-01-01",
			"date_of_birth": "1985-01-01",
			"gender": "Not Specified",
			"status": "Active",
		})
		emp.insert(ignore_permissions=True)
		cls.employee = emp.name
		frappe.db.commit()

	@classmethod
	def _build_salary_structure_assignment(cls):
		# calculate_leave_payout_on_termination() reads the daily rate off the
		# latest submitted Salary Structure Assignment - a real one is needed,
		# not just an Employee record, to exercise the full function.
		if frappe.db.exists(
			"Salary Structure Assignment",
			{"employee": cls.employee, "docstatus": 1},
		):
			return
		if not frappe.db.exists("Salary Structure", "REGTEST Leave Payout Structure"):
			ss = frappe.get_doc({
				"doctype": "Salary Structure",
				"name": "REGTEST Leave Payout Structure",
				"company": cls.company,
				"is_active": "Yes",
				"payroll_frequency": "Monthly",
				"currency": "ZAR",
				"earnings": [{"salary_component": "Basic", "amount": 58000.00}],
			})
			ss.insert(ignore_permissions=True)
			ss.submit()
		ssa = frappe.get_doc({
			"doctype": "Salary Structure Assignment",
			"employee": cls.employee,
			"salary_structure": "REGTEST Leave Payout Structure",
			"company": cls.company,
			"from_date": "2026-03-01",
			"base": 58000.00,
			"currency": "ZAR",
		})
		ssa.insert(ignore_permissions=True)
		ssa.submit()
		frappe.db.commit()

	@classmethod
	def _build_holiday_list_assignment(cls):
		holiday_list_name = "REGTEST Leave Payout Holidays 2026"
		if not frappe.db.exists("Holiday List", holiday_list_name):
			hl = frappe.get_doc({
				"doctype": "Holiday List",
				"holiday_list_name": holiday_list_name,
				"from_date": "2026-01-01",
				"to_date": "2026-12-31",
				"weekly_off": "Sunday",
			})
			hl.get_weekly_off_dates()
			hl.insert(ignore_permissions=True)
		if not frappe.db.exists(
			"Holiday List Assignment", {"assigned_to": cls.employee, "applicable_for": "Employee"}
		):
			hla = frappe.get_doc({
				"doctype": "Holiday List Assignment",
				"applicable_for": "Employee",
				"assigned_to": cls.employee,
				"employee_company": cls.company,
				"holiday_list": holiday_list_name,
				"from_date": "2026-01-01",
				"naming_series": "HRHLA-.YYYY.-",
			})
			hla.insert(ignore_permissions=True)
			hla.submit()
		frappe.db.commit()

	@classmethod
	def _build_leave_type(cls):
		cls.leave_type = "REGTEST Annual Leave"
		if not frappe.db.exists("Leave Type", cls.leave_type):
			frappe.get_doc({
				"doctype": "Leave Type",
				"leave_type_name": cls.leave_type,
				"is_earned_leave": 0,
				"max_leaves_allowed": 21,
			}).insert(ignore_permissions=True)
			frappe.db.commit()

	def _allocate_and_take_leave(self, allocated_days, taken_days):
		"""Allocate `allocated_days`, then submit a Leave Application consuming
		`taken_days` of it, so the remaining balance is allocated - taken."""
		if not frappe.db.exists(
			"Leave Allocation",
			{"employee": self.employee, "leave_type": self.leave_type, "docstatus": 1},
		):
			alloc = frappe.get_doc({
				"doctype": "Leave Allocation",
				"employee": self.employee,
				"leave_type": self.leave_type,
				"from_date": "2026-01-01",
				"to_date": "2026-12-31",
				"new_leaves_allocated": allocated_days,
			})
			alloc.insert(ignore_permissions=True)
			alloc.submit()

		if taken_days and not frappe.db.exists(
			"Leave Application",
			{"employee": self.employee, "leave_type": self.leave_type, "docstatus": 1},
		):
			# 4 consecutive weekdays, matching the diagnosis's own test case
			la = frappe.get_doc({
				"doctype": "Leave Application",
				"employee": self.employee,
				"leave_type": self.leave_type,
				"from_date": "2026-05-04",
				"to_date": "2026-05-07",
				"status": "Approved",
				"leave_approver": "Administrator",
			})
			la.insert(ignore_permissions=True)
			la.submit()
		frappe.db.commit()

	def test_leave_payout_nets_out_leave_already_taken(self):
		"""The exact 10-allocated/4-taken case from the DEFECT-001 diagnosis:
		remaining balance must be 6 days, not 10 - guards against a
		column-name-only fix that would silently return the total ever
		allocated instead of the unused balance."""
		self._allocate_and_take_leave(allocated_days=10, taken_days=4)

		result = calculate_leave_payout_on_termination(self.employee, date_value="2026-08-15")

		self.assertEqual(
			flt(result["days"]),
			6.0,
			msg=(
				f"Expected the NET remaining balance (10 allocated - 4 taken = 6), "
				f"got {result['days']}. If this returns 10, the fix has regressed "
				f"to counting total-ever-allocated instead of the unused balance."
			),
		)

		expected_daily_rate = 58000.0 / 30
		expected_amount = expected_daily_rate * 6.0
		self.assertAlmostEqual(flt(result["amount"]), expected_amount, delta=0.01)

	def test_leave_payout_does_not_raise_operational_error(self):
		"""The original defect: calling this function at all raised
		OperationalError (1054, unknown column 'total_leave_days') on every
		call, regardless of leave data. Confirms the function now runs
		successfully end-to-end without that error."""
		try:
			calculate_leave_payout_on_termination(self.employee, date_value="2026-08-15")
		except Exception as e:
			self.fail(f"calculate_leave_payout_on_termination() raised unexpectedly: {e}")

	def test_leave_payout_zero_when_no_allocation(self):
		"""An employee with no matching leave allocation at all should get a
		clean zero, not an error and not a stale/incorrect figure."""
		employee_number = "REGTEST-LEAVEPAYOUT-NOALLOC"
		existing = frappe.db.get_value("Employee", {"employee_number": employee_number}, "name")
		if not existing:
			emp = frappe.get_doc({
				"doctype": "Employee",
				"employee_number": employee_number,
				"first_name": "RegTest",
				"last_name": "NoAllocation",
				"company": self.company,
				"date_of_joining": "2024-01-01",
				"date_of_birth": "1985-01-01",
				"gender": "Not Specified",
				"status": "Active",
			})
			emp.insert(ignore_permissions=True)
			frappe.db.commit()
			existing = emp.name

		result = calculate_leave_payout_on_termination(existing, date_value="2026-08-15")
		self.assertEqual(result, {"days": 0, "amount": 0})

	def test_date_value_is_required_not_silently_defaulted(self):
		"""date_value must be required, not defaulted to today. This function
		is currently unreferenced anywhere in the codebase - a silent 'today'
		default would be a live trap for whoever wires it up later: a
		settlement processed days/weeks after the actual termination date
		would incorrectly net out leave taken in the intervening gap. Calling
		without it must fail loudly at the call site, not silently compute
		against the wrong date."""
		with self.assertRaises(TypeError):
			calculate_leave_payout_on_termination(self.employee)
