import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ProductGrid } from "@/components/retail/ProductGrid";
import { mockProducts } from "@/lib/mock-products";

describe("ProductGrid", () => {
  it("renders a card with an illustrated image for every mock product, with a formatted price", () => {
    render(<ProductGrid />);

    for (const product of mockProducts) {
      expect(screen.getByText(product.name)).toBeInTheDocument();

      const image = screen.getByAltText(product.name) as HTMLImageElement;
      expect(image).toBeInTheDocument();
      expect(image.getAttribute("src")).toBe(product.image);
    }

    expect(screen.getByText("$28.00")).toBeInTheDocument();
  });

  it("filters products by category when a chip is clicked", () => {
    render(<ProductGrid />);

    const outerwearOnly = mockProducts.filter(
      (product) => product.category === "Outerwear"
    );
    const somethingElse = mockProducts.find(
      (product) => product.category !== "Outerwear"
    );

    fireEvent.click(screen.getByRole("button", { name: "Outerwear" }));

    for (const product of outerwearOnly) {
      expect(screen.getByText(product.name)).toBeInTheDocument();
    }

    expect(somethingElse).toBeDefined();
    expect(screen.queryByText(somethingElse!.name)).toBeNull();
  });
});
