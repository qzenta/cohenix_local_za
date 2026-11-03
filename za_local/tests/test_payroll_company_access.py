"""P0-6c: payroll reports and payroll data fetches are HR Manager only and company-scoped.

The shared check ``za_local.utils.payroll_permissions.require_payroll_company_access(company)`` must, before any
payroll SQL runs: require role HR Manager (frappe.only_for), require role-level read on Salary Slip, and require the
company to be in the user's Company User Permissions that apply to Salary Slip (unscoped, or scoped to Salary Slip).
A user with no such User Permission is not company-restricted (Frappe's own rule). These tests need no site.
"""

import json
import re
import unittest
from pathlib import Path
from unittest import mock

import frappe

APP = Path(__file__).resolve().parents[1]
HELPER_CALL = "require_payroll_company_access("
# (file, function containing the guarded data access, first data-access marker inside it)
ENTRY_POINTS = [
	("sa_payroll/report/payroll_register/payroll_register.py", "_validate_filters", None),
	("sa_payroll/report/department_cost_analysis/department_cost_analysis.py", "_validate_filters", None),
	("sa_payroll/report/retirement_fund_deductions/retirement_fund_deductions.py", "_validate_filters", None),
	("sa_payroll/report/statutory_submissions_summary/statutory_submissions_summary.py", "_validate_filters", None),
	("sa_payroll/doctype/emp201_submission/emp201_submission.py", "fetch_emp201_data", 'frappe.get_all(\n\t\t\t"Salary Slip"'),
	("sa_payroll/doctype/irp5_certificate/irp5_certificate.py", "bulk_generate_certificates", 'frappe.get_all("Employee"'),
	("sa_coida/doctype/coida_annual_return/coida_annual_return.py", "fetch_employee_data", "get_coida_earnings_by_employee("),
]
REPORT_JSONS = [
	"sa_payroll/report/payroll_register/payroll_register.json",
	"sa_payroll/report/department_cost_analysis/department_cost_analysis.json",
	"sa_payroll/report/retirement_fund_deductions/retirement_fund_deductions.json",
	"sa_payroll/report/statutory_submissions_summary/statutory_submissions_summary.json",
]


def _function_source(path, name):
	src = (APP / path).read_text(encoding="utf-8")
	m = re.search(rf"^(\s*)def {name}\(.*?(?=^\1def |^\1@|\Z)", src, re.S | re.M)
	if not m:
		raise AssertionError(f"{name} not found in {path}")
	return m.group(0)


def _raise(msg, exc=frappe.ValidationError, *args, **kwargs):
	# frappe.throw cannot build its message without a site; raise the exception class it would raise
	raise exc(msg)


def _helper():
	from za_local.utils import payroll_permissions

	return payroll_permissions


class TestRequirePayrollCompanyAccess(unittest.TestCase):
	def _run(self, company="RC Payroll Co B", roles=("HR Manager",), user_perms=None, ss_read=True, user="u@x.test"):
		mod = _helper()
		def fake_only_for(required, *args, **kwargs):
			required = (required,) if isinstance(required, str) else tuple(required)
			if not set(required) & set(roles):
				raise frappe.PermissionError

		only_for = mock.Mock(side_effect=fake_only_for)
		with mock.patch.object(mod.frappe, "only_for", only_for), \
			mock.patch.object(mod, "get_user_permissions", return_value=user_perms or {}), \
			mock.patch.object(mod, "get_role_permissions", return_value={"read": 1 if ss_read else 0}), \
			mock.patch.object(mod.frappe, "get_meta", return_value=object()), \
			mock.patch.object(mod.frappe, "throw", side_effect=_raise), \
			mock.patch.object(mod.frappe, "session", frappe._dict(user=user), create=True):
			mod.require_payroll_company_access(company)
		return only_for

	def test_requires_hr_manager_only(self):
		only_for = self._run(user_perms={})
		only_for.assert_called_once()
		self.assertEqual(only_for.call_args.args[0], "HR Manager")
		with self.assertRaises(frappe.PermissionError):
			self._run(roles=("Accounts Manager",))

	def test_requires_role_level_salary_slip_read(self):
		with self.assertRaises(frappe.PermissionError):
			self._run(ss_read=False)

	def test_unscoped_company_permission_restricts(self):
		perms = {"Company": [frappe._dict(doc="RC Payroll Co", applicable_for=None)]}
		with self.assertRaises(frappe.PermissionError):
			self._run(company="RC Payroll Co B", user_perms=perms)
		self._run(company="RC Payroll Co", user_perms=perms)

	def test_salary_slip_scoped_company_permission_restricts(self):
		perms = {"Company": [frappe._dict(doc="RC Payroll Co", applicable_for="Salary Slip")]}
		with self.assertRaises(frappe.PermissionError):
			self._run(company="RC Payroll Co B", user_perms=perms)
		self._run(company="RC Payroll Co", user_perms=perms)

	def test_permission_scoped_to_other_doctype_does_not_apply(self):
		perms = {"Company": [frappe._dict(doc="RC Payroll Co", applicable_for="Employee")]}
		self._run(company="RC Payroll Co B", user_perms=perms)

	def test_no_company_permission_is_unrestricted(self):
		self._run(company="RC Payroll Co B", user_perms={})

	def test_missing_company_is_refused(self):
		with self.assertRaises(frappe.PermissionError):
			self._run(company=None, user_perms={})


class TestEntryPointsUseSharedCheck(unittest.TestCase):
	def test_helper_defined_once(self):
		hits = [p for p in APP.rglob("*.py") if re.search(r"^def require_payroll_company_access\(", p.read_text(encoding="utf-8"), re.M)]
		self.assertEqual([p.relative_to(APP).as_posix() for p in hits], ["utils/payroll_permissions.py"])

	def test_each_entry_point_calls_check_before_data_access(self):
		for path, func, marker in ENTRY_POINTS:
			with self.subTest(path=path):
				body = _function_source(path, func)
				self.assertIn(HELPER_CALL, body, f"{func} in {path} does not call the shared check")
				if marker:
					self.assertIn(marker, body)
					self.assertLess(body.index(HELPER_CALL), body.index(marker), f"check must run before {marker!r}")

	def test_report_validation_calls_check_with_company(self):
		import importlib

		for path, _func, _marker in ENTRY_POINTS[:4]:
			with self.subTest(path=path):
				mod = importlib.import_module("za_local." + path[:-3].replace("/", "."))
				with mock.patch.object(mod, "require_payroll_company_access", create=True) as check, \
					mock.patch.object(mod.frappe, "has_permission", return_value=True):
					mod._validate_filters({"company": "RC Payroll Co B", "from_date": "2026-04-01", "to_date": "2026-04-30"})
				check.assert_called_once_with("RC Payroll Co B")

	def test_report_roles_hr_manager_only(self):
		for path in REPORT_JSONS:
			with self.subTest(path=path):
				roles = [r["role"] for r in json.loads((APP / path).read_text(encoding="utf-8"))["roles"]]
				self.assertEqual(roles, ["HR Manager"])


if __name__ == "__main__":
	unittest.main(verbosity=1)
