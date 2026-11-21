#!/usr/bin/env python3
"""Brand identity for the Najjarine Tech Odoo modules (apps).

Two identities on purpose, and they must not be mixed:

  APPS   (modules)  deep plum ground, Odoo purple accent, teal pill.
                    This file. Every module on the store uses it.

  THEMES (website)  jade, brass and warm sand, which lives with the
                    theme itself, because a storefront has to look like
                    a storefront and not like a back office module.

Generating the module banners from one script is the point: hand made
banners drift a shade at a time until the vendor page stops reading as
one person's work.

    python3 tools/mna_brand.py
"""
import os

from PIL import Image, ImageDraw, ImageFont

# Sampled from the original banners so the identity is carried over
# faithfully rather than approximated again.
PLUM = "#261a24"        # ground
PLUM_GRID = "#342632"   # the grid, barely there on purpose
PURPLE = "#714b67"      # accent: left stripe, code tile, icon
TEAL = "#017e84"        # version pill, the one warm note
WHITE = "#ffffff"
SUBTITLE = "#d7c8d4"
MUTED = "#aa96a6"

BANNER = (1120, 560)
ICON_RENDER = 560
ICON_OUT = 140
AUTHOR = "Mohammad Najjarine"
VERSIONS = "Odoo 18 & 19"


def font(size, bold=True):
    path = ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def wrap(draw, text, fnt, max_width):
    words, lines, line = text.split(), [], ""
    for word in words:
        trial = (line + " " + word).strip()
        if draw.textlength(trial, font=fnt) <= max_width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def make_banner(path, code, title, subtitle):
    img = Image.new("RGB", BANNER, PLUM)
    d = ImageDraw.Draw(img)
    w, h = BANNER

    for x in range(0, w, 56):
        d.line([(x, 0), (x, h)], fill=PLUM_GRID)
    for y in range(0, h, 56):
        d.line([(0, y), (w, y)], fill=PLUM_GRID)

    d.rectangle([0, 0, 12, h], fill=PURPLE)

    # Code tile, with the type scaled to fit. A fixed size looks right
    # for two letters and overflows at four.
    d.rounded_rectangle([80, 70, 230, 220], radius=30, fill=PURPLE)
    size = 62
    cf = font(size)
    while size > 26 and d.textlength(code, font=cf) > 116:
        size -= 3
        cf = font(size)
    cw = d.textlength(code, font=cf)
    d.text((155 - cw / 2, 118 - size * 0.62), code, font=cf, fill=WHITE)
    sf = font(18, False)
    sw = d.textlength("mna", font=sf)
    d.text((155 - sw / 2, 176), "mna", font=sf, fill=SUBTITLE)

    # Title and subtitle measured then placed, so a two line title does
    # not shunt the subtitle down into the pill.
    tf, bf = font(44), font(26, False)
    title_lines = wrap(d, title, tf, w - 200)[:2]
    sub_lines = wrap(d, subtitle, bf, w - 220)[:2]

    block = len(title_lines) * 56 + 6 + len(sub_lines) * 38
    top, bottom = 262, h - 110
    y = top + max(0, (bottom - top - block) // 2)

    for line in title_lines:
        d.text((80, y), line, font=tf, fill=WHITE)
        y += 56
    y += 6
    for line in sub_lines:
        d.text((82, y), line, font=bf, fill=SUBTITLE)
        y += 38

    # Version pill.
    pf = font(22)
    pw = d.textlength(VERSIONS, font=pf)
    d.rounded_rectangle([80, h - 92, 80 + pw + 44, h - 44], radius=24, fill=TEAL)
    d.text((102, h - 80), VERSIONS, font=pf, fill=WHITE)

    af = font(22)
    aw = d.textlength(AUTHOR, font=af)
    d.text((w - 80 - aw, h - 80), AUTHOR, font=af, fill=MUTED)

    img.save(path, optimize=True)


def make_icon(path, code):
    s = ICON_RENDER
    img = Image.new("RGB", (s, s), PLUM)
    d = ImageDraw.Draw(img)

    # Rounded square in the accent, on the plum ground, so the corners
    # are not white against the store's own background.
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.17), fill=PURPLE)

    size = int(s * 0.40)
    cf = font(size)
    while size > 60 and d.textlength(code, font=cf) > s * 0.72:
        size -= 6
        cf = font(size)
    cw = d.textlength(code, font=cf)
    d.text((s / 2 - cw / 2, s * 0.50 - size * 0.78), code, font=cf, fill=WHITE)

    sf = font(int(s * 0.115), False)
    sw = d.textlength("mna", font=sf)
    d.text((s / 2 - sw / 2, s * 0.645), "mna", font=sf, fill=SUBTITLE)

    img.resize((ICON_OUT, ICON_OUT), Image.LANCZOS).save(path, optimize=True)


MODULES = [
    # repo, module, code, title, subtitle
    ("mna-odoo-apps", "mna_approval_matrix", "AM", "Approval Matrix",
     "Multi-level approval on any document, with a trail that cannot be edited"),

    ("mna-odoo-apps", "mna_access_governance", "AG", "Access Governance",
     "Why this user can do that, and every security change since"),

    ("mna-odoo-addons", "mna_health_check", "HC", "Odoo Health Check",
     "One screen for the things that quietly break"),

    ("mna-odoo-addons", "mna_mcp_server", "MCP", "MCP Server for Odoo",
     "Connect Claude, ChatGPT and any MCP client to Odoo"),

    ("mna-odoo-addons", "mna_sequence_gap", "SEQ",
     "Sequence Gap & Duplicate Report",
     "Find missing and duplicated numbers before the auditor does"),

    ("mna-odoo-addons", "mna_mcp_tool_packs", "PACK",
     "MCP Tool Packs for Odoo",
     "Exact sales, accounting and stock figures for an AI client"),

    ("mna-odoo-addons", "mna_currency_rate", "FX",
     "Currency Rate Auto Update",
     "Daily exchange rates for Odoo Community"),

    ("mna-odoo-addons", "mna_pos_session_check", "POS",
     "POS Session Check",
     "The sessions that closed short, stayed open, or never reached your accounts"),

    ("mna-odoo-addons", "mna_pos_sales_insight", "PSI",
     "POS Sales Insight",
     "Margin, what discounts cost, and when the shop is actually busy"),

    ("mna-odoo-addons", "mna_pos_z_report", "Z",
     "POS X/Z Report & Daily Closing",
     "The end of day report Odoo's Point of Sale does not have"),

    ("mna-odoo-addons", "mna_sale_order_check", "SOC",
     "Sales Order Check",
     "Sold under cost, discounted past the limit, delivered and never invoiced"),

    ("mna-odoo-addons", "mna_quotation_aging", "QA",
     "Quotation Pipeline Aging",
     "How old the open quotations are, and who wins"),

    ("mna-odoo-apps", "mna_sale_discount_approval", "DISC",
     "Sales Discount Approval",
     "No discount goes out of the door without someone allowing it"),

    ("mna-odoo-apps", "mna_sale_credit_hold", "CRED",
     "Sales Credit Hold",
     "Actually stop an order that takes a customer past their limit"),

    ("mna-odoo-addons", "mna_pos_multi_currency", "FX2",
     "POS Multi-Currency Payments",
     "Take payment in a second currency at a rate you control"),

    ("mna-odoo-addons", "mna_attendance_sheet", "ATT",
     "Monthly Attendance Sheet",
     "Who came late, who left early, who did not come at all"),

    ("mna-odoo-addons", "mna_leave_balance", "LVB",
     "Time Off Balance & Ledger",
     "Allocated, taken, pending and remaining, with every movement behind it"),

    ("mna-odoo-apps", "mna_attendance_regularize", "FIX",
     "Attendance Correction Requests",
     "Missing and wrong punches fixed through an approval, not a silent edit"),

    ("mna-odoo-apps", "mna_timeoff_approval", "LVL",
     "Multi-Level Time Off Approval",
     "Approval levels chosen by how long the request is"),

    ("mna-odoo-apps", "mna_fx_revaluation", "FXR",
     "Multi-Currency Revaluation",
     "Unrealised FX gain and loss, posted and reversed"),

    ("mna-odoo-apps", "mna_db_performance", "DB",
     "Database Performance & Storage",
     "Where your database size actually goes, and how to get it back"),

    ("mna-odoo-apps", "mna_customer_statement", "SOA",
     "Customer Statement of Account",
     "Opening balance, transactions, running balance and aging"),

    ("mna-odoo-apps", "mna_inventory_adjustment", "ADJ",
     "Backdated Inventory Adjustment",
     "Post an adjustment on a date that has already passed"),

    ("mna-odoo-apps", "mna_pdc_management", "PDC",
     "Post-Dated Cheque Management",
     "Register, track and clear cheques received and issued"),

    ("mna-odoo-apps", "mna_purchase_approval", "APR",
     "Purchase Order Approval",
     "Multi-level approval by amount, and approval to cancel"),

    ("mna-odoo-apps", "mna_purchase_report", "PO",
     "Professional Purchase Order Report",
     "A purchase order PDF you are happy to send out"),

    ("mna-odoo-addons", "mna_bom_where_used", "WHR",
     "BoM Where Used",
     "Every product you would break by changing this component"),

    ("mna-odoo-addons", "mna_mrp_order_check", "MOC",
     "Manufacturing Order Check",
     "The orders that closed short, consumed nothing, or cost nothing"),

    ("mna-odoo-apps", "mna_bom_cost_rollup", "ROL",
     "Multi-Level BoM Cost Rollup",
     "What it really costs to build, rolled up through every level"),

    ("mna-odoo-apps", "mna_mrp_cost_variance", "VAR",
     "Manufacturing Cost Variance",
     "Used too much, or paid too much: two different problems"),
]


def main():
    # The MODULES entries are repo relative, so the root is the directory
    # that holds both repos as siblings, which is the grandparent of this
    # script's repo rather than the repo itself.
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root = os.path.dirname(repo)
    only = os.environ.get("MNA_ONLY", "").split(",") if os.environ.get("MNA_ONLY") else None
    made = 0
    for repo, module, code, title, subtitle in MODULES:
        if only and module not in only:
            continue
        folder = os.path.join(root, repo, module, "static", "description")
        if not os.path.isdir(folder):
            print("skip (not checked out here):", repo, module)
            continue
        make_banner(os.path.join(folder, "banner.png"), code, title, subtitle)
        make_icon(os.path.join(folder, "icon.png"), code)
        print("ok", module)
        made += 1
    print("generated", made, "banner and icon pairs")
    print("note: themes keep the jade identity and are not touched here")


if __name__ == "__main__":
    main()
