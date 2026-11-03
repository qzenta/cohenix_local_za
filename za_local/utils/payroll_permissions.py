"""Shared access check for payroll reports and payroll data fetches (P0-6c).

Raw-SQL payroll reports and fetch methods bypass Frappe's per-document permission checks, so each one calls
``require_payroll_company_access(company)`` before any payroll query runs.
"""

import frappe
from frappe import _
from frappe.core.doctype.user_permission.user_permission import get_user_permissions
from frappe.permissions import get_role_permissions

PAYROLL_ROLE = "HR Manager"
PAYROLL_DOCTYPE = "Salary Slip"


def payroll_companies_for_user(user=None):
	"""Companies allowed by the user's Company User Permissions that apply to Salary Slip.

	A permission applies when it is unscoped (apply to all doctypes) or scoped to Salary Slip. Returns None when no
	such permission exists: the user is then not company-restricted, as in Frappe's own permission rules.
	"""
	entries = (get_user_permissions(user) or {}).get("Company") or []
	allowed = {e.get("doc") for e in entries if e.get("applicable_for") in (None, "", PAYROLL_DOCTYPE)}
	return allowed or None


def require_payroll_company_access(company):
	"""Raise frappe.PermissionError unless the session user may see payroll data for ``company``.

	Requires role HR Manager, role-level read on Salary Slip, and ``company`` within the user's Company User
	Permissions that apply to Salary Slip (if the user has any).
	"""
	frappe.only_for(PAYROLL_ROLE)
	user = frappe.session.user
	if user == "Administrator":
		return
	if not company:
		raise frappe.PermissionError(_("A company is required to access payroll data."))
	if not get_role_permissions(frappe.get_meta(PAYROLL_DOCTYPE), user=user).get("read"):
		frappe.throw(_("You are not permitted to read Salary Slips."), frappe.PermissionError)
	allowed = payroll_companies_for_user(user)
	if allowed is not None and company not in allowed:
		frappe.throw(_("You are not permitted to access payroll data for this company."), frappe.PermissionError)
