/**
 * Employees: the employee and leaderboard tables and the dashboard controls
 * that reload one chart. Loaded by base.html after DjangoTraders.js.
 */

/**
 * The employees list, alphabetical by name (column 0).
 * @param {string} tableId - selector for the table
 */
function MakeEmployeesDataTable(tableId) {
    $(tableId).DataTable({
        pageLength: 20,
        lengthMenu: [[10, 20, 25, 50, -1], [10, 20, 25, 50, "All"]],
        order: [[0, "asc"]]
    });
}

/**
 * The manager's leaderboard: best rank first (column 0), with no search
 * box, paging or "Showing X of Y" text, since the list is short.
 * @param {string} tableId - selector for the table
 */
function MakeLeaderboardDataTable(tableId) {
    $(tableId).DataTable({
        paging: false,
        searching: false,
        info: false,
        order: [[0, "asc"]]
    });
}

/**
 * Employee dashboard: the "Revenue by" dropdown (supplier, product, category),
 * the "Show Top" radio buttons (5, 10, All) and the "Chart" dropdown
 * (Bar, Column, and for a manager Pie) all reload the chart in #dashboard-breakdown. The first
 * chart arrives already drawn.
 * @param {jQuery} $pane - the tab pane that was just loaded
 */
function ActivateBreakdownControls($pane) {
    const $by = $pane.find("#breakdown-by");
    const $top = $pane.find("input[name='breakdown-top']");
    const $kind = $pane.find("#breakdown-kind");
    if ($by.length === 0) {
        return;
    }
    function loadBreakdown() {
        $.get($by.data("url"), { by: $by.val(), top: $top.filter(":checked").val(), kind: $kind.val() || "bar" })
            .done(function (html) { $("#dashboard-breakdown").html(html); })
            .fail(function () { $("#dashboard-breakdown").text("Could not load the chart."); });
    }
    $by.on("change", loadBreakdown);
    $top.on("change", loadBreakdown);
    $kind.on("change", loadBreakdown);
}

/**
 * Employee dashboard: the team comparison chart's "Compare" dropdown (Revenue,
 * Orders, Customers served) reloads the chart in #dashboard-team.
 * @param {jQuery} $pane - the tab pane that was just loaded
 */
function ActivateTeamComparison($pane) {
    const $controls = $pane.find("#team-controls");
    if ($controls.length === 0) {
        return;
    }
    const $measure = $controls.find("#team-measure");
    $measure.on("change", function () {
        $.get($controls.data("url"), { measure: $measure.val() })
            .done(function (html) { $("#dashboard-team").html(html); })
            .fail(function () { $("#dashboard-team").text("Could not load the chart."); });
    });
}

/**
 * Employee dashboard: the top-customers "Show Top" radio buttons and "Chart"
 * dropdown (Bar, Column, Pie) reload the chart in #dashboard-customers.
 * @param {jQuery} $pane - the tab pane that was just loaded
 */
function ActivateCustomerControls($pane) {
    const $controls = $pane.find("#customer-controls");
    if ($controls.length === 0) {
        return;
    }

    const $top = $controls.find("input[name='customer-top']");
    const $kind = $controls.find("#customer-kind");

    function loadCustomers() {
        $.get(
            $controls.data("url"),
            {
                top: $top.filter(":checked").val(),
                kind: $kind.val()
            }
        )
        .done(function (html) {
            $("#dashboard-customers").html(html);
        })
        .fail(function () {
            $("#dashboard-customers").text("Could not load the chart.");
        });
    }

    $top.on("change", loadCustomers);
    $kind.on("change", loadCustomers);
}

/**
 * Supplier dashboard: Revenue by Country. The "Show Top"
 * radio buttons (5, 10, All) and the "Metric" dropdown
 * (Revenue, Orders) reload the chart in #dashboard-country.
 * @param {jQuery} $pane - the tab pane that was just loaded
 */
function ActivateCountryControls($pane) {
    const $controls = $pane.find("#country-controls");
    if ($controls.length === 0) {
        return;
    }

    const $top = $controls.find("input[name='country-top']");
    const $metric = $controls.find("#country-metric");

    function loadCountry() {
        console.log("country control fired");

        $.get(
            $controls.data("url"),
            {
                top: $top.filter(":checked").val(),
                metric: $metric.val()
            }
        )
        .done(function (html) {
            $("#dashboard-country").html(html);
        })
        .fail(function () {
            $("#dashboard-country").text("Could not load the chart.");
        });
    }

    $top.on("change", loadCountry);
    $metric.on("change", loadCountry);
}