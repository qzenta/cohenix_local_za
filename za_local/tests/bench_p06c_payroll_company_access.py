"""P0-6c bench test (bench-rc only, synthetic users and data): an HR Manager restricted to company A must not run
payroll reports, exports or payroll data fetches for company B.

Not a unittest module (no test_ prefix): it needs the bench-rc site and its P0-4 synthetic payroll (company A).
Run inside the bench container from frappe-bench/sites:
    ../env/bin/python ../apps/za_local/za_local/tests/bench_p06c_payroll_company_access.py rc.localhost

In-process as each user (frappe.set_user), entry points dispatched the way Frappe dispatches them:
reports through frappe.desk.query_report.run / export_query (report role and ref-doctype checks apply), doctype
methods through frappe.get_doc(..., check_permission=True) like frappe.handler.run_doc_method. Every call is rolled
back. Users have no password (never logged in). Company B has no payroll on bench-rc, so for company B the assertion
is "refused with PermissionError"; anything else (rows returned, an empty result, another error after the data query)
is NOT_DENIED and FAILs. Company A calls are positive controls (must not be PermissionError).

User Permission variants for the company A users: "unscoped" (apply_to_all_doctypes=1) and "salary_slip"
(apply_to_all_doctypes=0, applicable_for=Salary Slip).
Users: hrm_a = HR Manager; hrm_a_doc = HR Manager + Payroll Manager + System Manager (EMP201 Submission and IRP5
Certificate grant doc access only to Payroll Manager / Accounts User and System Manager); am_a = Accounts Manager.
Prints one line per check and P06CJSON; exit 1 on any FAIL.
"""
import json
import sys
from datetime import datetime, timezone

import frappe

CO_A, CO_B = "RC Payroll Co", "RC Payroll Co B"
START, END = "2026-04-01", "2026-04-30"
USERS = {
	"hrm_a": ("p06c.hrm.a@rc-payroll.test", ["HR Manager"]),
	"hrm_a_doc": ("p06c.hrm.a.doc@rc-payroll.test", ["HR Manager", "Payroll Manager", "System Manager"]),
	"am_a": ("p06c.am.a@rc-payroll.test", ["Accounts Manager"]),
}
REPORTS = {
	"Payroll Register": lambda co: {"company": co, "from_date": START, "to_date": END},
	"Department Cost Analysis": lambda co: {"company": co, "from_date": START, "to_date": END},
	"Retirement Fund Deductions": lambda co: {"company": co, "from_date": START, "to_date": END},
	"Statutory Submissions Summary": lambda co: {"company": co, "from_date": START, "to_date": END},
}


def ensure_user(email, roles):
	if not frappe.db.exists("User", email):
		frappe.get_doc({"doctype": "User", "email": email, "first_name": "P06C", "last_name": email.split("@")[0],
		                "user_type": "System User", "send_welcome_email": 0, "enabled": 1}).insert(ignore_permissions=True)
	u = frappe.get_doc("User", email)
	if {r.role for r in u.roles} != set(roles):
		u.set("roles", [{"role": r} for r in roles])
		u.save(ignore_permissions=True)


def set_company_permission(email, variant):
	frappe.db.delete("User Permission", {"user": email, "allow": "Company"})
	row = {"doctype": "User Permission", "user": email, "allow": "Company", "for_value": CO_A}
	row.update({"apply_to_all_doctypes": 1} if variant == "unscoped" else {"apply_to_all_doctypes": 0, "applicable_for": "Salary Slip"})
	frappe.get_doc(row).insert(ignore_permissions=True)
	frappe.clear_cache(user=email)


def report_run(name, co):
	from frappe.desk.query_report import run
	res = run(name, filters=json.dumps(REPORTS[name](co)), ignore_prepared_report=True)
	return f"{len(res.get('result') or [])} rows"


def report_export(name, co):
	from frappe.desk.query_report import export_query
	frappe.local.form_dict = frappe._dict({"report_name": name, "file_format_type": "CSV",
	                                       "filters": json.dumps(REPORTS[name](co)), "include_indentation": 0})
	export_query()
	return f"export {len(frappe.response.get('filecontent') or b'')} bytes"


def emp201_fetch(co):
	doc = frappe.get_doc({"doctype": "EMP201 Submission", "company": co, "submission_period_start_date": START,
	                      "submission_period_end_date": END}, check_permission=True)
	out = doc.fetch_emp201_data()
	return f"fetched {type(out).__name__}"


def coida_fetch(co):
	doc = frappe.get_doc({"doctype": "COIDA Annual Return", "company": co, "from_date": "2026-03-01",
	                      "to_date": "2027-02-28", "industry_class": "P06C synthetic"}, check_permission=True)
	doc.fetch_employee_data()
	return f"fetched {doc.total_employees} employees"


def irp5_bulk(co):
	from za_local.sa_payroll.doctype.irp5_certificate.irp5_certificate import bulk_generate_certificates
	out = bulk_generate_certificates(json.dumps({"company": co, "tax_year": "2027", "from_date": "2026-03-01",
	                                             "to_date": "2027-02-28", "reconciliation_period": "Annual"}))
	return f"returned {sorted(out) if isinstance(out, dict) else type(out).__name__}"


def attempt(user, fn, *args):
	frappe.set_user(user)
	try:
		detail = fn(*args)
		outcome = "NOT_DENIED"
	except frappe.PermissionError as exc:
		outcome, detail = "DENIED", type(exc).__name__
	except Exception as exc:  # another error after the permission point: the data path was reached
		outcome, detail = "NOT_DENIED", f"{type(exc).__name__}: {str(exc)[:80]}"
	finally:
		frappe.db.rollback()
		frappe.set_user("Administrator")
		frappe.local.message_log = []
	return outcome, detail


def main(site):
	if site != "rc.localhost":
		raise SystemExit("refusing: runs only on the throwaway bench-rc site rc.localhost")
	frappe.init(site=site, sites_path=".")
	frappe.connect()
	frappe.set_user("Administrator")
	run_id = "p06c-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
	results = []
	try:
		if not frappe.db.count("Salary Slip", {"company": CO_A, "start_date": START, "docstatus": 1}):
			raise SystemExit("no company A payroll for 2026-04; run p04_setup_rc.py first")
		for email, roles in USERS.values():
			ensure_user(email, roles)
		frappe.db.commit()
		checks = []
		for variant in ("unscoped", "salary_slip"):
			for key in USERS:
				set_company_permission(USERS[key][0], variant)
			frappe.db.commit()
			for name in REPORTS:
				checks.append((variant, "hrm_a", f"report_run[{name}]", report_run, (name, CO_B), "DENIED"))
				checks.append((variant, "hrm_a", f"report_run[{name}]", report_run, (name, CO_A), "NOT_DENIED"))
				checks.append((variant, "am_a", f"report_run[{name}]", report_run, (name, CO_A), "DENIED"))
			checks.append((variant, "hrm_a", "report_export[Payroll Register]", report_export, ("Payroll Register", CO_B), "DENIED"))
			checks.append((variant, "hrm_a", "report_export[Payroll Register]", report_export, ("Payroll Register", CO_A), "NOT_DENIED"))
			checks.append((variant, "hrm_a", "coida_fetch_employee_data", coida_fetch, (CO_B,), "DENIED"))
			checks.append((variant, "hrm_a", "coida_fetch_employee_data", coida_fetch, (CO_A,), "NOT_DENIED"))
			checks.append((variant, "hrm_a_doc", "emp201_fetch_emp201_data", emp201_fetch, (CO_B,), "DENIED"))
			checks.append((variant, "hrm_a_doc", "emp201_fetch_emp201_data", emp201_fetch, (CO_A,), "NOT_DENIED"))
			checks.append((variant, "hrm_a_doc", "irp5_bulk_generate_certificates", irp5_bulk, (CO_B,), "DENIED"))
			for v, ukey, path, fn, args, expected in [c for c in checks if c[0] == variant]:
				outcome, detail = attempt(USERS[ukey][0], fn, *args)
				company = "B" if CO_B in args else "A"
				results.append({"id": f"P06C-{path}[{ukey},{v},company {company}]", "expected": expected,
				                "outcome": outcome, "detail": detail, "result": "PASS" if outcome == expected else "FAIL"})
	finally:
		frappe.destroy()
	for r in results:
		print(f'{r["id"]} {r["result"]}: expected {r["expected"]} | actual {r["outcome"]} ({r["detail"]})')
	summary = {s: sum(r["result"] == s for r in results) for s in ("PASS", "FAIL")}
	print("P06CJSON " + json.dumps({"run_id": run_id, "site": site, "results": results, "summary": summary}, default=str))
	sys.exit(1 if summary["FAIL"] else 0)


if __name__ == "__main__":
	main(sys.argv[1])
