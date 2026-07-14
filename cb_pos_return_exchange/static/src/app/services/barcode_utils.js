/** @odoo-module **/

/**
 * Barcode normalization for USB keyboard-wedge and wireless POS scanners.
 * Supports EAN-13, UPC-A (12 digit), EAN-8, and Code128 (alphanumeric).
 */

const EAN13_LENGTH = 13;
const UPC_A_LENGTH = 12;
const EAN8_LENGTH = 8;

export function cleanScanInput(code) {
    return (code || "")
        .replace(/Alt|Shift|Control/g, "")
        .trim();
}

export function detectBarcodeFormat(code) {
    const raw = cleanScanInput(code);
    const digits = raw.replace(/\D/g, "");
    if (digits.length === EAN13_LENGTH) {
        return "ean13";
    }
    if (digits.length === UPC_A_LENGTH) {
        return "upc_a";
    }
    if (digits.length === EAN8_LENGTH) {
        return "ean8";
    }
    if (raw && /^[0-9]+$/.test(raw)) {
        return "numeric";
    }
    return "code128";
}

export function getBarcodeCandidates(code) {
    const raw = cleanScanInput(code);
    const candidates = [];
    const seen = new Set();

    const add = (value) => {
        const v = (value || "").trim();
        if (v && !seen.has(v)) {
            seen.add(v);
            candidates.push(v);
        }
    };

    add(raw);
    add(raw.toUpperCase());

    const digits = raw.replace(/\D/g, "");
    if (digits) {
        add(digits);
        if (digits.length === UPC_A_LENGTH) {
            add(`0${digits}`);
        }
        if (digits.length === EAN13_LENGTH && digits.startsWith("0")) {
            add(digits.slice(1));
        }
        const stripped = digits.replace(/^0+/, "");
        if (stripped && stripped !== digits) {
            add(stripped);
        }
    }

    const alnum = raw.replace(/[^0-9A-Za-z]/g, "");
    if (alnum && alnum !== raw) {
        add(alnum);
        add(alnum.toUpperCase());
    }

    return candidates;
}

export function isRetailProductBarcode(code) {
    const format = detectBarcodeFormat(code);
    return ["ean13", "upc_a", "ean8", "numeric"].includes(format);
}

export function matchesPrefix(code, prefix) {
    if (!prefix) {
        return false;
    }
    return cleanScanInput(code).toUpperCase().startsWith(prefix.toUpperCase());
}

export function formatBarcodeLabel(code, max = 32) {
    const raw = cleanScanInput(code);
    if (raw.length <= max) {
        return raw;
    }
    return `${raw.slice(0, max - 3)}...`;
}
