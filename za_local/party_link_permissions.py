"""Contact and Address visibility follows the Customer and Supplier they link to.

Contact and Address have no Company field, so a Company User Permission cannot scope them. This module
links their visibility to the company-scoped party: a Contact or Address with a Dynamic Link to a Customer
or Supplier is visible only when the user may read that party, judged from the user's User Permissions on
Customer Group, Supplier Group, Customer and Supplier (groups expanded to descendants through lft and rgt).

- Administrator and System Manager: no restriction.
- A party type the user has no applicable User Permission for is unrestricted.
- A record with no Customer or Supplier link is left unchanged.
- A blank party group counts as readable unless Apply Strict User Permissions is on (Frappe's own rule).

Nothing is created per record. The SQL builder and the party check are pure functions for unit testing.
"""

import frappe
from frappe.utils import cint

TARGET_DOCTYPES = ("Contact", "Address")
PARTY_GROUP = {
	"Customer": ("Customer Group", "customer_group"),
	"Supplier": ("Supplier Group", "supplier_group"),
}
UNRESTRICTED_ROLES = ("System Manager",)


# ---------------------------------------------------------------------------
# Pure helpers (no database access)
# ---------------------------------------------------------------------------


def party_allowed(party_name, party_group, restriction, strict=False):
	"""True when a party with this name and group passes the restriction.

	restriction: {"groups": list | None, "names": list | None}; None means no restriction of that kind.
	"""
	if not restriction:
		return True
	groups, names = restriction.get("groups"), restriction.get("names")
	if groups is not None:
		if party_group:
			if party_group not in groups:
				return False
		elif strict:
			return False
	if names is not None and party_name not in names:
		return False
	return True


def build_party_allowed_sql(alias, group_field, restriction, escape, strict=False):
	"""SQL predicate on `alias` (a Customer or Supplier row) that mirrors party_allowed. Empty when unrestricted."""
	if not restriction:
		return ""
	parts = []
	groups, names = restriction.get("groups"), restriction.get("names")
	if groups is not None:
		blank = f"ifnull({alias}.`{group_field}`, '') = ''"
		if groups:
			in_groups = f"{alias}.`{group_field}` in ({', '.join(escape(g) for g in groups)})"
			parts.append(in_groups if strict else f"({in_groups} or {blank})")
		else:
			parts.append("1 = 0" if strict else blank)
	if names is not None:
		parts.append(f"{alias}.`name` in ({', '.join(escape(n) for n in names)})" if names else "1 = 0")
	return " and ".join(parts)


def build_party_link_condition(doctype, restrictions, escape, strict=False):
	"""Permission query condition for Contact or Address.

	A row is hidden when it has a Dynamic Link to a Customer or Supplier that fails the user's restriction.
	restrictions: {"Customer": restriction, "Supplier": restriction} as in party_allowed.
	escape: a quoting function, frappe.db.escape at runtime. Returns "" when nothing is restricted.
	"""
	if doctype not in TARGET_DOCTYPES:
		return ""
	conditions = []
	for party, (_group_doctype, group_field) in PARTY_GROUP.items():
		allowed = build_party_allowed_sql("p", group_field, restrictions.get(party), escape, strict)
		if not allowed:
			continue
		conditions.append(
			"not exists (select 1 from `tabDynamic Link` dl"
			f" inner join `tab{party}` p on p.`name` = dl.`link_name`"
			f" where dl.`parent` = `tab{doctype}`.`name`"
			f" and dl.`parenttype` = {escape(doctype)}"
			f" and dl.`link_doctype` = {escape(party)}"
			f" and not ({allowed}))"
		)
	return " and ".join(conditions)


def restrictions_from_user_permissions(user_permissions):
	"""{"Customer": restriction, "Supplier": restriction} from a get_user_permissions() dict (before group expansion).

	Only entries applicable to the party doctype (no applicable_for, or applicable_for equal to it) count.
	Group entries are returned as (name, hide_descendants) pairs for expansion.
	"""

	def applicable(entries, party):
		values = [e for e in (entries or []) if not e.get("applicable_for") or e.get("applicable_for") == party]
		return values or None

	out = {}
	for party, (group_doctype, _field) in PARTY_GROUP.items():
		group_entries = applicable(user_permissions.get(group_doctype), party)
		name_entries = applicable(user_permissions.get(party), party)
		out[party] = {
			"groups": None
			if group_entries is None
			else [(e.get("doc"), cint(e.get("hide_descendants"))) for e in group_entries],
			"names": None if name_entries is None else sorted({e.get("doc") for e in name_entries}),
		}
	return out


# ---------------------------------------------------------------------------
# Database-backed parts
# ---------------------------------------------------------------------------


def _is_unrestricted(user):
	return user == "Administrator" or bool(set(UNRESTRICTED_ROLES) & set(frappe.get_roles(user)))


def _expand_groups(group_doctype, entries):
	"""Each group plus its descendants (lft/rgt), unless the permission hides descendants."""
	names = set()
	for name, hide_descendants in entries:
		if not name:
			continue
		names.add(name)
		if hide_descendants:
			continue
		bounds = frappe.db.get_value(group_doctype, name, ["lft", "rgt"], as_dict=True)
		if bounds and bounds.lft is not None and bounds.rgt is not None:
			names.update(
				frappe.get_all(
					group_doctype,
					filters={"lft": (">", bounds.lft), "rgt": ("<", bounds.rgt)},
					pluck="name",
				)
			)
	return sorted(names)


def _get_restrictions(user):
	raw = restrictions_from_user_permissions(frappe.permissions.get_user_permissions(user) or {})
	for party, (group_doctype, _field) in PARTY_GROUP.items():
		if raw[party]["groups"] is not None:
			raw[party]["groups"] = _expand_groups(group_doctype, raw[party]["groups"])
		if raw[party]["groups"] is None and raw[party]["names"] is None:
			raw[party] = None
	return raw


def _strict():
	return bool(cint(frappe.get_system_settings("apply_strict_user_permissions")))


def get_permission_query_conditions(user=None, doctype=None):
	user = user or frappe.session.user
	if doctype not in TARGET_DOCTYPES or _is_unrestricted(user):
		return ""
	return build_party_link_condition(doctype, _get_restrictions(user), frappe.db.escape, _strict())


def has_permission(doc, ptype=None, user=None):
	"""Controller check: False when the document links to a Customer or Supplier the user may not read, else True.

	A has_permission hook can only deny (frappe.permissions.has_controller_permissions), and never returns None here.
	"""
	user = user or frappe.session.user
	if getattr(doc, "doctype", None) not in TARGET_DOCTYPES or _is_unrestricted(user):
		return True
	links = [
		link
		for link in (doc.get("links") or [])
		if link.get("link_doctype") in PARTY_GROUP and link.get("link_name")
	]
	if not links:
		return True
	restrictions = _get_restrictions(user)
	strict = _strict()
	for link in links:
		party = link.get("link_doctype")
		restriction = restrictions.get(party)
		if not restriction:
			continue
		group_field = PARTY_GROUP[party][1]
		party_group = frappe.db.get_value(party, link.get("link_name"), group_field)
		if party_group is None and not frappe.db.exists(party, link.get("link_name")):
			continue  # mirrors the SQL join: a link to a missing party does not hide the record
		if not party_allowed(link.get("link_name"), party_group, restriction, strict):
			return False
	return True
