"""E8 / G-7: HR Manager read access on Fiscal Year and EMP201 Submission (Governance rulings, 7 Nov 2026).

Two role-level Custom DocPerms, permlevel 0, every other flag explicitly 0:
- Fiscal Year / HR Manager / read=1
- EMP201 Submission / HR Manager / read=1, report=1

Granted only when the fail-closed Company scoping hooks for EMP201 Submission are registered
(emp201_company_scope.py). Otherwise nothing is granted. Idempotent. Goes through add_permission so Frappe
first copies the standard DocPerm rows into Custom DocPerm and no existing role loses access.
"""

import frappe
from frappe.permissions import add_permission

ROLE = "HR Manager"
SCOPED_DOCTYPE = "EMP201 Submission"
SCOPE_MODULE = "za_local.emp201_company_scope."
GRANTS = (
	("Fiscal Year", ("read",)),
	("EMP201 Submission", ("read", "report")),
)
FLAGS = (
	"read", "select", "write", "create", "delete", "submit", "cancel", "amend", "report",
	"export", "import", "share", "print", "email", "if_owner", "impersonate", "mask",
)


def scoping_hooks_registered():
	"""True when both the list and the document hook for EMP201 Submission point at the scoping module."""
	for hook in ("permission_query_conditions", "has_permission"):
		methods = (frappe.get_hooks(hook, {}) or {}).get(SCOPED_DOCTYPE, [])
		if not any(str(m).startswith(SCOPE_MODULE) for m in methods):
			return False
	return True


def ensure_hr_manager_emp201_access():
	if not frappe.db.exists("Role", ROLE):
		return
	if not scoping_hooks_registered():
		print("E8: EMP201 Submission scoping hooks are not registered, HR Manager grants skipped")
		return
	for doctype, ptypes in GRANTS:
		_ensure_grant(doctype, ptypes)


def _ensure_grant(doctype, ptypes):
	if not frappe.db.exists("DocType", doctype):
		return
	add_permission(doctype, ROLE, 0, ptypes[0])
	name = frappe.db.get_value(
		"Custom DocPerm", {"parent": doctype, "role": ROLE, "permlevel": 0, "if_owner": 0}
	)
	if not name:
		return
	meta = frappe.get_meta("Custom DocPerm")
	values = {f: 0 for f in FLAGS if meta.has_field(f)}
	for ptype in ptypes:
		values[ptype] = 1
	frappe.db.set_value("Custom DocPerm", name, values, update_modified=False)
	frappe.clear_cache(doctype=doctype)
