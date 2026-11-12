"""Fixed inventory category and unit options for JC Aqua."""

INVENTORY_CATEGORIES = (
    "Fish Food",
    "Aquarium",
    "Aquarium Accessories",
)

CATEGORY_EXAMPLES = {
    "Fish Food": (
        "Fish pellets, fish flakes, fish feed, fish vitamins, food supplements"
    ),
    "Aquarium": (
        "Glass aquariums, fish tanks, fish bowls, aquarium sets"
    ),
    "Aquarium Accessories": (
        "Aquarium filters, air pumps, heaters, LED lights, air tubing, "
        "thermometers, decorations, gravel and substrates"
    ),
}

PRODUCT_UNITS = (
    "pieces",
    "packs",
    "boxes",
    "bottles",
    "kilograms",
)

DEFAULT_PRODUCT_UNIT = "pieces"
