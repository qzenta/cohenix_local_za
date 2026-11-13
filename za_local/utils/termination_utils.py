"""
Termination & Settlement Utility Functions
"""

import frappe
from frappe import _
from frappe.utils import date_diff, flt, getdate

from za_local.utils.statutory_rates import calculate_lump_sum_benefit_tax


def calculate_bcea_notice_period(employee, termination_date):
	"""
	Calculate BCEA minimum notice period.

	Args:
		employee: Employee ID or doc
		termination_date: Date of termination

	Returns:
		int: Notice period in days
	"""
	if isinstance(employee, str):
		employee = frappe.get_doc("Employee", employee)

	if not employee.date_of_joining:
		return 28  # Default to 4 weeks

	tenure_days = date_diff(termination_date, employee.date_of_joining)
	tenure_years = tenure_days / 365.25

	if tenure_years < 0.5:
		return 7  # 1 week
	elif tenure_years < 1:
		return 14  # 2 weeks
	else:
		return 28  # 4 weeks


def calculate_severance_pay(employee, termination_date, termination_type):
	"""
	Calculate severance pay per BCEA.

	BCEA: 1 week's remuneration per completed year.
	Only for operational dismissals.

	Args:
		employee: Employee ID or doc
		termination_date: Date of termination
		termination_type: Type of termination

	Returns:
		float: Severance pay amount
	"""
	if termination_type != "Dismissal - Operational":
		return 0.0

	if isinstance(employee, str):
		employee = frappe.get_doc("Employee", employee)

	if not employee.date_of_joining:
		return 0.0

	# Completed years only
	tenure_days = date_diff(termination_date, employee.date_of_joining)
	completed_years = int(tenure_days / 365.25)

	if completed_years < 1:
		return 0.0

	# Get last salary
	salary = frappe.get_all(
		"Salary Structure Assignment",
		filters={"employee": employee.name, "docstatus": 1},
		fields=["base"],
		order_by="from_date desc",
		limit=1
	)

	if not salary:
		return 0.0

	monthly_salary = flt(salary[0].base)
	weekly_salary = monthly_salary / 4.33

	return weekly_salary * completed_years


def calculate_leave_payout_on_termination(employee, date_value):
	"""
	Calculate leave payout for untaken annual leave.

	Uses hrms's own leave-balance utility (reads the Leave Ledger, nets out
	leave already taken, handles carry-forward expiry) rather than summing
	Leave Allocation directly. A raw allocation sum only ever returns the
	total EVER allocated, not the remaining/unused balance - it would
	overstate the payout for any employee who has taken some of their
	allocated leave (confirmed empirically: a 10-day allocation with 4 days
	already taken returns 10 from a naive allocation sum vs the correct 6
	from get_leave_balance_on - a real R7,733.33 overstatement on a
	R58,000/month salary in that one test case).

	Sums across every Leave Type whose name matches the original '%Annual%'
	pattern - preserved deliberately, not narrowed to a single hardcoded
	name, since different clients may name their annual-leave type
	differently (e.g. "Annual Leave", "Company Annual Leave") and no
	evidence was found that the broad match was accidental (za_local does
	not itself seed any "Annual"-named Leave Type, so this has always been
	a deliberate tolerance for client-defined naming, not a bug).

	Args:
		employee: Employee ID
		date_value: date to compute the balance as of. REQUIRED, not defaulted
			to today - this function is currently unreferenced anywhere in the
			codebase (confirmed by an exhaustive search across frappe, erpnext,
			hrms, za_local and qzenta_controls), so a silent "today" default
			would be a live trap for whoever wires it up later: a settlement
			processed days or weeks after the actual termination date would
			incorrectly net out leave taken in the intervening gap. Callers
			must pass the actual separation/termination date explicitly.

	Returns:
		dict: {"days": float, "amount": float}
	"""
	from hrms.hr.doctype.leave_application.leave_application import get_leave_balance_on

	as_of_date = getdate(date_value)

	leave_types = frappe.get_all("Leave Type", filters={"name": ["like", "%Annual%"]}, pluck="name")

	total_days = 0
	for leave_type in leave_types:
		total_days += flt(get_leave_balance_on(employee, leave_type, as_of_date))

	if total_days <= 0:
		return {"days": 0, "amount": 0}

	# Get daily rate
	salary = frappe.get_all(
		"Salary Structure Assignment",
		filters={"employee": employee, "docstatus": 1},
		fields=["base"],
		order_by="from_date desc",
		limit=1
	)

	if not salary:
		return {"days": total_days, "amount": 0}

	monthly_salary = flt(salary[0].base)
	daily_rate = monthly_salary / 30

	return {
		"days": total_days,
		"amount": daily_rate * total_days
	}


def calculate_severance_tax(severance_amount, date_value=None, previous_lump_sums=0):
	"""
	Calculate tax on severance pay.

	SARS: severance benefits are taxed using the retirement fund lump sum
	benefits table on a cumulative basis.

	Args:
		severance_amount: Severance amount

	Returns:
		float: Tax amount
	"""
	return calculate_lump_sum_benefit_tax(
		severance_amount,
		date_value=date_value,
		previous_lump_sums=previous_lump_sums,
	)
