from odoo import api, fields, models, tools


class MnaPosInsight(models.Model):
    """One row per POS order line, with the figures Odoo's own report omits.

    Odoo ships report.pos.order, which is useful and does not carry cost,
    margin, or anything that answers "when are we busy". This view adds
    those without duplicating what is already there.

    Hour of day is computed per row against the timezone of the order's
    company, not in UTC. A shop in Beirut that is busiest at 7pm shows a
    peak at 17:00 in a UTC report, and a peak hour that is two hours wrong
    is worse than no peak hour at all, because someone will roster staff
    against it.
    """

    _name = "mna.pos.insight"
    _description = "POS Sales Insight"
    _auto = False
    _order = "date desc"
    _rec_name = "product_id"

    date = fields.Datetime(string="Order Date", readonly=True)
    hour_of_day = fields.Integer(
        readonly=True, aggregator="avg",
        help="Hour of the day in the company's own timezone, 0 to 23. Group by "
             "this to see when the shop is busy, whatever the date.",
    )
    day_of_week = fields.Selection(
        [("0", "Sunday"), ("1", "Monday"), ("2", "Tuesday"), ("3", "Wednesday"),
         ("4", "Thursday"), ("5", "Friday"), ("6", "Saturday")],
        readonly=True,
    )
    order_id = fields.Many2one("pos.order", string="Order", readonly=True)
    session_id = fields.Many2one("pos.session", string="Session", readonly=True)
    config_id = fields.Many2one("pos.config", string="Point of Sale", readonly=True)
    user_id = fields.Many2one("res.users", string="Cashier", readonly=True)
    partner_id = fields.Many2one("res.partner", string="Customer", readonly=True)
    product_id = fields.Many2one("product.product", string="Product", readonly=True)
    categ_id = fields.Many2one("product.category", string="Product Category", readonly=True)
    company_id = fields.Many2one("res.company", string="Company", readonly=True)
    currency_id = fields.Many2one("res.currency", string="Currency", readonly=True)

    qty = fields.Float(string="Quantity", readonly=True)
    revenue = fields.Monetary(
        string="Revenue", readonly=True, currency_field="currency_id",
        help="Net of tax and after discount, which is what actually arrived.",
    )
    cost = fields.Monetary(string="Cost", readonly=True, currency_field="currency_id")
    margin = fields.Monetary(string="Margin", readonly=True, currency_field="currency_id")
    margin_percent = fields.Float(
        string="Margin %", readonly=True, aggregator="avg",
        help="Margin over revenue for this line. Averaged when grouped, so read "
             "the margin column for the money and this one for the rate.",
    )
    discount_amount = fields.Monetary(
        string="Discount Given", readonly=True, currency_field="currency_id",
        help="What the discount cost you, in money rather than in percent.",
    )
    discount_percent = fields.Float(string="Discount %", readonly=True, aggregator="avg")
    has_cost = fields.Boolean(
        readonly=True,
        help="False when the line never had a cost recorded, in which case its "
             "margin is the full revenue and would flatter any total that "
             "included it.",
    )

    def _query(self):
        return """
            SELECT
                l.id AS id,
                o.date_order AS date,
                EXTRACT(HOUR FROM (o.date_order AT TIME ZONE 'UTC'
                        AT TIME ZONE COALESCE(NULLIF(pt.tz, ''), 'UTC')))::int AS hour_of_day,
                EXTRACT(DOW FROM (o.date_order AT TIME ZONE 'UTC'
                        AT TIME ZONE COALESCE(NULLIF(pt.tz, ''), 'UTC')))::text AS day_of_week,
                o.id AS order_id,
                o.session_id AS session_id,
                s.config_id AS config_id,
                o.user_id AS user_id,
                o.partner_id AS partner_id,
                l.product_id AS product_id,
                pt2.categ_id AS categ_id,
                o.company_id AS company_id,
                c.currency_id AS currency_id,
                l.qty AS qty,
                l.price_subtotal AS revenue,
                COALESCE(l.total_cost, 0.0) AS cost,
                l.price_subtotal - COALESCE(l.total_cost, 0.0) AS margin,
                CASE WHEN l.price_subtotal <> 0
                     THEN (l.price_subtotal - COALESCE(l.total_cost, 0.0))
                          / l.price_subtotal * 100.0
                     ELSE 0.0 END AS margin_percent,
                (l.price_unit * l.qty) * (COALESCE(l.discount, 0.0) / 100.0) AS discount_amount,
                COALESCE(l.discount, 0.0) AS discount_percent,
                (l.total_cost IS NOT NULL AND l.total_cost <> 0) AS has_cost
            FROM pos_order_line l
            JOIN pos_order o ON o.id = l.order_id
            JOIN pos_session s ON s.id = o.session_id
            JOIN res_company c ON c.id = o.company_id
            LEFT JOIN res_partner pt ON pt.id = c.partner_id
            LEFT JOIN product_product pp ON pp.id = l.product_id
            LEFT JOIN product_template pt2 ON pt2.id = pp.product_tmpl_id
            WHERE o.state IN ('paid', 'done', 'invoiced')
        """

    def init(self):
        # An explicit view, created the same way on 18 and 19, so one
        # source serves both branches.
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute(
            "CREATE OR REPLACE VIEW %s AS (%s)" % (self._table, self._query())
        )

    @api.model
    def action_open_peak_hours(self):
        return {
            "type": "ir.actions.act_window",
            "name": "When are we busy?",
            "res_model": "mna.pos.insight",
            "view_mode": "pivot,list",
            "context": {
                "pivot_row_groupby": ["hour_of_day"],
                "pivot_measures": ["revenue", "qty"],
            },
        }
