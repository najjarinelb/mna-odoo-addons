# Build tools for the Najjarine Tech modules

## mna_brand.py

Generates the store banner and icon for every module, so the vendor page
reads as one person's work rather than nine hand made images that drifted
a shade at a time.

    python3 tools/mna_brand.py                      # every module
    MNA_ONLY=mna_health_check python3 tools/mna_brand.py

Run it from the directory that holds both repos, not from inside one:
the script looks for `mna-odoo-addons/` and `mna-odoo-apps/` as siblings.

### The two identities, which must not be mixed

**Apps** (every module). Deep plum ground, Odoo purple accent, teal pill.

| Part | Colour |
|---|---|
| ground | `#261a24` |
| grid lines | `#342632` |
| accent: left stripe, code tile, icon | `#714b67` |
| version pill | `#017e84` |
| title | `#ffffff` |
| subtitle | `#d7c8d4` |
| author line | `#aa96a6` |

Banner 1120x560, icon 140x140.

**Themes** (storefront work). Jade, brass and warm sand, which lives with
the theme itself. A storefront theme has to look like a storefront and not
like a back office module.

To add a module, add its entry to the `MODULES` list at the foot of the
script, then run it with `MNA_ONLY` set to that module.

## shoot.py

Playwright helper for Apps Store screenshots. Logs in, waits on real
selectors rather than `networkidle` (which never fires in Odoo, because
the bus keeps a long poll open), and shoots at a 2x device scale so the
text stays legible when the store scales the image down.
