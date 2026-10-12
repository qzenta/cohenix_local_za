"""Regression coverage for DEFECT-004: PAYE over-deducted by cents because the seeded
Income Tax Slab bands ended in .99.

HRMS ``calculate_base_tax_from_tax_slabs`` taxes every fully crossed band on
``(to_amount - from_amount + 1) x rate``. That is exact only when ``to_amount`` is the whole
number just below the next band's ``from_amount``. The shipped slab files used x.99 band tops,
so each fully crossed band was taxed on 0.99 too much (annual excess 0.99 x the sum of the
rates of the crossed bands).

This test is a pure-function check: no fixtures, no database writes. The in-memory
Income Tax Slab documents are never inserted. The oracle is the statutory_rates_20xx.json
PAYE bracket table (base_tax, rate, amount_over), which is a separate source from the slab files.

Accepted residual (operator decision, 12 Oct 2026): with whole-number bands, income that falls
within one rand above a band top (strictly between L and L + 1) is under-taxed by at most
the next rate x (income - L). It is never over-taxed. The last test pins that bound.
"""

import json
import random
import unittest
from decimal import Decimal

import frappe

from za_local.tests.compat import UnitTestCase
from za_local.utils.file_utils import resolve_app_path
from za_local.utils.hrms_detection import is_hrms_installed

FILE_PAIRS = (
	("tax_slabs_2025.json", "statutory_rates_2025.json"),
	("tax_slabs_2026.json", "statutory_rates_2026.json"),
	("tax_slabs_2027.json", "statutory_rates_2027.json"),
)
TOP_BAND_TO_AMOUNT = 999999999
TOLERANCE = Decimal("0.000001")


def _load(name):
	path = resolve_app_path("sa_setup", "data") / name
	with open(path, encoding="utf-8") as handle:
		return json.load(handle)


def _slab_rows(slab_file):
	records = _load(slab_file)
	return (records if isinstance(records, list) else [records])[0]["slabs"]


def _brackets(rates_file):
	return _load(rates_file)["paye"]["brackets"]


def _exact_tax(brackets, income):
	"""Exact annual tax before rebates, from the rate pack, in Decimal."""
	income = Decimal(str(income))
	if income <= 0:
		return Decimal(0)
	bracket = [b for b in brackets if income > Decimal(b["amount_over"])][-1]
	return Decimal(bracket["base_tax"]) + (income - Decimal(bracket["amount_over"])) * Decimal(bracket["rate"]) / 100


def _slab_doc(rows):
	"""In-memory Income Tax Slab, never inserted."""
	return frappe.get_doc(
		{
			"doctype": "Income Tax Slab",
			"currency": "ZAR",
			"allow_tax_exemption": 1,
			"standard_tax_exemption_amount": 0,
			"tax_relief_limit": 0,
			"disabled": 0,
			"slabs": [
				{
					"from_amount": row["from_amount"],
					"to_amount": row["to_amount"],
					"percent_deduction": row["percent_deduction"],
				}
				for row in rows
			],
		}
	)


def _hrms_tax(doc, income):
	from hrms.payroll.doctype.income_tax_slab.income_tax_slab import calculate_tax_by_tax_slab

	return Decimal(str(calculate_tax_by_tax_slab(float(income), doc)[0]))


def _band_tops(brackets):
	"""The whole-number band tops L_k (k >= 1) that the slab files must use."""
	return [int(b["amount_over"]) for b in brackets[1:]]


def _in_one_rand_window(income, tops):
	return any(Decimal(top) < income < Decimal(top) + 1 for top in tops)


class TestTaxSlabBoundsRegression(UnitTestCase):
	def setUp(self):
		if not is_hrms_installed():
			raise unittest.SkipTest("HRMS is not installed")

	def test_bands_are_contiguous_whole_numbers_and_match_the_rate_pack(self):
		for slab_file, rates_file in FILE_PAIRS:
			with self.subTest(slab_file=slab_file):
				rows = _slab_rows(slab_file)
				brackets = _brackets(rates_file)
				self.assertEqual(len(rows), len(brackets), "one slab band per PAYE bracket")
				for index, (row, bracket) in enumerate(zip(rows, brackets, strict=True)):
					is_top = index == len(rows) - 1
					expected_from = 1 if index == 0 else int(bracket["amount_over"]) + 1
					expected_to = TOP_BAND_TO_AMOUNT if is_top else int(bracket["to_amount"])
					for field in ("from_amount", "to_amount"):
						self.assertTrue(
							float(row[field]).is_integer(),
							f"{slab_file} band {index}: {field} {row[field]!r} must be a whole number",
						)
					self.assertEqual(Decimal(str(row["from_amount"])), Decimal(expected_from), f"{slab_file} band {index} from_amount")
					self.assertEqual(Decimal(str(row["to_amount"])), Decimal(expected_to), f"{slab_file} band {index} to_amount")
					self.assertEqual(Decimal(str(row["percent_deduction"])), Decimal(str(bracket["rate"])), f"{slab_file} band {index} rate")
					if not is_top:
						self.assertEqual(
							Decimal(str(rows[index + 1]["from_amount"])),
							Decimal(str(row["to_amount"])) + 1,
							f"{slab_file} band {index + 1} must start one above band {index} top",
						)

	def test_rate_pack_oracle_is_continuous(self):
		for _slab_file, rates_file in FILE_PAIRS:
			with self.subTest(rates_file=rates_file):
				brackets = _brackets(rates_file)
				for lower, upper in zip(brackets, brackets[1:], strict=False):
					width = Decimal(upper["amount_over"]) - Decimal(lower["amount_over"])
					self.assertEqual(
						Decimal(upper["base_tax"]),
						Decimal(lower["base_tax"]) + width * Decimal(lower["rate"]) / 100,
						f"{rates_file}: base_tax is not continuous at {upper['amount_over']}",
					)

	def test_hrms_tax_equals_exact_tax_at_boundaries_and_for_random_incomes(self):
		for slab_file, rates_file in FILE_PAIRS:
			with self.subTest(slab_file=slab_file):
				doc = _slab_doc(_slab_rows(slab_file))
				brackets = _brackets(rates_file)
				tops = _band_tops(brackets)
				incomes = [Decimal(top + offset) for top in tops for offset in range(-3, 4)]
				incomes += [Decimal(i) for i in range(0, 4)]
				rng = random.Random(20261012)
				incomes += [Decimal(rng.randint(0, 250000000)) / 100 for _ in range(2000)]
				for income in incomes:
					if _in_one_rand_window(income, tops):
						continue
					got = _hrms_tax(doc, income)
					exact = _exact_tax(brackets, income)
					self.assertAlmostEqual(
						float(got - exact),
						0.0,
						places=5,
						msg=f"{slab_file}: income {income} is taxed {got} but exact tax is {exact}",
					)

	def test_accepted_residual_is_never_an_over_deduction_and_is_bounded(self):
		for slab_file, rates_file in FILE_PAIRS:
			with self.subTest(slab_file=slab_file):
				doc = _slab_doc(_slab_rows(slab_file))
				brackets = _brackets(rates_file)
				for bracket in brackets[1:]:
					top = Decimal(bracket["amount_over"])
					rate = Decimal(bracket["rate"]) / 100
					for cents in range(1, 101):
						income = top + Decimal(cents) / 100
						error = _hrms_tax(doc, income) - _exact_tax(brackets, income)
						self.assertLessEqual(error, TOLERANCE, f"{slab_file}: income {income} is over-taxed by {error}")
						self.assertGreaterEqual(
							error,
							-rate * (income - top) - TOLERANCE,
							f"{slab_file}: income {income} is under-taxed by more than the accepted residual ({error})",
						)
