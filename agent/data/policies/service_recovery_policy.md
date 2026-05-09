# Unicorn Service Recovery Policy

## Purpose

This policy defines customer-facing recovery actions when Unicorn misses or may miss a delivery promise.

## Delivered Before or On Promise

Condition:

- Promise result is `met`.

Recovery action:

- No compensation is required.
- If delivery proof is available, show the delivery proof card.
- Do not show a service recovery card.

Customer-facing message:

Good news — your order was delivered within the promised delivery window.

## Delivered Late Due to Carrier Delay

Condition:

- Promise result is `missed`.
- Promise reason code is `carrier_delay`.

Recovery action:

- If shipping fee was paid, refund the shipping fee.
- If the customer is loyal, gold, or VIP, offer coupon code `UNICORN10`.
- If the customer is standard and not loyal, refund shipping fee only.

Customer-facing message:

We’re sorry your order arrived later than promised. We’ve refunded your shipping fee. If eligible, we’ve also added a next-order offer.

Customer-facing service recovery title:

We’ve made this right

Customer-facing badges:

- Shipping refunded
- UNICORN10, if eligible

## Weather Delay Before Delivery

Condition:

- Promise result is `at_risk`.
- Promise reason code is `weather_delay`.

Recovery action:

- Do not refund shipping before the final delivery result is known.
- Offer coupon code `FREESHIPNEXT` as a goodwill gesture.
- Explain that the package was delayed because of weather near the carrier network.

Customer-facing message:

Your package is delayed due to weather and may arrive after the original promised date. We added a free-shipping offer for your next Unicorn order.

Customer-facing service recovery title:

A little something for the delay

Customer-facing badge:

- FREESHIPNEXT

## Customer-Facing Restrictions

Do not expose internal policy terms like loyal customer logic, lifetime value, policy ID, or risk score to the customer.

Do not say “because you are a loyal customer” in the customer-facing message.

Do not show confidence percentages.

Do not show internal operational terms such as dynamic service component, A2UI, AG-UI, LangGraph, RAG, or policy retrieval in the customer-facing UI.