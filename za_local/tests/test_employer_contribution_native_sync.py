"""Option C (P0-4): HRMS must post exactly za_local's company contributions.

HRMS posts employer contributions from the slip's native ``employer_contributions`` table. Before this change that
table came only from Salary Structure formulas on gross pay, so an earning flagged za_uif_applicable=0 or
za_sdl_applicable=0 was included natively but excluded by za_local (bench-rc run p04-20261103T122118Z: GL over-posted
by 60.00). ``sync_native_employer_contributions`` replaces the native rows with the final ``company_contribution``
rows. These tests need no site: the slip is a stub and the component lookup is patched.
"""

import inspect
import unittest
from types import SimpleNamespace
from unittest import mock

from za_local.overrides import salary_slip as module
from za_local.overrides.salary_slip import ZASalarySlip


class _Slip:
	sync_native_employer_contributions = ZASalarySlip.sync_native_employer_contributions

	def __init__(self, company_contribution, employer_contributions, has_field=True):
		self.meta = SimpleNamespace(has_field=lambda f: has_field and f == "employer_contributions")
		self._tables = {"company_contribution": company_contribution, "employer_contributions": employer_contributions}

	def get(self, key, default=None):
		return self._tables.get(key, default)

	def set(self, key, value):
		self._tables[key] = list(value)

	def append(self, key, row):
		self._tables.setdefault(key, []).append(SimpleNamespace(**row))


def _row(component, amount):
	return SimpleNamespace(salary_component=component, amount=amount)


class TestEmployerContributionNativeSync(unittest.TestCase):
	def setUp(self):
		patcher = mock.patch.object(module.frappe, "get_cached_value", side_effect=lambda dt, name, f: name[:3].upper())
		patcher.start()
		self.addCleanup(patcher.stop)

	def test_native_rows_replaced_by_company_contribution_values(self):
		# native formula rows on gross 12,000 (120/120); za_local statutory basis 10,000 (100/100)
		slip = _Slip([_row("UIF Employer Contribution", 100.0), _row("SDL Contribution", 100.0)],
		             [_row("UIF Employer Contribution", 120.0), _row("SDL Contribution", 120.0)])
		slip.sync_native_employer_contributions()
		got = {r.salary_component: (r.amount, r.default_amount) for r in slip.get("employer_contributions")}
		self.assertEqual(got, {"UIF Employer Contribution": (100.0, 100.0), "SDL Contribution": (100.0, 100.0)})

	def test_each_component_once_and_zero_rows_dropped(self):
		slip = _Slip([_row("UIF Employer Contribution", 177.12), _row("SDL Contribution", 0)], [])
		slip.sync_native_employer_contributions()
		rows = slip.get("employer_contributions")
		self.assertEqual([(r.salary_component, r.amount) for r in rows], [("UIF Employer Contribution", 177.12)])
		self.assertEqual(rows[0].depends_on_payment_days, 0)

	def test_no_native_table_is_a_no_op(self):
		native = [_row("SDL Contribution", 5.0)]
		slip = _Slip([_row("SDL Contribution", 300.0)], native, has_field=False)
		slip.sync_native_employer_contributions()
		self.assertIs(slip.get("employer_contributions"), native)

	def test_called_after_statutory_amounts(self):
		src = inspect.getsource(ZASalarySlip.calculate_company_contributions)
		self.assertLess(src.index("apply_statutory_company_contribution_amounts()"),
		                src.index("sync_native_employer_contributions()"))


if __name__ == "__main__":
	unittest.main()
