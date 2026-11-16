import json
import logging

from odoo import fields, http, release
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request

_logger = logging.getLogger(__name__)

SUPPORTED_PROTOCOLS = ["2025-06-18", "2025-03-26", "2024-11-05"]
MAX_LIMIT = 200
SERVER_INFO = {"name": "mna-mcp-server-odoo", "version": "1.0.0"}

# JSON-RPC error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602


class McpToolError(Exception):
    """Raised by a tool to report a failure back to the model."""


def _obj(properties, required=()):
    return {"type": "object", "properties": properties, "required": list(required)}


_MODEL = {"type": "string", "description": "Technical model name, e.g. res.partner"}

TOOLS = [
    {
        "name": "get_context",
        "description": "Return the current Odoo user, company, language, timezone and server version.",
        "inputSchema": _obj({}),
    },
    {
        "name": "list_models",
        "description": "List the Odoo models exposed to MCP and the operations allowed on each.",
        "inputSchema": _obj({}),
    },
    {
        "name": "get_fields",
        "description": "Describe the fields of an exposed model: type, label, required, relation, selection.",
        "inputSchema": _obj({"model": _MODEL}, ["model"]),
    },
    {
        "name": "search_records",
        "description": (
            "Search records of an exposed model with an Odoo domain and return the "
            "requested fields. Maximum %d records per call; use offset to paginate."
        )
        % MAX_LIMIT,
        "inputSchema": _obj(
            {
                "model": _MODEL,
                "domain": {
                    "type": "array",
                    "description": 'Odoo domain, e.g. [["is_company", "=", true]]',
                },
                "fields": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "default": 20},
                "offset": {"type": "integer", "default": 0},
                "order": {"type": "string", "description": "e.g. create_date desc"},
            },
            ["model"],
        ),
    },
    {
        "name": "count_records",
        "description": "Count the records of an exposed model matching an Odoo domain.",
        "inputSchema": _obj({"model": _MODEL, "domain": {"type": "array"}}, ["model"]),
    },
    {
        "name": "read_records",
        "description": "Read specific records of an exposed model by id.",
        "inputSchema": _obj(
            {
                "model": _MODEL,
                "ids": {"type": "array", "items": {"type": "integer"}},
                "fields": {"type": "array", "items": {"type": "string"}},
            },
            ["model", "ids"],
        ),
    },
    {
        "name": "create_record",
        "description": "Create one record on an exposed model. Only works if creation is allowed for that model.",
        "inputSchema": _obj(
            {"model": _MODEL, "values": {"type": "object"}}, ["model", "values"]
        ),
    },
    {
        "name": "update_record",
        "description": "Update one record on an exposed model. Only works if update is allowed for that model.",
        "inputSchema": _obj(
            {"model": _MODEL, "id": {"type": "integer"}, "values": {"type": "object"}},
            ["model", "id", "values"],
        ),
    },
]
TOOL_NAMES = {tool["name"] for tool in TOOLS}


class McpController(http.Controller):
    # ------------------------------------------------------------------
    # HTTP layer
    # ------------------------------------------------------------------
    def _json(self, payload, status=200, headers=None):
        body = json.dumps(payload, default=str)
        all_headers = [("Content-Type", "application/json"), ("Cache-Control", "no-store")]
        all_headers += headers or []
        return request.make_response(body, headers=all_headers, status=status)

    def _rpc_error(self, rpc_id, code, message, status=200):
        return self._json(
            {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}},
            status=status,
        )

    def _unauthorized(self, message):
        return self._json(
            {"error": "unauthorized", "message": message},
            status=401,
            headers=[("WWW-Authenticate", 'Bearer realm="Odoo MCP"')],
        )

    @http.route("/mcp", type="http", auth="none", methods=["GET", "DELETE"], csrf=False)
    def mcp_no_stream(self, **kwargs):
        # Stateless server: no SSE stream and no sessions to delete.
        return request.make_response("", headers=[("Allow", "POST")], status=405)

    # readonly=False: Odoo serves auth="none" routes on a read-only cursor by
    # default, which would break create/update tools and the audit log.
    @http.route(
        "/mcp",
        type="http",
        auth="none",
        methods=["POST"],
        csrf=False,
        save_session=False,
        readonly=False,
    )
    def mcp(self, **kwargs):
        if not request.db:
            return self._json({"error": "no_database"}, status=404)

        params = request.env["ir.config_parameter"].sudo()
        if params.get_param("mna_mcp.enabled", "True") != "True":
            return self._json({"error": "disabled"}, status=404)

        auth = request.httprequest.headers.get("Authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        key = request.env["mna.mcp.key"]._authenticate(token)
        if not key:
            return self._unauthorized("Missing, invalid or expired MCP key.")

        try:
            message = json.loads(request.httprequest.get_data(as_text=True) or "")
        except ValueError:
            return self._rpc_error(None, PARSE_ERROR, "Parse error", status=400)
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return self._rpc_error(None, INVALID_REQUEST, "Invalid request", status=400)

        request.update_env(user=key.user_id.id)
        key.sudo().last_used = fields.Datetime.now()

        method = message.get("method")
        rpc_id = message.get("id")
        if "id" not in message:
            # Notification (e.g. notifications/initialized) or client response.
            return request.make_response("", status=202)

        handler = {
            "initialize": self._initialize,
            "ping": lambda p: {},
            "tools/list": lambda p: {"tools": TOOLS},
            "tools/call": lambda p: self._tools_call(p, key),
        }.get(method)
        if not handler:
            return self._rpc_error(rpc_id, METHOD_NOT_FOUND, "Method not found: %s" % method)
        try:
            result = handler(message.get("params") or {})
        except McpToolError as exc:
            return self._rpc_error(rpc_id, INVALID_PARAMS, str(exc))
        return self._json({"jsonrpc": "2.0", "id": rpc_id, "result": result})

    # ------------------------------------------------------------------
    # MCP methods
    # ------------------------------------------------------------------
    def _initialize(self, params):
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": (
                "This server exposes an Odoo database. Call list_models first to see "
                "which models you may use, then get_fields before searching or writing."
            ),
        }

    def _tools_call(self, params, key):
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name not in TOOL_NAMES:
            raise McpToolError("Unknown tool: %s" % name)
        if not isinstance(arguments, dict):
            raise McpToolError("Tool arguments must be an object.")

        error = False
        data = None
        try:
            # Savepoint: a failed tool call must not poison the transaction,
            # so the audit log below is always written.
            with request.env.cr.savepoint():
                data = getattr(self, "_tool_" + name)(arguments)
        except (McpToolError, AccessError, UserError, ValidationError) as exc:
            error = str(exc) or exc.__class__.__name__
        except Exception as exc:  # noqa: BLE001 - reported to the client, logged here
            _logger.exception("MCP tool %s failed", name)
            error = "%s: %s" % (exc.__class__.__name__, exc)

        request.env["mna.mcp.log"].sudo().create(
            {
                "user_id": request.env.uid,
                "key_id": key.id,
                "tool": name,
                "model": arguments.get("model") if isinstance(arguments.get("model"), str) else False,
                "arguments": json.dumps(arguments, default=str)[:4000],
                "success": not error,
                "error": error or False,
            }
        )
        text = error if error else json.dumps(data, default=str, ensure_ascii=False)
        return {"content": [{"type": "text", "text": text}], "isError": bool(error)}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _model(self, arguments, operation):
        """Return the env model if the allowlist permits `operation` on it."""
        model_name = arguments.get("model")
        if not isinstance(model_name, str):
            raise McpToolError("'model' is required.")
        rule = request.env["mna.mcp.model"]._get_rule(model_name)
        if not rule or model_name not in request.env:
            raise McpToolError(
                "Model '%s' is not exposed to MCP. Call list_models to see what is available."
                % model_name
            )
        if not rule["allow_" + operation]:
            raise McpToolError(
                "Operation '%s' is not allowed on model '%s'." % (operation, model_name)
            )
        return request.env[model_name]

    def _domain(self, arguments):
        domain = arguments.get("domain") or []
        if not isinstance(domain, list):
            raise McpToolError("'domain' must be a list.")
        return domain

    def _field_names(self, model, arguments):
        names = arguments.get("fields")
        if not names:
            return ["id", "display_name"]
        if not isinstance(names, list):
            raise McpToolError("'fields' must be a list of field names.")
        unknown = [name for name in names if name not in model._fields]
        if unknown:
            raise McpToolError(
                "Unknown field(s) on %s: %s" % (model._name, ", ".join(map(str, unknown)))
            )
        return names

    def _values(self, model, arguments):
        values = arguments.get("values")
        if not isinstance(values, dict) or not values:
            raise McpToolError("'values' must be a non-empty object.")
        unknown = [name for name in values if name not in model._fields]
        if unknown:
            raise McpToolError(
                "Unknown field(s) on %s: %s" % (model._name, ", ".join(unknown))
            )
        return values

    # ------------------------------------------------------------------
    # Tools (all run as the key's user: ACLs and record rules apply)
    # ------------------------------------------------------------------
    def _tool_get_context(self, arguments):
        user = request.env.user
        return {
            "user": {"id": user.id, "name": user.name, "login": user.login},
            "company": {"id": user.company_id.id, "name": user.company_id.name},
            "allowed_companies": [{"id": c.id, "name": c.name} for c in user.company_ids],
            "lang": user.lang,
            "tz": user.tz,
            "today": fields.Date.context_today(user),
            "server_version": release.version,
        }

    def _tool_list_models(self, arguments):
        rules = request.env["mna.mcp.model"].sudo().search([])
        return [
            {
                "model": rule.model,
                "name": rule.name,
                "read": rule.allow_read,
                "create": rule.allow_create,
                "update": rule.allow_write,
            }
            for rule in rules
            if rule.model in request.env
            and request.env[rule.model].has_access("read")
        ]

    def _tool_get_fields(self, arguments):
        model = self._model(arguments, "read")
        attributes = ["string", "type", "required", "readonly", "relation", "selection", "help"]
        return model.fields_get(attributes=attributes)

    def _tool_search_records(self, arguments):
        model = self._model(arguments, "read")
        limit = arguments.get("limit", 20)
        offset = arguments.get("offset", 0)
        if not isinstance(limit, int) or not isinstance(offset, int) or limit < 1 or offset < 0:
            raise McpToolError("'limit' and 'offset' must be positive integers.")
        domain = self._domain(arguments)
        records = model.search_read(
            domain,
            self._field_names(model, arguments),
            offset=offset,
            limit=min(limit, MAX_LIMIT),
            order=arguments.get("order") or None,
        )
        return {"count": len(records), "total": model.search_count(domain), "records": records}

    def _tool_count_records(self, arguments):
        model = self._model(arguments, "read")
        return {"count": model.search_count(self._domain(arguments))}

    def _tool_read_records(self, arguments):
        model = self._model(arguments, "read")
        ids = arguments.get("ids")
        if not isinstance(ids, list) or not all(isinstance(i, int) for i in ids):
            raise McpToolError("'ids' must be a list of integers.")
        records = model.browse(ids[:MAX_LIMIT]).exists()
        return records.read(self._field_names(model, arguments))

    def _tool_create_record(self, arguments):
        model = self._model(arguments, "create")
        record = model.create(self._values(model, arguments))
        return {"id": record.id, "display_name": record.display_name}

    def _tool_update_record(self, arguments):
        model = self._model(arguments, "write")
        record_id = arguments.get("id")
        if not isinstance(record_id, int):
            raise McpToolError("'id' must be an integer.")
        record = model.browse(record_id).exists()
        if not record:
            raise McpToolError("Record %s(%s) does not exist." % (model._name, record_id))
        record.write(self._values(model, arguments))
        return {"id": record.id, "display_name": record.display_name}
