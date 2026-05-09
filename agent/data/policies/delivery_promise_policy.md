# Unicorn Delivery Promise Policy

## Purpose

This policy explains how Unicorn evaluates whether an order or package met the original delivery promise.

## Promise Evaluation Rules

### Delivered Before or On Promise

If a package has an actual delivered timestamp and the actual delivered timestamp is less than or equal to the original promised delivery timestamp, the promised delivery result is `met`.

Customer-facing status:

Promised delivery: Met

Recommended customer message:

Good news — your order was delivered within the promised delivery window.

### Delivered After Promise

If a package has an actual delivered timestamp and the actual delivered timestamp is greater than the original promised delivery timestamp, the promised delivery result is `missed`.

Customer-facing status:

Promised delivery: Missed

Recommended customer message:

We’re sorry your order arrived later than promised.

### In Transit and Estimated After Promise

If a package is still in transit and the current estimated delivery timestamp is greater than the original promised delivery timestamp, the promised delivery result is `at_risk`.

Customer-facing status:

Promised delivery: At risk

Recommended customer message:

Your package may arrive later than the original promised delivery date. We’ll continue monitoring the latest carrier updates.

## Timeline Display Rules

Do not show order created or order placed events inside the package promise timeline if the order date is already shown in the order header.

The package promise timeline should focus on key fulfillment and delivery events:

- Shipped
- Carrier exception or weather delay
- Original promise
- Delivered or new estimated delivery

The original promise should appear in chronological order relative to tracking events.