import { patch } from "@web/core/utils/patch";
import { PosPayment } from "@point_of_sale/app/models/pos_payment";

/**
 * A payment method can be set to take money in another currency. When it
 * is, the amount the cashier types is what the customer handed over in
 * that currency, and the amount Odoo records is that divided by the rate.
 *
 * The conversion is repeated on the server when the order is saved, from
 * the rate on the method rather than the one sent by the browser. A till
 * left open since yesterday would otherwise book today's takings at
 * yesterday's rate.
 *
 * Odoo 18 names these methods set_amount and get_amount; Odoo 19 renamed
 * them to setAmount and getAmount. Both are patched when present so one
 * file serves both versions.
 */
const mnaMixin = {
    mnaMethod() {
        return this.payment_method_id || this.payment_method;
    },

    mnaForeignCurrency() {
        // Keyed off the currency code rather than the many2one: the POS
        // does not load res.currency, so the relation arrives as null.
        const method = this.mnaMethod();
        return method && method.mna_foreign_code ? method : false;
    },

    mnaRate() {
        const method = this.mnaForeignCurrency();
        if (!method) {
            return 1;
        }
        if (method.mna_rate_mode === "fixed" && method.mna_fixed_rate > 0) {
            return method.mna_fixed_rate;
        }
        return this.mna_live_rate || method.mna_fixed_rate || 1;
    },

    /** Record what was handed over, and derive the value to the shop. */
    mnaSetForeign(value) {
        const rate = this.mnaRate() || 1;
        const foreign = parseFloat(value) || 0;
        this.mna_amount_foreign = foreign;
        this.mna_rate_used = rate;
        return foreign / rate;
    },

    mnaForeignLabel() {
        const method = this.mnaForeignCurrency();
        if (!method || !this.mna_amount_foreign) {
            return "";
        }
        const rate = this.mnaRate();
        const code = method.mna_foreign_code;
        return `${code} ${this.mna_amount_foreign.toLocaleString()} @ ${rate.toLocaleString()}`;
    },
};

patch(PosPayment.prototype, mnaMixin);

if (PosPayment.prototype.set_amount) {
    patch(PosPayment.prototype, {
        set_amount(value) {
            if (this.mnaForeignCurrency()) {
                return super.set_amount(this.mnaSetForeign(value));
            }
            return super.set_amount(value);
        },
    });
}

if (PosPayment.prototype.setAmount) {
    patch(PosPayment.prototype, {
        setAmount(value) {
            if (this.mnaForeignCurrency()) {
                return super.setAmount(this.mnaSetForeign(value));
            }
            return super.setAmount(value);
        },
    });
}
