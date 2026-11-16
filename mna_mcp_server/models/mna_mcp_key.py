import hashlib
import secrets

from odoo import api, fields, models

KEY_PREFIX = "mna_"


def _hash(key):
    return hashlib.sha256(key.encode()).hexdigest()


class MnaMcpKey(models.Model):
    _name = "mna.mcp.key"
    _description = "MCP API Key"
    _order = "create_date desc"

    name = fields.Char(string="Description", required=True)
    user_id = fields.Many2one(
        "res.users",
        string="Runs As",
        required=True,
        ondelete="cascade",
        help="Every MCP call made with this key runs with this user's access rights.",
    )
    key_hash = fields.Char(readonly=True, copy=False, groups="base.group_system")
    key_hint = fields.Char(string="Key", readonly=True, copy=False)
    expiration_date = fields.Datetime()
    last_used = fields.Datetime(readonly=True)
    active = fields.Boolean(default=True)

    @api.model
    def _generate(self, name, user, expiration_date=False):
        """Create a key record and return (record, clear_key).

        The clear key is returned once and never stored.
        """
        key = KEY_PREFIX + secrets.token_hex(24)
        record = self.sudo().create(
            {
                "name": name,
                "user_id": user.id,
                "expiration_date": expiration_date,
                "key_hash": _hash(key),
                "key_hint": "%s...%s" % (key[:8], key[-4:]),
            }
        )
        return record, key

    @api.model
    def _authenticate(self, key):
        """Return the active key record matching a clear key, or empty."""
        if not key or not key.startswith(KEY_PREFIX):
            return self.browse()
        record = self.sudo().search([("key_hash", "=", _hash(key))], limit=1)
        if not record or not record.user_id.active:
            return self.browse()
        if record.expiration_date and record.expiration_date < fields.Datetime.now():
            return self.browse()
        return record
