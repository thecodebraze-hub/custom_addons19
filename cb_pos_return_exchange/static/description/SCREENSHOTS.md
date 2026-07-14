# Apps Store screenshots

Add the following PNG files to this folder (`static/description/`) for the Odoo Apps description page.

| File | What to capture |
|------|-----------------|
| `screenshot_pos_return.png` | POS Return screen — order found, lines selected |
| `screenshot_voucher_payment.png` | Payment screen with voucher panel |
| `screenshot_exchange.png` | Exchange screen with totals |
| `screenshot_barcode.png` | Barcode action or scan result |
| `screenshot_dashboard.png` | Returns & Exchanges reporting dashboard |
| `screenshot_config.png` | POS Configuration → Returns & Exchanges tab |
| `screenshot_receipt.png` | PDF return or voucher receipt (80 mm) |
| `screenshot_voucher_popup.png` | Voucher issued popup with barcode |
| `screenshot_product_screen.png` | Product screen showing Return / Exchange buttons |

`icon.png` — module icon (128×128 or larger), already included.

Recommended size for screenshots: **1280×720** or **1920×1080** PNG.

Until screenshots are added, you can temporarily copy `icon.png` to each filename for layout testing:

```powershell
$names = @(
  'screenshot_pos_return.png','screenshot_voucher_payment.png','screenshot_exchange.png',
  'screenshot_barcode.png','screenshot_dashboard.png','screenshot_config.png',
  'screenshot_receipt.png','screenshot_voucher_popup.png','screenshot_product_screen.png'
)
foreach ($n in $names) { Copy-Item icon.png $n }
```
