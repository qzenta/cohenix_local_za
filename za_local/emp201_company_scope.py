"""EMP201 Submission follows the user's Company permissions, fail-closed.

Frappe's own Company user-permission match is non-strict: a user with no applicable Company
permission is unrestricted, and rows with an empty or NULL Company pass it. For the users who
receive the HR Manager grant on EMP201 Submission (sa_setup/hr_manager_emp201_perms.py) that is
not acceptable, so this module scopes them to the Company values in their applicable Company user
permissions and refuses everything else. (Governance rulings of 7 Nov 2026, E8 / G-7.)

List and document (permission_query_conditions and has_permission hooks):
- Exempt: Administrator only (named break-glass role). Payroll Manager and Accounts User are
  scoped like every other role (Governance ruling of 9 Nov 2026, EMP201 residual closure).
- Everyone else is scoped: only rows whose Company is in the user's applicable Company user
  permissions. No applicable permission means no rows. Empty and NULL Company never match.

EMP201 Report (validate_report_company, called from emp201_report._validate_filters):
- Exempt: Administrator only.
- Everyone else must hold an applicable Company user permission for the requested Company.

Applicability follows party_link_permissions.py: a Company permission applies when it has no
applicable_for, or applicable_for equals EMP201 Submission. Descendant Companies are whatever
frappe.permissions.get_user_permissions returns; nothing is expanded here (stricter, never wider).

The has_permission hook can only deny. The SQL builder and the checks are pure functions for unit testing.
"""

import frappe
from frappe import _

DOCTYPE = "EMP201 Submission"
LIST_DOC_EXEMPT_ROLES = ()


# ---------------------------------------------------------------------------
# Pure helpers (no database access)
# ---------------------------------------------------------------------------


def allowed_companies_from_user_permissions(user_permissions, doctype=DOCTYPE):
	"""Sorted Company values from a get_user_permissions() dict that apply to doctype. Empty list if none."""
	entries = (user_permissions or {}).get("Company") or []
	return sorted(
		{
			e.get("doc")
			for e in entries
			if e.get("doc") and (not e.get("applicable_for") or e.get("applicable_for") == doctype)
		}
	)


def is_list_doc_exempt(user, roles):
	"""True for Administrator only. LIST_DOC_EXEMPT_ROLES is empty, so no role grants an exemption."""
	return user == "Administrator" or bool(set(LIST_DOC_EXEMPT_ROLES) & set(roles or ()))


def is_report_exempt(user):
	"""True for Administrator only."""
	return user == "Administrator"


def company_allowed(company, allowed):
	"""True only for a non-empty Company that is in the allowed list. Empty and NULL never match."""
	return bool(company) and company in (allowed or ())


def build_company_condition(allowed, escape):
	"""Permission query condition for EMP201 Submission. Fails closed: '1 = 0' when nothing is allowed."""
	allowed = [c for c in (allowed or ()) if c]
	if not allowed:
		return "1 = 0"
	column = f"`tab{DOCTYPE}`.`company`"
	return f"{column} in ({', '.join(escape(c) for c in allowed)}) and ifnull({column}, '') != ''"


# ---------------------------------------------------------------------------
# Database-backed parts
# ---------------------------------------------------------------------------


def _allowed_companies(user):
	return allowed_companies_from_user_permissions(frappe.permissions.get_user_permissions(user) or {})


def get_permission_query_conditions(user=None, doctype=None):
	user = user or frappe.session.user
	if doctype != DOCTYPE or is_list_doc_exempt(user, frappe.get_roles(user)):
		return ""
	return build_company_condition(_allowed_companies(user), frappe.db.escape)


def has_permission(doc, ptype=None, user=None):
	"""Controller check: False for a scoped user when the Company is empty or not permitted, else True.

	A has_permission hook can only deny (frappe.permissions.has_controller_permissions).
	"""
	user = user or frappe.session.user
	if getattr(doc, "doctype", None) != DOCTYPE or is_list_doc_exempt(user, frappe.get_roles(user)):
		return True
	return company_allowed(doc.get("company"), _allowed_companies(user))


def validate_report_company(company, user=None):
	"""EMP201 Report: refuse unless the user holds an applicable Company permission for this Company."""
	user = user or frappe.session.user
	if is_report_exempt(user):
		return
	if not company_allowed(company, _allowed_companies(user)):
		frappe.throw(
			_("You do not have permission to access EMP201 data for Company: {0}.").format(company),
			frappe.PermissionError,
		)
