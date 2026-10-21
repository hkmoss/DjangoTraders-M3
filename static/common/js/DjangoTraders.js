/*
    Project-wide custom JavaScript.

    Lives in static/common/js/ (project-root static/ folder, registered
    via STATICFILES_DIRS in settings.py), parallel to templates/common/
    holding the project-wide base.html. Loaded from base.html after
    jQuery and DataTables, so anything here can rely on both already
    being present.

    Each Make*DataTable(tableId) function below applies DataTables to
    one named table by id -- pageLength/lengthMenu raise DataTables'
    own default of 10 rows per page and the choices in its "Show N
    entries" dropdown. Kept as one function per table, repeating the
    same settings, rather than a shared helper -- simple beats DRY
    here: a table with its own quirk (an unsortable icon column, a
    custom sort order) just sets that option in its own function
    instead of a generic helper needing extra parameters to handle
    every table's special case.

    MakeCustomersDataTable (customer_list.html) also disables sorting
    on its Actions column (an icon, not sortable data), and swaps the
    entries-per-page dropdown and "Showing X of Y" positions.
    MakeProductsDataTable (product_list.html) also disables sorting on
    its Actions column. MakeOrdersDataTable (customer_detail.html) and
    MakeProductOrdersDataTable (product_detail.html) both default to
    sorting by Order Date, descending, instead of DataTables' own
    default (first column, ascending). MakeOrderDetailsDataTable
    (order_detail.html) uses the plain defaults -- no special options
    needed.

    ValidateCustomerEditForm (customer_edit.html) is a hand-written
    jQuery illustration of client-side validation, alongside (not
    instead of) the HTML5 pattern= attributes and Django's own
    clean_<field>() methods (djtraders/forms.py) already doing the
    real work -- see its own comment below.

    AddOrderLineItem (order_build.html) is this project's one
    AJAX-driven workflow -- see its own comment below. It swaps in a
    server-rendered partial (_order_add_card.html) after each add, and
    ActivateProductSearch attaches the jQuery UI Autocomplete to that
    partial's Product box.
*/

// #region DataTables activation functions
function MakeCustomersDataTable(tableId) {
    $(tableId).DataTable({
        pageLength: 20,
        lengthMenu: [ [10, 20, 25, 50, -1], [10, 20, 25, 50, "All"] ],
        columnDefs: [
            { targets: -1, orderable: false }
        ],
        layout: {
            topStart: 'info',
            topEnd: 'search',
            bottomStart: 'pageLength',
            bottomEnd: 'paging'
        },
    });
}

function MakeProductsDataTable(tableId) {
    $(tableId).DataTable({
        pageLength: 20,
        lengthMenu: [ [10, 20, 25, 50, -1], [10, 20, 25, 50, "All"] ],
        columnDefs: [
            { targets: -1, orderable: false }
        ],
        layout: {
            topStart: 'info',
            topEnd: 'search',
            bottomStart: 'pageLength',
            bottomEnd: 'paging'
        }
    });
}

function MakeOrdersDataTable(tableId) {
    $(tableId).DataTable({
        pageLength: 20,
        lengthMenu: [ [10, 20, 25, 50, -1], [10, 20, 25, 50, "All"] ],
        // Column 1 is Order Date; 'desc' shows the most recent order first
        // by default, instead of DataTables' own default (column 0, asc).
        order: [[1, 'desc']]
    });
}

function MakeOrderDetailsDataTable(tableId) {
    $(tableId).DataTable({
        pageLength: 20,
        lengthMenu: [ [10, 20, 25, 50, -1], [10, 20, 25, 50, "All"] ]
    });
}

function MakeProductOrdersDataTable(tableId) {
    $(tableId).DataTable({
        pageLength: 20,
        lengthMenu: [ [10, 20, 25, 50, -1], [10, 20, 25, 50, "All"] ],
        // Column 1 is Order Date; 'desc' shows the most recent order first
        // by default, instead of DataTables' own default (column 0, asc).
        order: [[1, 'desc']]
    });
}
// #endregion

/*
    ValidateCustomerEditForm -- client-side validation for customer_edit.html,
    layered alongside (not instead of) the HTML5 pattern= attributes
    CustomerEditForm's __init__ sets AND Django's own server-side check
    (clean_phone()/clean_company_name()/clean_city(), djtraders/forms.py).
    The server-side check is the one that actually enforces the rule --
    this only improves the browser experience.

    Its three regexes are hand-copied from forms.py's PHONE_PATTERN/
    NO_DIGITS_PATTERN. A static .js file can't import from a Python
    module, so the two copies have to be kept in sync by hand; if they
    ever drift apart, the server-side check still wins because it runs
    last and is the actual gate.

    Uses a plain 'submit' event listener with preventDefault() on
    failure, not AJAX -- the page still does a full POST/redirect on
    success. Note: a script that calls a form's native .submit()
    method (rather than a real click or Enter key) does not fire the
    'submit' event at all, so this validation -- like the HTML5
    pattern= attributes -- can be bypassed that way. That's inherent
    to client-side validation generally, not a gap specific to this
    function.
*/
function ValidateCustomerEditForm(formId) {
    // Same three patterns as forms.py's PHONE_PATTERN/NO_DIGITS_PATTERN,
    // hand-copied into JS since a .js file can't import from forms.py.
    const PHONE_PATTERN = /^[0-9()\-\s]{7,20}$/;
    const NO_DIGITS_PATTERN = /^[^0-9]*$/;

    // Shows (or clears) one field's error the same way crispy/Bootstrap
    // already render a server-side error (is-invalid + a sibling
    // .invalid-feedback), so a client-caught error and a server-caught
    // one look identical to someone just looking at the page.
    function setFieldError(fieldId, message) {
        const field = document.getElementById(fieldId);
        let feedback = field.parentElement.querySelector(".js-invalid-feedback");
        if (!feedback) {
            feedback = document.createElement("div");
            feedback.className = "invalid-feedback js-invalid-feedback";
            field.insertAdjacentElement("afterend", feedback);
        }
        if (message) {
            field.classList.add("is-invalid");
            feedback.textContent = message;
            feedback.style.display = "block";
        } else {
            field.classList.remove("is-invalid");
            feedback.style.display = "none";
        }
    }

    $(formId).on("submit", function (event) {
        let valid = true;

        // company_name is required (HTML5 required= already blocks an
        // empty submission before this handler ever runs on a real
        // click) -- an empty value here is skipped, not flagged, so
        // this check never fights with that native "required" message.
        const companyName = $("#id_company_name").val().trim();
        if (companyName && !NO_DIGITS_PATTERN.test(companyName)) {
            setFieldError("id_company_name", "Company name can't contain numbers.");
            valid = false;
        } else {
            setFieldError("id_company_name", null);
        }

        // phone and city are both optional (blank=True, null=True on
        // the model) -- an empty value is valid and skips its pattern
        // check entirely, the same way clean_phone()/clean_city() do
        // server-side (forms.py).
        const phone = $("#id_phone").val().trim();
        if (phone && !PHONE_PATTERN.test(phone)) {
            setFieldError("id_phone", "Enter a valid phone number (digits, spaces, parentheses, and dashes only, 7-20 characters).");
            valid = false;
        } else {
            setFieldError("id_phone", null);
        }

        const city = $("#id_city").val().trim();
        if (city && !NO_DIGITS_PATTERN.test(city)) {
            setFieldError("id_city", "City can't contain numbers.");
            valid = false;
        } else {
            setFieldError("id_city", null);
        }

        if (!valid) {
            event.preventDefault();
        }
    });
}

/*
    AddOrderLineItem -- wires up order_build.html's Add to Cart card
    (the _order_add_card.html partial). Submitting its form POSTs to
    order_add_line (djtraders/views.py) via AJAX, patching the page in
    place instead of reloading it. This is the project's one AJAX-driven
    view: a customer can add several products in a row without the page
    reloading each time, then commit the whole order at once. Changing
    the card's Filter by Category dropdown also swaps the card in place
    (see below), so nothing on this page reloads the whole page.

    On success order_add_line returns JSON holding three things -- the
    new line's table row (row_html), the running total, and a freshly
    rendered, empty Add to Cart card (card_html). The row is appended to
    (or replaces) the Cart Items table, the total is updated, and the
    card is swapped for the fresh one, so the user starts over with an
    empty Product box, quantity 1, discount 0, and no category filter. On
    failure nothing is swapped: only an error message appears, so what
    was typed stays put while the user fixes it.

    The same swap happens when the category changes: order_add_card
    returns the card rendered for the chosen category (nothing in the
    cart changes, and typed-in values reset along with the card).

    Swapping the card replaces its elements outright, which has two
    consequences for this code. The submit and change listeners are
    attached to document (jQuery's delegated form: .on(event, selector,
    handler)), which is never replaced, so they keep working on each new
    copy of the card; and the Product autocomplete is a separate function
    (ActivateProductSearch) that runs again on every new text box. Elements
    are looked up inside the handler, at the moment they're needed,
    instead of being saved once up front -- a saved reference would
    still point at the old, removed card.

    Checks the bare minimum client-side before submitting -- a product
    is selected, quantity is a positive number, and (Enhancement 5)
    quantity doesn't exceed that product's own units_in_stock, read
    from the product-stock-data JSON block the card embeds
    (json_script, {product_id: units_in_stock}). All three are courtesy
    checks only; OrderDetailForm/order_add_line (djtraders/forms.py,
    djtraders/views.py) run the real, authoritative versions server-side.

    formId: the Add to Cart <form>'s own id ("#order-detail-form"),
    passed in from order_build.html's {% block scripts %} rather than
    hard-coded, the same way ValidateCustomerEditForm takes its form id
    as an argument.
*/
function AddOrderLineItem(formId) {
    ActivateProductSearch();

    // Errors come back either as plain strings (order_add_line's own
    // access/state checks, views.py) or as {message, code} objects
    // (Django's form.errors.get_json_data(), for OrderDetailForm's
    // field validation) -- normalized to plain text either way.
    function messagesFrom(errors) {
        return Object.values(errors || {})
            .flat()
            .map((error) => (typeof error === "string" ? error : error.message));
    }

    function showError(message) {
        $("#order-detail-form-error").text(message).removeClass("d-none");
    }

    // Changing the Filter by Category dropdown asks order_add_card
    // (djtraders/views.py) for the whole card re-rendered for that
    // category, and swaps it in -- the Product search and stock data
    // both narrow to it, with no page reload. The dropdown lives inside
    // the card, so it comes back from the server already set.
    $(document).on("change", "#id_category_filter", function () {
        $.get($(this).data("cardUrl"), { category: $(this).val() })
            .done(function (cardHtml) {
                $("#add-to-cart-card").replaceWith(cardHtml);
                ActivateProductSearch();
            })
            .fail(function () {
                showError("Couldn't load that category -- try again.");
            });
    });

    $(document).on("submit", formId, function (event) {
        event.preventDefault();
        const $form = $(this);
        $("#order-detail-form-error").text("").addClass("d-none");

        const productId = $("#id_product").val();
        const quantity = parseInt($("#id_quantity").val(), 10);

        if (!productId) {
            showError("Pick a product from the suggestions.");
            return;
        }
        if (!quantity || quantity < 1) {
            showError("Quantity must be at least 1.");
            return;
        }
        // Enhancement 5: {product_id: units_in_stock}, read from the
        // card's own <script type="application/json"> tag -- plain text
        // already in the page, not an AJAX call.
        const stockDataEl = document.getElementById("product-stock-data");
        const productStock = stockDataEl ? JSON.parse(stockDataEl.textContent) : {};
        const unitsInStock = productStock[productId];
        if (unitsInStock !== null && unitsInStock !== undefined && quantity > unitsInStock) {
            showError(`Only ${unitsInStock} left in stock.`);
            return;
        }

        $.ajax({
            url: $form.attr("action"),
            method: "POST",
            data: $form.serialize(),
            dataType: "json",
        }).done(function (response) {
            if (!response.success) {
                showError(messagesFrom(response.errors).join(" ") || "Couldn't add that to your cart.");
                return;
            }

            $("#order-lines-empty-row").remove();
            const $existingRow = $(`#order-lines-body tr[data-product-id="${response.product_id}"]`);
            if ($existingRow.length) {
                $existingRow.replaceWith(response.row_html);
            } else {
                $("#order-lines-body").append(response.row_html);
            }
            $("#order-total").text("$" + response.order_total);

            // Swap in the server's fresh, empty card and re-attach the
            // autocomplete to its new text box.
            $("#add-to-cart-card").replaceWith(response.card_html);
            ActivateProductSearch();
        }).fail(function (xhr) {
            // A validation failure (order_add_line's own 400/403 JsonResponse,
            // views.py) lands here, not in .done() above -- jQuery treats
            // any non-2xx HTTP status as a failure regardless of the
            // response body, so the real error message has to be read
            // from xhr.responseJSON. Fall back to a generic message only
            // when there's no JSON to read (a network failure or 500).
            const messages = xhr.responseJSON ? messagesFrom(xhr.responseJSON.errors) : [];
            showError(messages.join(" ") || "Something went wrong adding that to your cart -- try again.");
        });
    });
}

/*
    ActivateProductSearch -- turns the Add to Cart card's #product-search
    text box into a jQuery UI Autocomplete. Typing queries
    product_search_json (djtraders/views.py) for matching non-discontinued
    products, flags any low on stock with a "Low stock" badge in the
    suggestion list and under the field once picked, and copies the chosen
    product's id into the hidden #id_product field the form actually
    submits. Called once on page load and again whenever AddOrderLineItem
    swaps in a fresh card, since the new text box has no autocomplete yet.
*/
function ActivateProductSearch() {
    // #product-search is the visible, autocomplete-only text box;
    // #id_product is the hidden field holding the real Product pk that
    // gets POSTed. minLength: 0 allows a search on an empty box -- by
    // itself that still waits for a keystroke, so the focus/click handler
    // below asks for one explicitly, listing products as soon as the box
    // is entered. Fine for a catalog this size; a real one would raise
    // minLength to keep every keystroke-less query from returning
    // everything.
    const $productSearch = $("#product-search");
    const $productId = $("#id_product");
    const $lowStockNote = $("#product-low-stock-note");

    function showLowStock(item) {
        if (item && item.low_stock) {
            $("#product-low-stock-count").text(`Only ${item.units_in_stock} left`);
            $lowStockNote.removeClass("d-none");
        } else {
            $lowStockNote.addClass("d-none");
        }
    }

    $productSearch.autocomplete({
        minLength: 0,
        // A function source (instead of a bare URL) so the current
        // category filter can ride along with the typed term.
        source: function (request, response) {
            $.getJSON($productSearch.data("searchUrl"), {
                term: request.term,
                category: $productSearch.data("category"),
            }).done(response).fail(function () {
                response([]);
            });
        },
        select: function (event, ui) {
            $productId.val(ui.item.id);
            showLowStock(ui.item);
        },
    });

    // Entering the box searches with whatever it already holds (nothing,
    // on a fresh card), which is what makes a zero-character search
    // actually fire.
    $productSearch.on("focus click", function () {
        $productSearch.autocomplete("search", $productSearch.val());
    });

    // Typing again after a pick invalidates it: without this, editing the
    // text would leave the old product's id in the hidden field.
    $productSearch.on("input", function () {
        $productId.val("");
        showLowStock(null);
    });

    // jQuery UI draws each suggestion as plain text by default; this
    // override builds the <li> by hand so a "Low stock" badge can sit
    // beside the label. .text() (never string-built HTML) escapes the
    // product name, so a name containing markup can't inject anything.
    $productSearch.autocomplete("instance")._renderItem = function (ul, item) {
        const $row = $("<div>").text(item.label);
        if (item.low_stock) {
            $row.append(
                $("<span>")
                    .addClass("badge text-bg-warning ms-2")
                    .text(`Low stock (${item.units_in_stock})`)
            );
        }
        return $("<li>").append($row).appendTo(ul);
    };
}

// #region Page tabs (customer, supplier and employee pages)
// customer_detail.html, supplier_detail.html and employee_detail.html are page shells with a
// Bootstrap tab control; each tab's content is a partial template (no
// base.html) fetched with $.get from the tab button's data-url and dropped
// into its pane. Each tab loads once, the first time it is shown. jQuery's
// .html() also runs the small <script> inside each Plotly chart, which is
// what actually draws it.
function ActivatePageTabs(tabsSelector) {
    const $tabs = $(tabsSelector);

    // Bootstrap fires shown.bs.tab on the button that just became active.
    $tabs.on("shown.bs.tab", "button[data-bs-toggle='tab']", function () {
        LoadPageTab($(this));
    });

    // The first tab is already active when the page opens, so Bootstrap
    // never fires an event for it -- load it by hand.
    LoadPageTab($tabs.find("button.active"));
}

// Each table a tab can load, by id, and the function that turns it into
// a DataTable once it is in the page.
const TAB_TABLE_MAKERS = {
    "#orders-table": MakeOrdersDataTable,
    "#supplier-orders-table": MakeSupplierOrdersDataTable,
    "#product-revenue-table": MakeProductRevenueDataTable,
    "#employees-table": MakeEmployeesDataTable,
    "#leaderboard-table": MakeLeaderboardDataTable,
};

function LoadPageTab($tabButton) {
    const $pane = $($tabButton.data("bs-target"));
    if ($pane.data("loaded")) {
        return;
    }
    $pane.text("Loading…");
    $.get($tabButton.data("url"))
        .done(function (html) {
            $pane.html(html).data("loaded", true);
            Object.entries(TAB_TABLE_MAKERS).forEach(function ([tableId, makeTable]) {
                if ($pane.find(tableId).length) {
                    makeTable(tableId);
                }
            });
            ActivateYearDropdown($pane);
            ActivateBreakdownControls($pane);
            ActivateCustomerControls($pane);
            ActivateRevenueOverTime($pane);
        })
        .fail(function () {
            $pane.text("Could not load this tab. Please try again.");
        });
}

function MakeSupplierOrdersDataTable(tableId) {
    $(tableId).DataTable({
        pageLength: 20,
        lengthMenu: [ [10, 20, 25, 50, -1], [10, 20, 25, 50, "All"] ],
        // Column 1 is Order Date; most recent first.
        order: [[1, 'desc']]
    });
}

function MakeEmployeesDataTable(tableId) {
    $(tableId).DataTable({
        pageLength: 20,
        lengthMenu: [ [10, 20, 25, 50, -1], [10, 20, 25, 50, "All"] ],
        // Column 0 is Name (last, first); alphabetical.
        order: [[0, 'asc']]
    });
}

function MakeLeaderboardDataTable(tableId) {
    $(tableId).DataTable({
        // Nine employees fit on one page; no search box needed.
        paging: false,
        searching: false,
        info: false,
        // Column 0 is Rank; best first.
        order: [[0, 'asc']]
    });
}

function MakeProductRevenueDataTable(tableId) {
    $(tableId).DataTable({
        pageLength: 20,
        lengthMenu: [ [10, 20, 25, 50, -1], [10, 20, 25, 50, "All"] ],
        // Column 4 is Revenue; biggest earners first.
        order: [[4, 'desc']]
    });
}

// The dashboard has a year <select> whose change loads the monthly chart
// for that year into #dashboard-monthly (and the latest year loads at once).
function ActivateYearDropdown($pane) {
    const $select = $pane.find("#dashboard-year");
    if ($select.length === 0) {
        return;
    }
    const loadMonthly = function () {
        $.get($select.data("url"), { year: $select.val() })
            .done(function (html) { $("#dashboard-monthly").html(html); })
            .fail(function () { $("#dashboard-monthly").text("Could not load the monthly chart."); });
    };
    $select.on("change", loadMonthly);
    loadMonthly();
}

// The employee dashboard's bottom chart has a "Revenue by" <select> and a set of "Show Top" radio buttons
// (supplier, product, category) and 5 / 10 / All. A change to
// either reloads the chart into #dashboard-breakdown with both choices sent
// to the server. The page arrives with suppliers, Top 10 already drawn, so
// nothing loads until a selection changes.
function ActivateBreakdownControls($pane) {
    const $by = $pane.find("#breakdown-by");
    const $top = $pane.find("input[name='breakdown-top']");
    if ($by.length === 0) {
        return;
    }
    const loadBreakdown = function () {
        $.get($by.data("url"), { by: $by.val(), top: $top.filter(":checked").val() })
            .done(function (html) { $("#dashboard-breakdown").html(html); })
            .fail(function () { $("#dashboard-breakdown").text("Could not load the chart."); });
    };
    $by.on("change", loadBreakdown);
    $top.on("change", loadBreakdown);
}
// The employee dashboard's top-customers chart has "Show Top" radio buttons (5,
// 10, All). A change reloads the chart into #dashboard-customers, with the
// choice sent to the server as ?top=.
function ActivateCustomerControls($pane) {
    const $controls = $pane.find("#customer-controls");
    if ($controls.length === 0) {
        return;
    }
    const $top = $controls.find("input[name='customer-top']");
    $top.on("change", function () {
        $.get($controls.data("url"), { top: $top.filter(":checked").val() })
            .done(function (html) { $("#dashboard-customers").html(html); })
            .fail(function () { $("#dashboard-customers").text("Could not load the chart."); });
    });
}

// The employee dashboard's revenue-over-time card: "View by" radio buttons (Year,
// Month) and a year <select> whose job depends on the level. At Month, choosing a
// year reloads the chart into #dashboard-revenue for that year (or all years). At
// Year, every year is already on the chart, so the select is labeled "Details for"
// and choosing a year opens the Bootstrap modal for it, filled by one more $.get;
// the select then goes back to its first option.
function ActivateRevenueOverTime($pane) {
    const $controls = $pane.find("#revenue-controls");
    if ($controls.length === 0) {
        return;
    }
    const $level = $controls.find("input[name='revenue-level']");
    const $year = $controls.find("#revenue-year");
    const $yearLabel = $controls.find("label[for='revenue-year']");
    const $firstOption = $year.find("option[value='all']");
    const currentLevel = function () { return $level.filter(":checked").val(); };
    const loadRevenue = function () {
        $.get($controls.data("url"), { level: currentLevel(), year: $year.val() })
            .done(function (html) { $("#dashboard-revenue").html(html); })
            .fail(function () { $("#dashboard-revenue").text("Could not load the chart."); });
    };
    const showDetails = function (period) {
        const $modal = $("#revenue-modal");
        // A modal inside a tab pane can end up behind its backdrop; keep it a direct child of <body>.
        if ($modal.parent()[0] !== document.body) {
            $modal.appendTo("body");
        }
        const showModal = function (html) {
            $("#revenue-modal-content").html(html);
            // A chart drawn while the modal is hidden has no width to fit; redraw it once the modal is showing.
            $modal.one("shown.bs.modal", function () {
                $modal.find(".js-plotly-plot").each(function () { Plotly.Plots.resize(this); });
            });
            bootstrap.Modal.getOrCreateInstance($modal[0]).show();
        };
        $.get($controls.data("detail-url"), { period: period })
            .done(showModal)
            .fail(function () { showModal("<div class='modal-body'>Could not load the details.</div>"); });
    };
    $level.on("change", function () {
        const atYear = currentLevel() === "year";
        $yearLabel.text(atYear ? "Details for" : "Year");
        $firstOption.text(atYear ? "Choose a year" : "All years");
        $year.val("all");
        loadRevenue();
    });
    $year.on("change", function () {
        if (currentLevel() === "year") {
            if ($year.val() !== "all") {
                showDetails($year.val());
                $year.val("all");
            }
            return;
        }
        loadRevenue();
    });
}
// #endregion
