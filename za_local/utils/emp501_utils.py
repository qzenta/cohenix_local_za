"""
EMP501 Utility Functions

Utilities for generating and validating EMP501 (Employer Reconciliation Declaration)
submissions to SARS.
"""

import frappe


@frappe.whitelist()
def generate_emp501_csv(emp501_name):
	"""Reject the removed mixed-record export while preserving access control."""
	# check_permission=True is required: frappe.get_doc does NOT check permissions.
	message_log = list(frappe.local.message_log or [])
	try:
		frappe.get_doc("EMP501 Reconciliation", emp501_name, check_permission=True)
	except frappe.DoesNotExistError:
		# A-08: a scoped user must not tell a missing name from a denied one. Re-run the same
		# permission check on an unsaved stand-in (no Company), which fails exactly as a denied row.
		from za_local.emp501_company_scope import is_break_glass

		if is_break_glass(frappe.session.user, frappe.get_roles()):
			raise
		frappe.local.message_log = message_log
		frappe.get_doc({"doctype": "EMP501 Reconciliation", "name": emp501_name}).check_permission("read")
		raise

	# Preserve the stricter IRP5 permission gate on this retired endpoint so direct
	# calls cannot be used to probe whether an EMP501 exists.
	if not frappe.has_permission("IRP5 Certificate", "read"):
		frappe.throw(
			frappe._("You are not permitted to export IRP5 certificate data."),
			frappe.PermissionError,
			title=frappe._("Insufficient Permission"),
		)

	frappe.throw(
		frappe._(
			"The legacy mixed-record CSV was removed because it is not a valid SARS PAYE BRS certificate file. "
			"Use SARS eFiling for up to 50 certificates or an approved e@syFile-compatible export."
		),
		title=frappe._("Unsupported SARS Filing Format"),
	)
