document.addEventListener("DOMContentLoaded", () => {
    const itemList = document.querySelector("[data-item-list]");
    const itemTemplate = document.querySelector("[data-item-template]");
    const addButton = document.querySelector("[data-add-item]");
    const totalDisplay = document.querySelector("[data-order-total]");

    if (!itemList || !itemTemplate || !addButton || !totalDisplay) {
        return;
    }

    const updateForm = () => {
        const rows = [...itemList.querySelectorAll("[data-item-row]")];
        rows.forEach((row) => {
            const removeButton = row.querySelector("[data-remove-item]");
            removeButton.disabled = rows.length === 1;
        });

        const totalCents = rows.reduce((total, row) => {
            const quantity = Number(row.querySelector('[name="quantity"]').value);
            const price = Number(row.querySelector('[name="unit_price"]').value);
            if (!Number.isFinite(quantity) || !Number.isFinite(price)) {
                return total;
            }
            return total + Math.round(price * 100) * quantity;
        }, 0);
        totalDisplay.textContent = (totalCents / 100).toFixed(2);
    };

    addButton.addEventListener("click", () => {
        const newRow = itemTemplate.content.cloneNode(true);
        const index = itemList.querySelectorAll("[data-item-row]").length + 1;
        newRow.querySelectorAll(".item-mobile-label").forEach((label, fieldIndex) => {
            const input = label.nextElementSibling;
            const fieldName = input.name.replaceAll("_", "-");
            const id = `item-${fieldName}-${index}`;
            label.htmlFor = id;
            input.id = id;
            if (fieldIndex === 0) {
                input.focus();
            }
        });
        itemList.append(newRow);
        updateForm();
    });

    itemList.addEventListener("click", (event) => {
        const button = event.target.closest("[data-remove-item]");
        if (button && itemList.querySelectorAll("[data-item-row]").length > 1) {
            button.closest("[data-item-row]").remove();
            updateForm();
        }
    });

    itemList.addEventListener("input", updateForm);
    updateForm();
});
