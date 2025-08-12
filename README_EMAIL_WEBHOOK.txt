EMAIL TEMPLATES & WEBHOOK
-------------------------
Templates live in /email_templates and use Jinja variables like {{ item.vendor }}, {{ item.order_number }}, and loop over {{ photos }}.
Set env vars:
  EMAIL_FROM=fowhandorders@gmail.com
  EMAIL_TO_DEFAULT=FOWHANDSALESGROUP@NETORG2273987.onmicrosoft.com,lesia@fowhandfurniture.com,james@fowhandfurniture.com
  EMAIL_TEMPLATES_DIR=/opt/render/project/src/email_templates
  WEBHOOK_URL=https://your-webhook-or-kenect-endpoint
  WEBHOOK_TOKEN=optional-secret
Optional vendor portals button on detail page via:
  VENDOR_PORTALS_JSON={"Ashley":"https://portal.ashley.com","VendorX":"https://x.example.com"}
