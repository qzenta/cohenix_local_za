import frappe
from frappe.permissions import add_permission

DOCTYPE = "Fiscal Year"
ROLE = "HR Manager"
OTHER_FLAGS = (
    "select", "write", "create", "delete", "submit", "cancel", "amend",
    "report", "export", "import", "share", "print", "email", "if_owner",
)


def ensure_hr_manager_fiscal_year_read():
    """Governance ruling 7 Nov 2026 (E8 / G-7): one role-level, read-only
    Custom DocPerm for HR Manager on Fiscal Year (permlevel 0).
    Idempotent. Goes through add_permission so Frappe copies the standard
    DocPerm rows first and no existing role loses access."""
    if not frappe.db.exists("DocType", DOCTYPE) or not frappe.db.exists("Role", ROLE):
        return
    add_permission(DOCTYPE, ROLE, 0, "read")
    name = frappe.db.get_value(
        "Custom DocPerm",
        {"parent": DOCTYPE, "role": ROLE, "permlevel": 0, "if_owner": 0},
    )
    if not name:
        return
    meta = frappe.get_meta("Custom DocPerm")
    values = {f: 0 for f in OTHER_FLAGS if meta.has_field(f)}
    values["read"] = 1
    frappe.db.set_value("Custom DocPerm", name, values, update_modified=False)
    frappe.clear_cache(doctype=DOCTYPE)
