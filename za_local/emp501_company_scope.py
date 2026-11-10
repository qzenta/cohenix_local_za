"""EMP501 Reconciliation follows the user's Company permissions, fail-closed.

Frappe's own Company user-permission match is non-strict: a user with no applicable Company
permission is unrestricted, and rows with an empty or NULL Company pass it. For HR Manager and
HR User, who hold read, write and export on EMP501 Reconciliation, that is not acceptable, so this
module scopes them to the Company values in their applicable Company user permissions and refuses
everything else. (Governance ruling of 9 Nov 2026, G-9c Annex A, item M-01.)

List and document (permission_query_conditions and has_permission hooks):
- Exempt (break-glass): Administrator and System Manager, for EMP501 Reconciliation only.
  HR Manager and HR User are never exempt. This module does not exempt anyone from EMP201 scope.
- Everyone else is scoped: only rows whose Company is in the user's applicable Company user
  permissions. No applicable permission means no rows. Empty and NULL Company never match.

Applicability follows emp201_company_scope.py: a Company permission applies when it has no
applicable_for, or applicable_for equals EMP501 Reconciliation. Descendant Companies are whatever
frappe.permissions.get_user_permissions returns; nothing is expanded here (stricter, never wider).

The has_permission hook can only deny. The SQL builder and the checks are pure functions for unit testing.
"""

import frappe
from frappe import _

DOCTYPE = "EMP501 Reconciliation"
BREAK_GLASS_ROLES = ("System Manager",)


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


def is_break_glass(user, roles):
	"""True for Administrator and for System Manager. Never true for HR Manager or HR User."""
	return user == "Administrator" or bool(set(BREAK_GLASS_ROLES) & set(roles or ()))


def company_allowed(company, allowed):
	"""True only for a non-empty Company that is in the allowed list. Empty and NULL never match."""
	return bool(company) and company in (allowed or ())


def share_allowed(everyone, target_user, target_roles, record_company, allowed):
	"""True if a share of an EMP501 Reconciliation to target_user is permitted.

	Never for an everyone share. Break-glass targets (Administrator, System Manager) always.
	Any other target only when the record's non-empty Company is in the target's applicable Company
	permissions, so a share can never widen access beyond the M-01 scope.
	"""
	if everyone or not target_user:
		return False
	if is_break_glass(target_user, target_roles):
		return True
	return company_allowed(record_company, allowed)


def build_company_condition(allowed, escape):
	"""Permission query condition for EMP501 Reconciliation. Fails closed: '1 = 0' when nothing is allowed."""
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
	if doctype != DOCTYPE or is_break_glass(user, frappe.get_roles(user)):
		return ""
	return build_company_condition(_allowed_companies(user), frappe.db.escape)


def has_permission(doc, ptype=None, user=None):
	"""Controller check: False for a scoped user when the Company is empty or not permitted, else True.

	A has_permission hook can only deny (frappe.permissions.has_controller_permissions).
	"""
	user = user or frappe.session.user
	if getattr(doc, "doctype", None) != DOCTYPE or is_break_glass(user, frappe.get_roles(user)):
		return True
	return company_allowed(doc.get("company"), _allowed_companies(user))


def validate_docshare(doc, method=None):
	"""doc_events validate hook for DocShare. A DocShare would otherwise bypass has_permission above."""
	if doc.get("share_doctype") != DOCTYPE:
		return
	target = doc.get("user")
	record_company = frappe.db.get_value(DOCTYPE, doc.get("share_name"), "company")
	roles = frappe.get_roles(target) if target else ()
	allowed = _allowed_companies(target) if target else []
	if not share_allowed(doc.get("everyone"), target, roles, record_company, allowed):
		frappe.throw(_("This record cannot be shared with that user."), frappe.PermissionError)
