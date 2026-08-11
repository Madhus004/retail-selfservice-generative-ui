# Order Cancellation Policy

## Eligibility

- An order can be cancelled only while it is still in "Processing" status — before any package on it has shipped.
- Once any package on an order has shipped, that order (and its shipped items) are no longer eligible for cancellation. Offer a return once delivered, or a wrong-delivery claim if applicable, instead.
- Cancellation can apply to the whole order or to individual line items, and to a partial quantity of a line item when more than one unit was ordered.

## What happens after a cancellation is submitted

- Cancelled items are removed from the order and any authorized payment for those items is released or refunded to the original payment method. Refund timing is typically a few business days — do not promise an exact date unless policy context confirms one.
- If every item on the order is cancelled, the order moves to a "Cancelled" status. If only some items are cancelled, the order continues processing for the remaining items ("Partially cancelled").

## Customer-facing rules

- Confirm clearly what was cancelled (items, quantities) and the resulting order status — do not use internal terms like "eligibility gate," "line ID," or "server-side validation."
- Do not blame the customer for changing their mind.
- Do not invent a specific refund amount or exact delivery date for remaining items unless it is present in the data provided.
- Keep any generated confirmation message short — the UI already shows the cancelled items and resulting status in detail.
