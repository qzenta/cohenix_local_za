"""Gate B: a Customer must have a Customer Group and a Supplier must have a Supplier Group.

Registered through doc_events "validate" for Customer and Supplier (za_local hooks.py), so it runs for every save path
that goes through Document.insert or Document.save: Desk form and quick entry, REST (/api/resource and frappe.client),
Data Import, and server code. It applies to every user, Administrator included: this is a data integrity rule, not an
access rule. No permission, role or setting is read or changed (Apply Strict User Permissions is untouched).

Rule:
- insert: a blank group is rejected;
- update: a save that blanks a group that was set is rejected;
- an existing record that was already blank before this rule is not changed and can still be saved without a group
  (no backfill; that is a separate decision). Its first save with a group set is accepted as normal.
"""

import frappe
from frappe import _

RULES = {
	"Customer": ("customer_group", "Customer Group"),
	"Supplier": ("supplier_group", "Supplier Group"),
}


def is_blank(value) -> bool:
	return not (value or "").strip() if isinstance(value, str) or value is None else False


def blanks_group(is_new: bool, current, previous, has_previous: bool) -> bool:
	"""True when this save must be rejected. Pure function, no site needed."""
	if not is_blank(current):
		return False
	if is_new:
		return True
	if has_previous and is_blank(previous):
		return False  # legacy blank record, this save does not blank it
	return True


def message(doctype: str, name: str | None) -> str:
	field_label = RULES[doctype][1]
	return _("{0} is required. Choose a {0} for {1} {2} before saving.").format(
		_(field_label), _(doctype), name or _("(new)")
	)


def _validate(doc, doctype: str) -> None:
	fieldname, label = RULES[doctype]
	is_new = doc.is_new()
	previous_doc = None if is_new else doc.get_doc_before_save()
	previous = previous_doc.get(fieldname) if previous_doc is not None else None
	if blanks_group(is_new, doc.get(fieldname), previous, previous_doc is not None):
		frappe.throw(message(doctype, doc.name), frappe.ValidationError, title=_("Missing {0}").format(_(label)))


def validate_customer_group(doc, method=None):
	_validate(doc, "Customer")


def validate_supplier_group(doc, method=None):
	_validate(doc, "Supplier")
