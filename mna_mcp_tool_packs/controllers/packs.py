"""Business tool packs for the Odoo MCP server.

The core server gives a model generic CRUD: search, read, create, update.
That is enough to answer "find invoice INV/2026/0042" and badly suited to
"what did we sell last month by salesperson", which with CRUD alone means
paging through hundreds of records and adding them up in the model's head.
Models are poor at arithmetic over long lists and will confidently return a
total that is wrong by one page.

So these tools aggregate in Postgres and hand back a short, exact answer.
They are read only, they run as the key's own user, and every one of them
goes through the same allowlist as the core tools: a pack tool over
account.move stays unavailable until account.move is exposed for reading.
"""
import logging
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from odoo.http import request

from odoo.addons.mna_mcp_server.controllers.main import (
    McpController,
    McpToolError,
    register_tool,
)

_logger = logging.getLogger(__name__)

MAX_GROUPS = 100

PERIODS = [
    "today",
    "yesterday",
    "last_7_days",
    "last_30_days",
    "this_month",
    "last_month",
    "this_quarter",
    "last_quarter",
    "this_year",
    "last_year",
]

_PERIOD = {
    "type": "string",
    "enum": PERIODS,
    "description": "Named period. Ignored when date_from or date_to is given.",
}
_DATE = {"type": "string", "description": "Date as YYYY-MM-DD."}
_LIMIT = {
    "type": "integer",
    "description": "Maximum number of groups to return, at most %d." % MAX_GROUPS,
}


def _obj(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required)}


def _needs(*models):
    """Hide a tool unless every model it reports on exists in the registry."""

    def available(env):
        return all(name in env for name in models)

    return available


# ----------------------------------------------------------------------
# Tool declarations
# ----------------------------------------------------------------------
register_tool(
    {
        "name": "sales_summary",
        "description": (
            "Total confirmed sales for a period, optionally grouped by salesperson, "
            "customer, product, team or month. Returns exact totals computed in the "
            "database, not a sample of orders."
        ),
        "inputSchema": _obj(
            {
                "period": _PERIOD,
                "date_from": _DATE,
                "date_to": _DATE,
                "group_by": {
                    "type": "string",
                    "enum": ["none", "salesperson", "customer", "product", "team", "month"],
                    "description": "Defaults to none, which returns a single total.",
                },
                "limit": _LIMIT,
            }
        ),
    },
    available=_needs("sale.order"),
)

register_tool(
    {
        "name": "sales_pipeline",
        "description": (
            "Open quotations and sales orders that are not yet fully invoiced, "
            "with their amount and age in days. Answers 'what is still in the pipeline'."
        ),
        "inputSchema": _obj({"limit": _LIMIT}),
    },
    available=_needs("sale.order"),
)

register_tool(
    {
        "name": "aged_receivable",
        "description": (
            "Customer balances due, split into the usual aging buckets "
            "(not due, 1-30, 31-60, 61-90, over 90 days). Amounts are in company currency."
        ),
        "inputSchema": _obj(
            {
                "partner_id": {
                    "type": "integer",
                    "description": "Restrict to one customer. Omit for all customers.",
                },
                "limit": _LIMIT,
            }
        ),
    },
    available=_needs("account.move.line"),
)

register_tool(
    {
        "name": "unpaid_invoices",
        "description": (
            "Posted customer invoices that are not fully paid, oldest first, with "
            "amount due and days overdue."
        ),
        "inputSchema": _obj(
            {
                "partner_id": {"type": "integer", "description": "Restrict to one customer."},
                "overdue_only": {
                    "type": "boolean",
                    "description": "Only invoices past their due date. Defaults to false.",
                },
                "limit": _LIMIT,
            }
        ),
    },
    available=_needs("account.move"),
)

register_tool(
    {
        "name": "revenue_by_period",
        "description": (
            "Posted customer invoice totals per month or per quarter for a period, "
            "net of credit notes. Use this for revenue trends instead of reading invoices."
        ),
        "inputSchema": _obj(
            {
                "period": _PERIOD,
                "date_from": _DATE,
                "date_to": _DATE,
                "granularity": {"type": "string", "enum": ["month", "quarter", "year"]},
            }
        ),
    },
    available=_needs("account.move"),
)

register_tool(
    {
        "name": "stock_on_hand",
        "description": (
            "Quantity on hand per product, optionally for one product or one "
            "internal location. Sums quants in the database rather than reading them one by one."
        ),
        "inputSchema": _obj(
            {
                "product_id": {"type": "integer", "description": "Restrict to one product."},
                "location_id": {
                    "type": "integer",
                    "description": "Restrict to one location and the locations under it.",
                },
                "limit": _LIMIT,
            }
        ),
    },
    available=_needs("stock.quant"),
)

register_tool(
    {
        "name": "low_stock",
        "description": (
            "Storable products at or below their reorder minimum, or with no stock at "
            "all, with the quantity on hand and the quantity already incoming."
        ),
        "inputSchema": _obj({"limit": _LIMIT}),
    },
    available=_needs("stock.quant"),
)

register_tool(
    {
        "name": "purchase_summary",
        "description": (
            "Total confirmed purchases for a period, optionally grouped by vendor, "
            "product, buyer or month."
        ),
        "inputSchema": _obj(
            {
                "period": _PERIOD,
                "date_from": _DATE,
                "date_to": _DATE,
                "group_by": {
                    "type": "string",
                    "enum": ["none", "vendor", "product", "buyer", "month"],
                },
                "limit": _LIMIT,
            }
        ),
    },
    available=_needs("purchase.order"),
)


class McpPacksController(McpController):
    """Extends the MCP controller with the pack tools.

    Same class, so the core dispatch finds ``_tool_<name>`` here without
    knowing this module exists.
    """

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _limit(self, arguments):
        value = arguments.get("limit") or 20
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise McpToolError("'limit' must be a positive integer.")
        return min(value, MAX_GROUPS)

    def _parse_date(self, value, label):
        if not isinstance(value, str):
            raise McpToolError("'%s' must be a date string, YYYY-MM-DD." % label)
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            raise McpToolError("'%s' is not a valid date: %s" % (label, value)) from None

    def _range(self, arguments, default="this_month"):
        """Resolve the period arguments to an inclusive (date_from, date_to)."""
        raw_from, raw_to = arguments.get("date_from"), arguments.get("date_to")
        if raw_from or raw_to:
            today = date.today()
            start = self._parse_date(raw_from, "date_from") if raw_from else date(2000, 1, 1)
            end = self._parse_date(raw_to, "date_to") if raw_to else today
            if start > end:
                raise McpToolError("'date_from' is after 'date_to'.")
            return start, end

        period = arguments.get("period") or default
        if period not in PERIODS:
            raise McpToolError(
                "Unknown period '%s'. Use one of: %s" % (period, ", ".join(PERIODS))
            )
        today = date.today()
        if period == "today":
            return today, today
        if period == "yesterday":
            day = today - timedelta(days=1)
            return day, day
        if period == "last_7_days":
            return today - timedelta(days=6), today
        if period == "last_30_days":
            return today - timedelta(days=29), today
        if period == "this_month":
            return today.replace(day=1), today
        if period == "last_month":
            first = today.replace(day=1)
            return first - relativedelta(months=1), first - timedelta(days=1)
        if period == "this_quarter":
            start = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
            return start, today
        if period == "last_quarter":
            start = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
            previous = start - relativedelta(months=3)
            return previous, start - timedelta(days=1)
        if period == "this_year":
            return date(today.year, 1, 1), today
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)

    def _allowed(self, model_name):
        """Reuse the core allowlist, so packs never widen what is reachable."""
        return self._model({"model": model_name}, "read")

    def _currency(self):
        return request.env.company.currency_id.name

    def _named(self, value):
        """``_read_group`` returns a recordset for a many2one group key."""
        if not value:
            return {"id": False, "name": "Not set"}
        return {"id": value.id, "name": value.display_name}

    def _money(self, amount):
        return round(amount or 0.0, 2)

    # ------------------------------------------------------------------
    # Sales
    # ------------------------------------------------------------------
    def _tool_sales_summary(self, arguments):
        order = self._allowed("sale.order")
        start, end = self._range(arguments)
        limit = self._limit(arguments)
        group_by = arguments.get("group_by") or "none"

        domain = [
            ("state", "in", ["sale", "done"]),
            ("date_order", ">=", str(start)),
            ("date_order", "<=", str(end) + " 23:59:59"),
        ]

        if group_by == "product":
            line = self._allowed("sale.order.line")
            rows = line._read_group(
                [("order_id", "in", order._search(domain))],
                groupby=["product_id"],
                aggregates=["price_subtotal:sum", "product_uom_qty:sum"],
                order="price_subtotal:sum desc",
                limit=limit,
            )
            groups = [
                {
                    "product": self._named(product),
                    "quantity": round(qty or 0.0, 2),
                    "revenue": self._money(subtotal),
                }
                for product, subtotal, qty in rows
            ]
        else:
            field = {
                "none": None,
                "salesperson": "user_id",
                "customer": "partner_id",
                "team": "team_id",
                "month": "date_order:month",
            }.get(group_by)
            if group_by != "none" and not field:
                raise McpToolError("Unknown group_by: %s" % group_by)
            rows = order._read_group(
                domain,
                groupby=[field] if field else [],
                aggregates=["amount_total:sum", "__count"],
                order=("amount_total:sum desc" if field and group_by != "month" else None),
                limit=limit if field else None,
            )
            groups = []
            for row in rows:
                if field:
                    key, total, count = row
                    label = (
                        {"period": key[0].strftime("%Y-%m") if key else "Not set"}
                        if group_by == "month"
                        else {group_by: self._named(key)}
                    )
                else:
                    label, (total, count) = {}, row
                groups.append(dict(label, revenue=self._money(total), orders=count))

        # Grouping by product sums order lines, which excludes tax and so does
        # not reconcile with the order totals above. Reporting a "total" there
        # would invite exactly the wrong comparison, so it is left out.
        total = None
        if group_by != "product":
            total = self._money(sum(group["revenue"] for group in groups))

        return {
            "date_from": str(start),
            "date_to": str(end),
            "currency": self._currency(),
            "group_by": group_by,
            "total": total,
            "groups": groups,
        }

    def _tool_sales_pipeline(self, arguments):
        order = self._allowed("sale.order")
        limit = self._limit(arguments)
        today = date.today()

        rows = order.search_read(
            [("state", "in", ["draft", "sent", "sale"])],
            ["name", "partner_id", "amount_total", "state", "date_order"],
            limit=limit,
            order="amount_total desc",
        )
        out = []
        for row in rows:
            ordered = row["date_order"]
            out.append(
                {
                    "order": row["name"],
                    "customer": row["partner_id"][1] if row["partner_id"] else None,
                    "state": row["state"],
                    "amount": self._money(row["amount_total"]),
                    "age_days": (today - ordered.date()).days if ordered else None,
                }
            )
        return {"currency": self._currency(), "count": len(out), "orders": out}

    # ------------------------------------------------------------------
    # Accounting
    # ------------------------------------------------------------------
    def _tool_aged_receivable(self, arguments):
        line = self._allowed("account.move.line")
        limit = self._limit(arguments)
        today = date.today()

        domain = [
            ("parent_state", "=", "posted"),
            ("account_id.account_type", "=", "asset_receivable"),
            ("full_reconcile_id", "=", False),
            ("balance", "!=", 0),
        ]
        partner_id = arguments.get("partner_id")
        if partner_id:
            domain.append(("partner_id", "=", partner_id))

        # amount_residual carries the open part, which is the whole point of
        # an aging report: a half paid invoice must show the half.
        rows = line.search_read(
            domain, ["partner_id", "amount_residual", "date_maturity", "date"], limit=20000
        )

        buckets = ["not_due", "1_30", "31_60", "61_90", "over_90"]
        per_partner = {}
        for row in rows:
            residual = row["amount_residual"] or 0.0
            if not residual:
                continue
            partner = row["partner_id"]
            key = partner[0] if partner else 0
            entry = per_partner.setdefault(
                key,
                dict(
                    {b: 0.0 for b in buckets},
                    partner=partner[1] if partner else "Not set",
                    partner_id=key,
                    total=0.0,
                ),
            )
            due = row["date_maturity"] or row["date"]
            overdue = (today - due).days if due else 0
            if overdue <= 0:
                bucket = "not_due"
            elif overdue <= 30:
                bucket = "1_30"
            elif overdue <= 60:
                bucket = "31_60"
            elif overdue <= 90:
                bucket = "61_90"
            else:
                bucket = "over_90"
            entry[bucket] += residual
            entry["total"] += residual

        ordered = sorted(per_partner.values(), key=lambda e: -e["total"])[:limit]
        for entry in ordered:
            for field in buckets + ["total"]:
                entry[field] = self._money(entry[field])

        return {
            "as_of": str(today),
            "currency": self._currency(),
            "total": self._money(sum(e["total"] for e in per_partner.values())),
            "partners": ordered,
        }

    def _tool_unpaid_invoices(self, arguments):
        move = self._allowed("account.move")
        limit = self._limit(arguments)
        today = date.today()

        domain = [
            ("move_type", "in", ["out_invoice", "out_refund"]),
            ("state", "=", "posted"),
            ("payment_state", "in", ["not_paid", "partial"]),
        ]
        if arguments.get("partner_id"):
            domain.append(("partner_id", "=", arguments["partner_id"]))
        if arguments.get("overdue_only"):
            domain.append(("invoice_date_due", "<", str(today)))

        rows = move.search_read(
            domain,
            [
                "name",
                "partner_id",
                "invoice_date",
                "invoice_date_due",
                "amount_total",
                "amount_residual",
                "payment_state",
            ],
            limit=limit,
            order="invoice_date_due asc, id asc",
        )
        invoices = []
        for row in rows:
            due = row["invoice_date_due"]
            invoices.append(
                {
                    "invoice": row["name"],
                    "customer": row["partner_id"][1] if row["partner_id"] else None,
                    "invoice_date": str(row["invoice_date"]) if row["invoice_date"] else None,
                    "due_date": str(due) if due else None,
                    "days_overdue": max(0, (today - due).days) if due else 0,
                    "amount_total": self._money(row["amount_total"]),
                    "amount_due": self._money(row["amount_residual"]),
                    "payment_state": row["payment_state"],
                }
            )
        return {
            "currency": self._currency(),
            "count": len(invoices),
            "total_due": self._money(sum(i["amount_due"] for i in invoices)),
            "invoices": invoices,
        }

    def _tool_revenue_by_period(self, arguments):
        move = self._allowed("account.move")
        start, end = self._range(arguments, default="this_year")
        granularity = arguments.get("granularity") or "month"
        if granularity not in ("month", "quarter", "year"):
            raise McpToolError("Unknown granularity: %s" % granularity)

        rows = move._read_group(
            [
                ("move_type", "in", ["out_invoice", "out_refund"]),
                ("state", "=", "posted"),
                ("invoice_date", ">=", str(start)),
                ("invoice_date", "<=", str(end)),
            ],
            groupby=["invoice_date:" + granularity, "move_type"],
            aggregates=["amount_total_signed:sum", "__count"],
            order="invoice_date:" + granularity + " asc",
        )

        periods = {}
        for key, move_type, total, count in rows:
            label = str(key) if key else "Not set"
            if key and granularity == "month":
                label = key.strftime("%Y-%m")
            elif key and granularity == "year":
                label = key.strftime("%Y")
            elif key:
                label = "%d-Q%d" % (key.year, (key.month - 1) // 3 + 1)
            entry = periods.setdefault(
                label, {"period": label, "invoiced": 0.0, "credited": 0.0, "net": 0.0, "count": 0}
            )
            # amount_total_signed is negative on a credit note, so the net is
            # simply the sum and the split is for the reader's benefit.
            if move_type == "out_refund":
                entry["credited"] += total or 0.0
            else:
                entry["invoiced"] += total or 0.0
            entry["net"] += total or 0.0
            entry["count"] += count

        out = [
            {k: (self._money(v) if isinstance(v, float) else v) for k, v in entry.items()}
            for entry in periods.values()
        ]
        return {
            "date_from": str(start),
            "date_to": str(end),
            "currency": self._currency(),
            "granularity": granularity,
            "net_total": self._money(sum(e["net"] for e in out)),
            "periods": out,
        }

    # ------------------------------------------------------------------
    # Inventory
    # ------------------------------------------------------------------
    def _tool_stock_on_hand(self, arguments):
        quant = self._allowed("stock.quant")
        limit = self._limit(arguments)

        domain = [("location_id.usage", "=", "internal")]
        if arguments.get("product_id"):
            domain.append(("product_id", "=", arguments["product_id"]))
        if arguments.get("location_id"):
            domain = [d for d in domain if d[0] != "location_id.usage"]
            domain.append(("location_id", "child_of", arguments["location_id"]))

        rows = quant._read_group(
            domain,
            groupby=["product_id"],
            aggregates=["quantity:sum", "reserved_quantity:sum"],
            order="quantity:sum desc",
            limit=limit,
        )
        products = [
            {
                "product": self._named(product),
                "on_hand": round(quantity or 0.0, 3),
                "reserved": round(reserved or 0.0, 3),
                "available": round((quantity or 0.0) - (reserved or 0.0), 3),
            }
            for product, quantity, reserved in rows
        ]
        return {"count": len(products), "products": products}

    def _tool_low_stock(self, arguments):
        quant = self._allowed("stock.quant")
        limit = self._limit(arguments)
        env = request.env

        on_hand = dict(
            (product.id, quantity or 0.0)
            for product, quantity in quant._read_group(
                [("location_id.usage", "=", "internal")],
                groupby=["product_id"],
                aggregates=["quantity:sum"],
            )
        )

        # A reorder rule is the only place Odoo records a deliberate minimum,
        # so products without one are only reported when they are at zero and
        # have actually moved before. Listing every never stocked product
        # would bury the real shortages.
        rules = {}
        if "stock.warehouse.orderpoint" in env:
            for rule in env["stock.warehouse.orderpoint"].search_read(
                [], ["product_id", "product_min_qty"]
            ):
                product_id = rule["product_id"][0]
                rules[product_id] = max(rules.get(product_id, 0.0), rule["product_min_qty"] or 0.0)

        candidates = set(rules) | {pid for pid, qty in on_hand.items() if qty <= 0}
        if not candidates:
            return {"count": 0, "products": []}

        products = env["product.product"].browse(sorted(candidates)).exists()
        products = products.filtered(lambda p: p.type in ("product", "consu"))

        incoming = {}
        if "stock.move" in env:
            for product, qty in env["stock.move"]._read_group(
                [
                    ("product_id", "in", products.ids),
                    ("state", "in", ["waiting", "confirmed", "assigned", "partially_available"]),
                    ("location_dest_id.usage", "=", "internal"),
                ],
                groupby=["product_id"],
                aggregates=["product_uom_qty:sum"],
            ):
                incoming[product.id] = qty or 0.0

        out = []
        for product in products:
            quantity = on_hand.get(product.id, 0.0)
            minimum = rules.get(product.id, 0.0)
            if quantity > minimum and not (quantity <= 0 and product.id in rules):
                if quantity > 0:
                    continue
            out.append(
                {
                    "product": {"id": product.id, "name": product.display_name},
                    "on_hand": round(quantity, 3),
                    "reorder_min": round(minimum, 3),
                    "incoming": round(incoming.get(product.id, 0.0), 3),
                    "shortfall": round(max(0.0, minimum - quantity), 3),
                }
            )
        out.sort(key=lambda row: (-row["shortfall"], row["on_hand"]))
        return {"count": len(out[:limit]), "products": out[:limit]}

    # ------------------------------------------------------------------
    # Purchase
    # ------------------------------------------------------------------
    def _tool_purchase_summary(self, arguments):
        order = self._allowed("purchase.order")
        start, end = self._range(arguments)
        limit = self._limit(arguments)
        group_by = arguments.get("group_by") or "none"

        domain = [
            ("state", "in", ["purchase", "done"]),
            ("date_order", ">=", str(start)),
            ("date_order", "<=", str(end) + " 23:59:59"),
        ]

        if group_by == "product":
            line = self._allowed("purchase.order.line")
            rows = line._read_group(
                [("order_id", "in", order._search(domain))],
                groupby=["product_id"],
                aggregates=["price_subtotal:sum", "product_qty:sum"],
                order="price_subtotal:sum desc",
                limit=limit,
            )
            groups = [
                {
                    "product": self._named(product),
                    "quantity": round(qty or 0.0, 2),
                    "spend": self._money(subtotal),
                }
                for product, subtotal, qty in rows
            ]
            total = None
        else:
            field = {
                "none": None,
                "vendor": "partner_id",
                "buyer": "user_id",
                "month": "date_order:month",
            }.get(group_by)
            if group_by != "none" and not field:
                raise McpToolError("Unknown group_by: %s" % group_by)
            rows = order._read_group(
                domain,
                groupby=[field] if field else [],
                aggregates=["amount_total:sum", "__count"],
                order=("amount_total:sum desc" if field and group_by != "month" else None),
                limit=limit if field else None,
            )
            groups = []
            for row in rows:
                if field:
                    key, amount, count = row
                    label = (
                        {"period": key[0].strftime("%Y-%m") if key else "Not set"}
                        if group_by == "month"
                        else {group_by: self._named(key)}
                    )
                else:
                    label, (amount, count) = {}, row
                groups.append(dict(label, spend=self._money(amount), orders=count))
            total = self._money(sum(g["spend"] for g in groups))

        return {
            "date_from": str(start),
            "date_to": str(end),
            "currency": self._currency(),
            "group_by": group_by,
            "total": total,
            "groups": groups,
        }
