import unittest
from pathlib import Path

import frappe

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_PATH = PACKAGE_ROOT / "templates" / "print_format" / "sa_commercial_document.html"

# The VAT-registration-status block sits between these two `{% set %}` lines
# in sa_commercial_document.html. Extracting it by marker (rather than
# duplicating the logic here) keeps this test tracking the live template
# instead of a hand-copied snapshot that could silently drift from it.
_START_MARKER = "{% set company_is_vat_registered ="
_END_MARKER = "{% set inferred_profile ="


def _vat_status_snippet():
	src = TEMPLATE_PATH.read_text()
	start = src.index(_START_MARKER)
	end = src.index(_END_MARKER)
	return src[start:end]


class _MetaStub:
	def __init__(self, fields=()):
		self._fields = set(fields)

	def has_field(self, fieldname):
		return fieldname in self._fields


class _DocStub(frappe._dict):
	"""Minimal stand-in for a Company/Customer/Supplier doc, since the
	template only calls .get() on it and, for party_doc, .meta.has_field()."""

	def __init__(self, data, fields=()):
		super().__init__(data)
		object.__setattr__(self, "meta", _MetaStub(fields))


class TestSACommercialDocumentVatRegistrationStatus(unittest.TestCase):
	"""Regression coverage for the VAT-registration-status fix to
	sa_commercial_document.html (Sep 2026): before this fix, party VAT
	numbers were shown whenever a `tax_id` was present, with no check of
	whether the party was actually a registered VAT vendor. This produced
	incorrect "VAT registered" evidence on real commercial documents.
	"""

	@staticmethod
	def _render(company_doc, party_doc):
		render_expr = (
			_vat_status_snippet()
			+ "{{ company_is_vat_registered }}|{{ company_vat }}|"
			+ "{{ party_has_vat_flag_field }}|{{ party_is_vat_registered }}|{{ party_vat }}"
		)
		return frappe.render_template(render_expr, {"company_doc": company_doc, "party_doc": party_doc}).strip()

	def test_company_with_vat_number_is_registered(self):
		company_doc = _DocStub({"za_vat_number": "4123456789"})
		party_doc = _DocStub({"tax_id": "999", "za_is_vat_vendor": True}, fields=["za_is_vat_vendor"])
		out = self._render(company_doc, party_doc)
		self.assertEqual(out, "True|4123456789|True|True|999")

	def test_company_without_vat_number_is_not_registered(self):
		company_doc = _DocStub({})
		party_doc = _DocStub({"tax_id": "999", "za_is_vat_vendor": True}, fields=["za_is_vat_vendor"])
		out = self._render(company_doc, party_doc)
		self.assertEqual(out, "False||True|True|999")

	def test_party_with_tax_id_but_za_is_vat_vendor_false_is_not_registered(self):
		"""The bug this fix addresses: a tax_id alone used to be treated as
		proof of VAT registration. A party can have a tax_id (e.g. an income
		tax reference) without being VAT-registered - za_is_vat_vendor is
		the actual source of truth once the field exists."""
		company_doc = _DocStub({"za_vat_number": "4123456789"})
		party_doc = _DocStub({"tax_id": "999", "za_is_vat_vendor": False}, fields=["za_is_vat_vendor"])
		out = self._render(company_doc, party_doc)
		self.assertEqual(out, "True|4123456789|True|False|")

	def test_party_doctype_without_za_is_vat_vendor_field_falls_back_to_tax_id(self):
		"""Backward compatibility: if the installed party doctype doesn't
		carry the za_is_vat_vendor custom field at all, fall back to the
		old tax_id-presence check rather than failing closed."""
		company_doc = _DocStub({"za_vat_number": "4123456789"})
		party_doc = _DocStub({"tax_id": "999"}, fields=[])
		out = self._render(company_doc, party_doc)
		self.assertEqual(out, "True|4123456789|False|True|999")

	def test_missing_company_and_party_docs_render_safely(self):
		out = self._render(None, None)
		self.assertEqual(out, "False||False|False|")
