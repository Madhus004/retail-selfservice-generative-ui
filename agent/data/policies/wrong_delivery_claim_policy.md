# Unicorn Wrong Delivery Claim Policy

## Purpose

This policy defines what Unicorn should do when tracking says delivered but the customer says the package was not delivered to their address.

## Delivered With Proof, Customer Says Not Delivered

Condition:

- Package status is delivered.
- Delivery proof is available.
- Customer says the package was not delivered to their address, or says the delivery photo does not match their location.

Agent behavior:

- Show the delivery proof card if available.
- Do not argue with the customer.
- Offer a wrong-delivery claim form.
- Ask the customer to confirm issue details and preferred contact method.

UI behavior:

Show `wrongDeliveryClaim` canvas mode.

Claim form should collect:

- Order number
- Package ID
- Issue description
- Preferred contact method

## Claim Submission

When the customer submits the wrong-delivery claim form, create a claim record with status `submitted`.

Confirmation message:

Thanks — we submitted your wrong-delivery claim. Our service team will investigate and provide an update within 1–2 days.

UI behavior:

Show `claimSubmitted` canvas mode.

## Customer-Facing Restrictions

Do not blame the carrier.

Do not say the customer is wrong.

Do not expose internal fraud, risk, or investigation logic.

Do not promise an immediate refund or replacement unless a policy action explicitly allows it.