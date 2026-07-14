/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { makeAwaitable } from "@point_of_sale/app/utils/make_awaitable_dialog";
import {
    cleanScanInput,
    detectBarcodeFormat,
    getBarcodeCandidates,
    isRetailProductBarcode,
    matchesPrefix,
    formatBarcodeLabel,
} from "./barcode_utils";
import { BarcodeActionPopup } from "../components/popups/barcode_action_popup/barcode_action_popup";

const DEDUP_MS = 400;

/**
 * Routes USB / wireless scanner input to return, voucher, and product flows.
 */
export class CbReturnBarcodeHandler {
    constructor(pos) {
        this.pos = pos;
        this._exclusive = null;
        this._mode = "auto";
        this._lastScan = { code: "", at: 0 };
        this._settings = null;
    }

    setExclusive(handler) {
        this._exclusive = handler;
        return () => {
            if (this._exclusive === handler) {
                this._exclusive = null;
            }
        };
    }

    setMode(mode) {
        this._mode = mode;
    }

    getMode() {
        return this._mode;
    }

    extractCode(parsed, raw) {
        if (parsed?.base_code) {
            return cleanScanInput(parsed.base_code);
        }
        if (parsed?.code) {
            return cleanScanInput(parsed.code);
        }
        return cleanScanInput(raw);
    }

    isDuplicateScan(code) {
        const now = Date.now();
        if (code === this._lastScan.code && now - this._lastScan.at < DEDUP_MS) {
            return true;
        }
        this._lastScan = { code, at: now };
        return false;
    }

    async getBarcodeSettings() {
        if (this._settings) {
            return this._settings;
        }
        const result = await this.pos.returnApi.getSettings();
        this._settings = result?.settings || {
            voucher_barcode_prefix: "VCH/",
            return_barcode_prefix: "RET/",
            auto_barcode_detect: true,
        };
        return this._settings;
    }

    /**
     * Main entry from patched POS screens. Returns true when the scan is consumed.
     */
    async processScan(parsed, { screen = "product", force = false } = {}) {
        const code = this.extractCode(parsed, parsed?.code);
        if (!code || this.isDuplicateScan(code)) {
            return false;
        }
        if (this._exclusive) {
            await this._exclusive(code, parsed);
            return true;
        }

        const settings = await this.getBarcodeSettings();
        if (!settings.auto_barcode_detect && !force) {
            return false;
        }

        if (this._mode === "voucher") {
            await this._openVoucherScanner(code);
            return true;
        }
        if (this._mode === "order") {
            await this.pos.openReturnFlow({ searchTerm: code });
            return true;
        }
        if (this._mode === "product") {
            await this.pos.openReturnScreen({ searchTerm: code });
            return true;
        }

        const classification = await this.classify(code, settings);
        if (!classification?.success) {
            if (screen === "product") {
                return false;
            }
            await this._handleInvalidScan(code, classification || {}, screen);
            return true;
        }

        if (classification.barcode_type === "product" && screen === "product") {
            const local = this.pos.returnApi.findLocalProduct(code);
            if (local) {
                return false;
            }
        }

        if (classification.error_code === "barcode_unknown") {
            await this._handleInvalidScan(code, classification, screen);
            return screen !== "product";
        }

        return this._presentActions(classification, screen);
    }

    async classify(code, settings = null) {
        settings = settings || (await this.getBarcodeSettings());
        const local = this._classifyLocal(code, settings);
        if (local) {
            return local;
        }
        if (this.pos.returnApi.isOffline) {
            return {
                success: false,
                error_code: "barcode_unknown",
                error: _t("Barcode not found in offline cache."),
                barcode: code,
                format: detectBarcodeFormat(code),
            };
        }
        return this.pos.returnApi.classifyBarcode(code);
    }

    _classifyLocal(code, settings) {
        const format = detectBarcodeFormat(code);
        const voucherPrefix = settings.voucher_barcode_prefix || "VCH/";
        const returnPrefix = settings.return_barcode_prefix || "RET/";

        if (matchesPrefix(code, voucherPrefix)) {
            return {
                success: true,
                barcode_type: "voucher",
                barcode_format: format,
                barcode: code,
                label: code,
                actions: [
                    { id: "redeem_voucher", label: _t("Redeem Voucher") },
                    { id: "view_voucher", label: _t("View Voucher") },
                ],
                data: { barcode: code },
                _local: true,
            };
        }
        if (matchesPrefix(code, returnPrefix)) {
            return {
                success: true,
                barcode_type: "return",
                barcode_format: format,
                barcode: code,
                label: code,
                actions: [
                    { id: "view_return", label: _t("View Return") },
                    { id: "return_history", label: _t("Return History") },
                ],
                data: { name: code },
                _local: true,
            };
        }

        const product = this.pos.returnApi.findLocalProduct(code);
        if (product && isRetailProductBarcode(code)) {
            return {
                success: true,
                barcode_type: "product",
                barcode_format: format,
                barcode: code,
                label: product.display_name,
                actions: [
                    { id: "return_product", label: _t("Return Product") },
                    { id: "find_orders", label: _t("Find Orders") },
                ],
                data: {
                    id: product.id,
                    name: product.display_name,
                    barcode: product.barcode,
                },
                _local: true,
            };
        }

        const order = this.pos.returnApi.findLocalOrderByReference(code);
        if (order) {
            return {
                success: true,
                barcode_type: "order",
                barcode_format: format,
                barcode: code,
                label: order.pos_reference || order.name,
                actions: [
                    { id: "start_return", label: _t("Start Return") },
                    { id: "return_history", label: _t("Return History") },
                ],
                data: { id: order.id },
                _local: true,
            };
        }
        return null;
    }

    async _presentActions(classification, screen) {
        const type = classification.barcode_type;
        const primary = this._primaryAction(type, screen);
        const actions = classification.actions || [];

        if (screen === "payment" && type === "voucher" && primary === "redeem_voucher") {
            return this._executeAction("redeem_voucher", classification);
        }
        if (screen === "product" && type === "order" && primary === "start_return") {
            return this._executeAction("start_return", classification);
        }
        if (actions.length === 1) {
            return this._executeAction(actions[0].id, classification);
        }

        const choice = await makeAwaitable(this.pos.dialog, BarcodeActionPopup, {
            pos: this.pos,
            classification,
        });
        if (!choice?.action) {
            return true;
        }
        return this._executeAction(choice.action, classification);
    }

    _primaryAction(type, screen) {
        if (screen === "payment" && type === "voucher") {
            return "redeem_voucher";
        }
        if (type === "order") {
            return "start_return";
        }
        if (type === "product") {
            return "return_product";
        }
        if (type === "voucher") {
            return "redeem_voucher";
        }
        if (type === "return") {
            return "view_return";
        }
        return null;
    }

    async _executeAction(actionId, classification) {
        const data = classification.data || {};
        const code = classification.barcode;
        switch (actionId) {
            case "redeem_voucher":
                if (this.pos.router?.state?.current === "PaymentScreen") {
                    await this.pos.applyVoucherFromPaymentScan(code, { promptPartial: true });
                } else {
                    await this._openVoucherScanner(code);
                }
                break;
            case "view_voucher": {
                const result = await this.pos.returnApi.validateVoucher(code);
                if (result?.success) {
                    await this.pos.showVoucherPopup(result.voucher);
                } else {
                    this._notifyInvalid(result?.error || _t("Voucher not found."));
                }
                break;
            }
            case "return_product":
                await this.pos.openReturnScreen({ searchTerm: code });
                break;
            case "find_orders": {
                const result = await this.pos.returnApi.findProduct({
                    barcode: code,
                    productId: data.id,
                });
                if (result?.success && result.orders?.length) {
                    await this.pos.openReturnScreen({
                        order: result.orders[0],
                        orderId: result.orders[0].id,
                    });
                } else {
                    this._notifyInvalid(result?.error || _t("No returnable orders found."));
                }
                break;
            }
            case "start_return": {
                const result = await this.pos.returnApi.findOrder(code);
                if (result?.success) {
                    await this.pos.openReturnScreen({
                        order: result.order,
                        orderId: result.order.id,
                    });
                } else {
                    await this.pos.openReturnScreen({ searchTerm: code });
                }
                break;
            }
            case "return_history":
                await this.pos.openHistoryPopup({
                    orderId: data.id || data.original_order_id,
                    partnerId: data.partner_id,
                });
                break;
            case "view_return":
                this.pos.notification.add(
                    _t("Return document: %s", data.name || code),
                    { type: "info" }
                );
                break;
            default:
                this._notifyInvalid(_t("Unsupported barcode action."));
        }
        return true;
    }

    async _openVoucherScanner(code) {
        const settings = await this.pos.returnApi.getSettings();
        if (!this.guardPermission(settings, "redeem_voucher")) {
            return;
        }
        await this.pos.openVoucherScanner({ barcode: code });
    }

    async _handleInvalidScan(code, result, screen) {
        this.pos.sound?.play?.("scan-error");
        const format = result.format || detectBarcodeFormat(code);
        const message =
            result.error ||
            _t("No product, voucher, or return matches barcode %(barcode)s.", {
                barcode: formatBarcodeLabel(code),
            });
        if (screen === "product") {
            return;
        }
        this.pos.notification.add(message, {
            type: "warning",
            title: _t("Invalid Barcode (%(format)s)", { format: format.toUpperCase() }),
        });
    }

    _notifyInvalid(message) {
        this.pos.sound?.play?.("scan-error");
        this.pos.notification.add(message, {
            type: "danger",
            title: _t("Invalid Barcode"),
        });
    }

    buildCallbackMap(component) {
        const handler = async (parsed) => {
            await component.onBarcodeScanned?.(this.extractCode(parsed, parsed?.code), parsed);
        };
        return {
            product: (parsed) => handler(parsed),
            weight: (parsed) => handler(parsed),
            quantity: (parsed) => handler(parsed),
            price: (parsed) => handler(parsed),
            gs1: (parsed) => {
                const product = parsed?.find?.((p) => p.type === "product");
                if (product?.code) {
                    handler(product, product.code);
                }
            },
        };
    }

    guardPermission(settings, key) {
        const permissions = settings?.permissions || {};
        if (!permissions[key]) {
            this.pos.notification.add(_t("Permission denied."), { type: "danger" });
            return false;
        }
        return true;
    }

    getCandidateCodes(code) {
        return getBarcodeCandidates(code);
    }
}
