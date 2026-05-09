// frontend/lib/mock-orders.ts

import type { OrderScenario } from "@/types/order";

export const mockOrders: OrderScenario[] = [
  {
    orderNumber: "U-1001",
    status: "Delivered",
    promise: "Delivered before promise",
    date: "May 4, 2026",
    items: "2 packages · 3 items",
    customerName: "Emma Reed",
    orderPromiseSummary: "Promised by May 6, 2026 at 8:00 PM",
    promiseStatusLabel: "Delivered before promise",
    promiseStatusTone: "success",
    customerSummary:
      "Good news — your order was delivered before the promised delivery time. You can review each package below, including delivery proof where available.",
    packages: [
      {
        packageNumber: 1,
        trackingNumber: "1Z-UNICORN-1001-A",
        carrier: "UPS",
        status: "Delivered",
        promisedDeliveryResult: "Met",
        promisedDelivery: "May 6, 2026 by 8:00 PM",
        actualOrEstimatedDelivery: "Delivered May 5, 2026 at 3:42 PM",
        fullTrackingUrl: "#",
        items: [
          {
            itemName: "Everyday Cloud Tee",
            color: "Black",
            size: "M",
            qty: 1,
            price: "$38.00",
            imageGradient: "from-neutral-900 to-neutral-500",
          },
          {
            itemName: "SoftForm Rib Tank",
            color: "Ivory",
            size: "M",
            qty: 1,
            price: "$28.00",
            imageGradient: "from-stone-100 to-stone-300",
          },
        ],
        milestones: [
          {
            label: "Shipped",
            date: "May 4, 5:42 PM",
            position: 8,
            tone: "success",
          },
          {
            label: "In transit",
            date: "May 5, 8:20 AM",
            position: 38,
            tone: "success",
          },
          {
            label: "Delivered",
            date: "May 5, 3:42 PM",
            position: 62,
            tone: "success",
          },
          {
            label: "Promise",
            date: "May 6, 8:00 PM",
            position: 86,
            tone: "promise",
          },
        ],
        deliveryProof: {
          deliveredAt: "May 5, 2026 at 3:42 PM",
          locationNote: "Front porch",
          imageDescription: "Proof photo available from carrier delivery scan",
        },
      },
      {
        packageNumber: 2,
        trackingNumber: "1Z-UNICORN-1001-B",
        carrier: "UPS",
        status: "Delivered",
        promisedDeliveryResult: "Met",
        promisedDelivery: "May 6, 2026 by 8:00 PM",
        actualOrEstimatedDelivery: "Delivered May 5, 2026 at 6:10 PM",
        fullTrackingUrl: "#",
        items: [
          {
            itemName: "AirSoft Utility Jacket",
            color: "Sand",
            size: "M",
            qty: 1,
            price: "$118.00",
            imageGradient: "from-yellow-100 to-stone-400",
          },
        ],
        milestones: [
          {
            label: "Shipped",
            date: "May 4, 7:05 PM",
            position: 10,
            tone: "success",
          },
          {
            label: "In transit",
            date: "May 5, 10:45 AM",
            position: 40,
            tone: "success",
          },
          {
            label: "Delivered",
            date: "May 5, 6:10 PM",
            position: 66,
            tone: "success",
          },
          {
            label: "Promise",
            date: "May 6, 8:00 PM",
            position: 86,
            tone: "promise",
          },
        ],
        deliveryProof: {
          deliveredAt: "May 5, 2026 at 6:10 PM",
          locationNote: "Front door",
          imageDescription: "Proof photo available from carrier delivery scan",
        },
      },
    ],
  },
  {
    orderNumber: "U-1002",
    status: "Delivered Late",
    promise: "Service recovery available",
    date: "May 2, 2026",
    items: "1 package · 1 item",
    customerName: "Emma Reed",
    orderPromiseSummary: "Promised by May 6, 2026 at 8:00 PM",
    promiseStatusLabel: "Delivered after promise",
    promiseStatusTone: "danger",
    customerSummary:
      "We’re sorry your order arrived later than promised. We’ve refunded your shipping fee and added a 10% offer for your next Unicorn order.",
    packages: [
      {
        packageNumber: 1,
        trackingNumber: "1Z-UNICORN-1002",
        carrier: "UPS",
        status: "Delivered Late",
        promisedDeliveryResult: "Missed",
        promisedDelivery: "May 6, 2026 by 8:00 PM",
        actualOrEstimatedDelivery: "Delivered May 7, 2026 at 11:18 AM",
        fullTrackingUrl: "#",
        items: [
          {
            itemName: "SoftStride Jogger",
            color: "Olive",
            size: "M",
            qty: 1,
            price: "$68.00",
            imageGradient: "from-green-800 to-lime-700",
          },
        ],
        milestones: [
          {
            label: "Shipped",
            date: "May 2, 4:44 PM",
            position: 10,
            tone: "success",
          },
          {
            label: "In transit",
            date: "May 4, 9:12 PM",
            position: 44,
            tone: "neutral",
          },
          {
            label: "Promise",
            date: "May 6, 8:00 PM",
            position: 72,
            tone: "promise",
          },
          {
            label: "Delivered late",
            date: "May 7, 11:18 AM",
            position: 92,
            tone: "danger",
          },
        ],
        deliveryProof: {
          deliveredAt: "May 7, 2026 at 11:18 AM",
          locationNote: "Front door",
          imageDescription: "Proof photo available from carrier delivery scan",
        },
      },
    ],
    serviceRecovery: {
      title: "We’ve made this right",
      description:
        "Your shipping fee has been refunded. We’ve also added 10% off your next Unicorn order.",
      badge: "Shipping refunded",
      secondaryBadge: "UNICORN10",
      tone: "refund",
    },
  },
  {
    orderNumber: "U-1003",
    status: "In Transit",
    promise: "Weather delay anticipated",
    date: "May 5, 2026",
    items: "1 package · 1 item",
    customerName: "Emma Reed",
    orderPromiseSummary: "Promised by May 8, 2026 at 8:00 PM",
    promiseStatusLabel: "Weather delay anticipated",
    promiseStatusTone: "warning",
    customerSummary:
      "Your package is still moving, but severe weather may delay delivery beyond the original promise. We’ve added free shipping for your next Unicorn order.",
    packages: [
      {
        packageNumber: 1,
        trackingNumber: "FX-UNICORN-1003",
        carrier: "FedEx",
        status: "In Transit · Weather Delay",
        promisedDeliveryResult: "At risk",
        promisedDelivery: "May 8, 2026 by 8:00 PM",
        actualOrEstimatedDelivery: "Estimated May 9, 2026 by 8:00 PM",
        fullTrackingUrl: "#",
        items: [
          {
            itemName: "MotionFlex Hoodie",
            color: "Heather Grey",
            size: "L",
            qty: 1,
            price: "$78.00",
            imageGradient: "from-slate-300 to-slate-500",
          },
        ],
        milestones: [
          {
            label: "Shipped",
            date: "May 5, 6:25 PM",
            position: 10,
            tone: "success",
          },
          {
            label: "Weather delay",
            date: "May 7, 8:40 AM",
            position: 46,
            tone: "warning",
          },
          {
            label: "Promise",
            date: "May 8, 8:00 PM",
            position: 72,
            tone: "promise",
          },
          {
            label: "New ETA",
            date: "May 9, 8:00 PM",
            position: 90,
            tone: "danger",
          },
        ],
      },
    ],
    serviceRecovery: {
      title: "A little something for the delay",
      description:
        "Severe weather may delay your delivery. Here’s free shipping on your next Unicorn order.",
      badge: "FREESHIPNEXT",
      tone: "coupon",
    },
  },
];