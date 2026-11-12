import frappe
from frappe import _
from frappe.model.document import Document


class EMP501IRP5Reference(Document):
    """Child row of EMP501 Reconciliation. It is written only through its parent.

    A direct insert or save of a row (frappe.client.save, savedocs, bulk_update) is refused
    before Frappe's link validation and before any lookup of the referenced IRP5 Certificate,
    so the answer is the same whether that record exists, is foreign, or does not exist,
    and no value of the certificate is copied into the row.
    The parent writes its rows with db_insert and db_update and never calls these methods.
    """

    def _refuse_direct_write(self):
        frappe.throw(
            _("IRP5 references can only be changed by saving the EMP501 Reconciliation."),
            frappe.PermissionError,
        )

    def insert(self, *args, **kwargs):
        self._refuse_direct_write()

    def save(self, *args, **kwargs):
        self._refuse_direct_write()

    def validate(self):
        self._refuse_direct_write()
