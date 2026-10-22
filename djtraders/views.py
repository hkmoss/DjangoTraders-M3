"""
View functions for the djtraders app.

Browsing (open to anyone): home, customer_list/product_list (search
handled by each model's own search() classmethod, djtraders/models.py),
customer_detail/product_detail, order_detail.

Two logins, each hand-rolled with plain sessions instead of Django's
own auth system: login_view/logout_view (employee, session key
"current_user") and customer_login_view/customer_logout_view (customer,
session key "customer_id"). Only one of the two can be logged in at a
time -- landing on either login page logs out whoever was there before.

Self-service access rule: a logged-in customer may only view/edit their
own record (or build/commit their own cart, below); an employee may act
on any customer's. The four helpers at the top of this file
(_own_customer_redirect, _customer_edit_denied, _order_access_denied,
_order_cart_denied) enforce that rule wherever it applies, instead of
repeating the same session checks in every view. The employee and
supplier pages have their own rules (_employee_access_denied,
_supplier_access_denied, next to those pages' views).

Customer edit/create: customer_edit renders a Django ModelForm
(CustomerEditForm, djtraders/forms.py) through django-crispy-forms.
customer_create reuses customer_edit's own template and form for a
Customer that doesn't exist yet. customer_delete marks a customer
inactive instead of deleting the row.

Ordering: a customer's in-progress order lives in
request.session["cart"] (a plain dict, no database row) until
order_commit writes it out as a real Order plus its OrderDetail rows,
inside one transaction. order_create/order_build/order_add_line/order_remove_line/
order_clear_cart/order_commit walk through that flow, open to the
cart's own customer or to any employee (_order_cart_denied); order_delete
cancels an already-placed order on the same day it was placed.
"""

from types import SimpleNamespace

from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone

from .forms import (
    CustomerEditForm,
    OrderCommitForm,
    OrderDetailForm,
    default_required_date,
    default_shipped_date,
)
from .models import Category, Customer, Employee, Order, OrderDetail, Product, Supplier


def _own_customer_redirect(request, customer_id):
    """
    If a logged-in customer (request.session["customer_id"]) is asking
    for a different customer_id than their own, returns a redirect to
    their own customer_detail page instead. Returns None (proceed
    normally) for an employee, an anonymous visitor, or a customer
    already looking at their own page.

    Used by customer_list (called with customer_id=None, so any
    logged-in customer counts as "asking for a different one") and
    customer_detail (called with the customer_id from the URL).
    """
    logged_in_customer_id = request.session.get("customer_id")
    if logged_in_customer_id and logged_in_customer_id != customer_id:
        return redirect("djtraders:customer_detail", customer_id=logged_in_customer_id)
    return None


def _order_access_denied(request, order):
    """
    True if the current session may NOT view/build/commit this order --
    neither an employee (who can act on any order) nor the order's own
    logged-in customer. Same shape as _customer_edit_denied below, just
    checked against order.customer_id instead of a customer_id URL
    parameter.

    order.customer can be None (a SET_NULL foreign key, djtraders/
    models.py) if the customer row it pointed to is ever gone -- treated
    as employee-only access, since there's no customer session left to
    match against.
    """
    logged_in_employee = request.session.get("current_user")
    if logged_in_employee:
        return False
    if order.customer_id is None:
        return True
    logged_in_customer_id = request.session.get("customer_id")
    return order.customer_id != logged_in_customer_id


def _customer_edit_denied(request, customer_id):
    """
    True if the current session may NOT edit this customer_id -- neither
    an employee (who can edit any customer) nor this customer's own
    logged-in session. Used by customer_edit to gate
    the whole view; unlike _own_customer_redirect above, an anonymous
    visitor (or a different customer) is denied outright here rather
    than redirected to their own page, since there's no "own edit page"
    to send them to instead.
    """
    logged_in_employee = request.session.get("current_user")
    logged_in_customer_id = request.session.get("customer_id")
    return not logged_in_employee and logged_in_customer_id != customer_id


def _order_cart_denied(request, customer_id):
    """
    Enhancement 7. True if the current session may NOT start/build/
    commit a cart for this customer_id -- neither a logged-in employee
    (who may act on behalf of any customer, the same relaxed rule
    _customer_edit_denied above already uses for editing) nor that
    customer's own logged-in session. Used by order_create/order_build/
    order_add_line/order_commit below in place of a bare "session
    customer_id must match" check.
    """
    if request.session.get("current_user"):
        return False
    return request.session.get("customer_id") != customer_id


def home(request):
    """
    Landing page for the djtraders app.

    Deliberately simple: no database access, just a template with links
    into the app's other pages -- no context dict either, since this
    page has no per-request data (compare to customer_list()/
    product_list() below, which each pass one).

    No login required to see this page -- Products stays a public
    catalog link for every visitor. current_employee/current_customer
    (djtraders/session_context.py) are already available in every
    template's context, so home.html decides on its own whether to show
    the Customers card or the Customer/Employee Login buttons instead.
    """
    return render(request, "djtraders/home.html")


def customer_list(request):
    """
    Display a list of customers, searchable by company name, contact
    name, contact title, city, and country.

    Uses the Customer model (djtraders/models.py) instead of raw SQL.
    The five search fields come from the search form's GET parameters
    (a plain string, "" when not submitted); Customer.search handles
    turning those into the actual filter, so this view doesn't build
    the queryset itself.

    The city dropdown is narrowed to the selected country (both submit
    the form on change, via customer_list.html's onchange), so choosing
    a country reloads the page with only that country's cities listed.

    A logged-in customer only ever needs their own record, not the full
    roster -- _own_customer_redirect sends them straight to their own
    customer_detail page instead. Employees (and anonymous visitors)
    still see the full list.
    """
    redirect_response = _own_customer_redirect(request, customer_id=None)
    if redirect_response:
        return redirect_response

    search_company_name = request.GET.get("company_name", "")
    search_contact_name = request.GET.get("contact_name", "")
    search_contact_title = request.GET.get("contact_title", "")
    search_city = request.GET.get("city", "")
    search_country = request.GET.get("country", "")

    # Distinct, non-blank city/country values on record, for the search
    # dropdowns -- not every customer has one, so blanks are excluded.
    # cities is narrowed to the selected country (if any), so picking a
    # country and reloading the page also narrows which cities show up.
    cities_queryset = Customer.objects.exclude(city__isnull=True).exclude(city__exact="")
    if search_country:
        cities_queryset = cities_queryset.filter(country=search_country)
    cities = cities_queryset.order_by("city").values_list("city", flat=True).distinct()

    countries = (
        Customer.objects.exclude(country__isnull=True)
        .exclude(country__exact="")
        .order_by("country")
        .values_list("country", flat=True)
        .distinct()
    )

    # Distinct, non-blank contact_title values on record, for its dropdown.
    contact_titles = (
        Customer.objects.exclude(contact_title__isnull=True)
        .exclude(contact_title__exact="")
        .order_by("contact_title")
        .values_list("contact_title", flat=True)
        .distinct()
    )

    # A previously selected city that isn't in the country just chosen
    # (e.g. switching country resets which cities are valid) would zero
    # out every result if still applied -- drop it instead of filtering
    # by a city/country combination nothing matches.
    if search_city and search_city not in cities:
        search_city = ""

    customers = Customer.search(
        company_name=search_company_name,
        contact_name=search_contact_name,
        contact_title=search_contact_title,
        city=search_city,
        country=search_country,
    )

    context = {
        "customers": customers,
        "cities": cities,
        "countries": countries,
        "contact_titles": contact_titles,
        "search_company_name": search_company_name,
        "search_contact_name": search_contact_name,
        "search_contact_title": search_contact_title,
        "search_city": search_city,
        "search_country": search_country,
    }
    return render(request, "djtraders/customers/customer_list.html", context)


def product_list(request):
    """
    Display a list of products, searchable by product name and category,
    with an option to include discontinued products.

    Same shape as customer_list above -- product_name/category/show_all
    come from the search form's GET parameters; Product.search
    (djtraders/models.py) handles turning those into the actual filter.
    """
    search_product_name = request.GET.get("product_name", "")
    search_category_id = request.GET.get("category", "")
    show_all = request.GET.get("show_all") == "on"

    products = Product.search(
        product_name=search_product_name,
        category_id=search_category_id,
        show_all=show_all,
    )

    # Every category on record, for the search dropdown.
    categories = Category.objects.order_by("category_name")

    context = {
        "products": products,
        "categories": categories,
        "search_product_name": search_product_name,
        "search_category_id": search_category_id,
        "show_all": show_all,
    }
    return render(request, "djtraders/products/product_list.html", context)


def product_detail(request, product_id):
    """
    Display a single product's full record: its own fields, plus every
    order line it's appeared on (product.orderdetail_set).

    Same shape as customer_detail below -- Units Sold/Total Revenue are
    read straight from Product's own units_sold/total_revenue properties
    (djtraders/models.py) rather than computed here.
    """
    product = get_object_or_404(Product, pk=product_id)

    # product.orderdetail_set is OrderDetail's reverse FK accessor --
    # every order line this product appears on. select_related("order")
    # fetches each line's Order via a JOIN, since the template needs
    # order.order_date/order_id for every row.
    order_lines = product.orderdetail_set.select_related("order").order_by("-order__order_date")
    context = {"product": product, "order_lines": order_lines}
    return render(request, "djtraders/products/product_detail.html", context)


# region [WHY] LOW_STOCK_THRESHOLD: one named number, not a literal
# product_search_json flags any product with fewer units than this as
# "low-stock". Kept as a module-level constant so the rule lives in
# exactly one place if the business ever changes it.
# endregion
LOW_STOCK_THRESHOLD = 5



# region [WHY] the customer page's three tabs are partial pages
# customer_detail (below) renders only the page shell -- the header and a
# Bootstrap tab control. Each tab's content comes from its own view here,
# fetched with an AJAX GET (DjangoTraders.js, LoadCustomerTab) and
# returned as an HTML fragment with no base.html around it, the same
# partial-template pattern as order_add_card. customer_id comes from the
# URL; a logged-in customer only ever gets their own tabs (a different
# customer_id gets a 403), while an employee or anonymous visitor may
# view any customer's, matching customer_detail's own rule.
# endregion
def _customer_tab_denied(request, customer_id):
    """True when a logged-in customer asks for someone else's tab."""
    logged_in_customer_id = request.session.get("customer_id")
    return bool(logged_in_customer_id) and logged_in_customer_id != customer_id


def customer_dashboard(request, customer_id):
    """
    Dashboard tab: the customer's revenue by year as a Plotly chart
    (Customer.annual_orders_plot), or a message when there are no placed
    orders to chart.
    """
    if _customer_tab_denied(request, customer_id):
        return HttpResponse(status=403)
    customer = get_object_or_404(Customer, pk=customer_id)
    context = {
        "customer": customer,
        "stats": customer.dashboard_stats(),
        "annual_plot": customer.annual_orders_plot(),
        "order_years": customer.order_years(),
    }
    return render(request, "djtraders/customers/_customer_dashboard.html", context)


def customer_monthly_chart(request, customer_id):
    """
    The dashboard's year dropdown: Customer.orders_placed_plot for ?year=,
    as just the chart HTML that fills #dashboard-monthly. The year comes
    from the browser, so it is checked before use: 403 for another
    customer's dashboard, 400 for anything that is not one of this
    customer's order years.
    """
    if _customer_tab_denied(request, customer_id):
        return HttpResponse(status=403)
    customer = get_object_or_404(Customer, pk=customer_id)
    try:
        year = int(request.GET.get("year", ""))
    except ValueError:
        return HttpResponse("Choose a valid year.", status=400)
    if year not in customer.order_years():
        return HttpResponse("Choose a valid year.", status=400)
    plot = customer.orders_placed_plot(year)
    return HttpResponse(plot or "<p>No orders on record.</p>")


def customer_info(request, customer_id):
    """
    Customer Info tab: the contact details and the Order Summary card
    (with its Start New Order button).
    """
    if _customer_tab_denied(request, customer_id):
        return HttpResponse(status=403)
    customer = get_object_or_404(Customer, pk=customer_id)

    # customer.order_set is Order's reverse FK accessor -- every order
    # this customer has placed. order_date__isnull=False excludes a cart
    # that was started (order_create below) but never committed
    # (order_commit below) -- order_date doubles as the "placed" flag.
    # Each order's own order_total property (djtraders/models.py) sums
    # its line items, so this view just adds those totals together
    # rather than computing revenue itself.
    orders = customer.order_set.filter(order_date__isnull=False)
    total_quantity = sum(
        line.quantity for order in orders for line in order.orderdetail_set.all()
    )
    total_revenue = sum(order.order_total for order in orders)

    # "Start New Order" is shown to the logged-in customer viewing their
    # own page, or an employee, same relaxed rule as Edit (Enhancement 7,
    # _order_cart_denied above).
    can_start_order = not _order_cart_denied(request, customer.customer_id)

    context = {
        "customer": customer,
        "total_quantity": total_quantity,
        "total_revenue": total_revenue,
        "can_start_order": can_start_order,
    }
    return render(request, "djtraders/customers/_customer_info.html", context)


def customer_orders(request, customer_id):
    """Order History tab: the customer's placed orders, newest first, in a DataTable."""
    if _customer_tab_denied(request, customer_id):
        return HttpResponse(status=403)
    customer = get_object_or_404(Customer, pk=customer_id)
    orders = customer.order_set.filter(order_date__isnull=False).order_by("-order_date")
    return render(request, "djtraders/customers/_customer_orders.html", {
        "customer": customer,
        "orders": orders,
    })


def product_search_json(request):
    """
    JSON endpoint behind order_build.html's Product autocomplete. jQuery UI
    sends the typed text as the "term" GET parameter; this returns up to
    10 matching products as a list of {label, value, id, ...} dicts --
    label is what the dropdown shows, value is written into the visible
    text box on selection, id is the real Product primary key the
    select handler copies into the hidden id_product field.

    Only non-discontinued products are ever returned (discontinued is a
    plain 1/0 column, so the filter is discontinued=0), and an optional
    "category" parameter narrows the match the same way order_build's own
    Filter by Category dropdown does. units_in_stock/low_stock ride along
    so the page can draw a "low-stock" badge without a second request;
    a NULL units_in_stock means "stock isn't tracked," so it is never
    flagged.
    """
    term = request.GET.get("term", "").strip()
    category_id = request.GET.get("category", "")

    products = Product.objects.filter(discontinued=0, product_name__icontains=term)
    if category_id:
        products = products.filter(category_id=category_id)

    results = []
    for product in products.order_by("product_name")[:10]:
        price = product.unit_price or 0
        results.append(
            {
                "label": f"{product.product_name} (${price:,.2f})",
                "value": product.product_name,
                "id": product.product_id,
                "units_in_stock": product.units_in_stock,
                "low_stock": (
                    product.units_in_stock is not None
                    and product.units_in_stock < LOW_STOCK_THRESHOLD
                ),
            }
        )
    return JsonResponse(results, safe=False)


def customer_detail(request, customer_id):
    """
    Display a single customer's page: a header plus a Dashboard / Customer Info / Order History tab control.

    customer_id comes from the URL itself (see djtraders/urls.py's
    customer_detail_url, which captures it with a path converter) rather
    than from a query string or form -- Django hands it to this view as
    a plain function argument with the same name used in the URL pattern.

    A logged-in customer can only view their own record --
    _own_customer_redirect sends them back to their own page if the URL
    asks for a different customer_id. Employees (and anonymous visitors)
    can view any customer's page.
    """
    redirect_response = _own_customer_redirect(request, customer_id)
    if redirect_response:
        return redirect_response

    # get_object_or_404 is shorthand for .objects.get(pk=...), except it
    # raises Http404 instead of letting DoesNotExist crash the request.
    customer = get_object_or_404(Customer, pk=customer_id)

    # Only the page shell is built here. Each tab's content comes from
    # customer_dashboard, customer_info, or customer_orders above,
    # loaded by AJAX once the page is open.
    return render(request, "djtraders/customers/customer_detail.html", {"customer": customer})


def customer_edit(request, customer_id):
    """
    Edits a customer's own record with a Django Form: CustomerEditForm
    (djtraders/forms.py) declares the fields/widgets once as a class,
    request.POST is bound to it and checked with form.is_valid() instead
    of hand-validating each field, and form.save() writes every
    validated field onto the Customer instance at once. company_name
    being required is enforced automatically (a ModelForm reads that off
    the model field itself).

    customer_edit.html renders the form with django-crispy-forms'
    {% crispy %} tag instead of hand-written <input> tags.

    Available to an employee editing any customer, or a logged-in
    customer editing their own record only (_customer_edit_denied,
    above).
    """
    customer = get_object_or_404(Customer, pk=customer_id)

    if _customer_edit_denied(request, customer_id):
        return redirect("djtraders:customer_detail", customer_id=customer_id)

    if request.method == "POST":
        form = CustomerEditForm(request.POST, instance=customer)
        if form.is_valid():
            form.save()
            return redirect("djtraders:customer_detail", customer_id=customer.customer_id)
    else:
        form = CustomerEditForm(instance=customer)

    # confirm_delete=1 (customer_list.html's Delete icon) shows an
    # in-page "are you sure?" prompt instead of the edit form -- see
    # customer_edit.html. Its own Confirm button is a real POST to
    # customer_delete, not a browser confirm() popup (see CLAUDE.md).
    confirm_delete = request.GET.get("confirm_delete") == "1"

    context = {"customer": customer, "form": form, "confirm_delete": confirm_delete}
    return render(request, "djtraders/customers/customer_edit.html", context)


def customer_create(request):
    """
    "Create Empty and Edit": renders the exact same page as
    customer_edit above -- same template, same CustomerEditForm, same
    field grid -- for a Customer that doesn't exist in the database yet,
    and writes it to the database exactly once, only when Save is
    actually clicked. Employee-only, same as customer_delete; a customer
    edits their own existing record but never creates a new one.

    GET builds a blank, unsaved Customer() and hands it to
    CustomerEditForm/customer_edit.html with new_customer=True in the
    context, so that template can tell "New Customer" from "Edit
    <existing customer>" and point its own Cancel link at customer_list
    instead of a customer_detail page that doesn't exist yet. Clicking
    Cancel from here is a plain link, not a form submission -- nothing
    was ever saved, so there's nothing to undo or delete.

    POST validates the submitted fields through that same form -- no
    different from customer_edit's own POST handling above, since
    customer_id was never one of CustomerEditForm's fields to begin
    with (djtraders/forms.py). Only on success does this view do the two
    things customer_edit's POST never has to: ask
    Customer.generate_customer_id (djtraders/models.py) to invent a new,
    unique customer_id from the now-validated company_name -- a customer
    never picks or types their own ID -- and redirect to customer_list
    rather than customer_detail, so the employee who just created this
    customer sees it appear in the roster right away.
    """
    if not request.session.get("current_user"):
        return redirect("djtraders:customer_list")

    if request.method == "POST":
        # instance=Customer() -- an unsaved, blank row -- so is_valid()
        # runs the exact same field checks customer_edit's POST runs
        # against an existing customer.
        form = CustomerEditForm(request.POST, instance=Customer())
        if form.is_valid():
            # Only generated once everything else has already passed
            # validation -- generate_customer_id needs a real,
            # validated company_name to build a sensible ID from.
            form.instance.customer_id = Customer.generate_customer_id(
                form.cleaned_data["company_name"]
            )
            form.save()
            return redirect("djtraders:customer_list")
    else:
        form = CustomerEditForm(instance=Customer())

    context = {"customer": form.instance, "form": form, "new_customer": True}
    return render(request, "djtraders/customers/customer_edit.html", context)


def customer_delete(request, customer_id):
    """
    Marks a customer inactive (sets inactive_date to today) instead of
    actually deleting the row -- reversible, and keeps their order
    history intact. Employee-only action, available from the Actions
    column on customer_list.html; POST-only, since it changes data.
    """
    if not request.session.get("current_user"):
        return redirect("djtraders:customer_list")

    if request.method == "POST":
        customer = get_object_or_404(Customer, pk=customer_id)
        customer.inactive_date = timezone.now().date()
        customer.save()

    return redirect("djtraders:customer_list")


def order_detail(request, order_id):
    """
    Display a single order: who placed it, who processed/shipped it, and
    every product line item on it.

    This view exists mainly to illustrate model traversal end to end.
    Starting from one Order: order.customer and order.employee/
    order.ship_via are forward ForeignKeys (Order holds those FK
    columns), while the order's line items are a reverse relationship
    (order.orderdetail_set -- OrderDetail holds the FK to Order, not the
    other way around), and each of those lines reaches its own Product
    via yet another forward FK (order_detail.product). Reached from
    customer_detail.html's Orders table.

    The page itself has no access check -- an order's detail page is
    viewable by anyone, the same as a product or employee's detail page.
    can_cancel_order (below) is the one thing on this page that IS
    gated, since Cancel Order (order_delete below) is a real,
    destructive, self-service action.
    """
    order = get_object_or_404(Order, pk=order_id)

    # order.orderdetail_set is Django's default reverse accessor name for
    # OrderDetail's FK to Order. select_related("product__supplier")
    # fetches each line's Product AND that Product's Supplier via one
    # JOIN in this same query, instead of a separate query per line --
    # worth it since the template touches both every row. Each line's
    # own line_total property (djtraders/models.py) is used directly in
    # the template, no annotation needed here.
    order_lines = order.orderdetail_set.select_related("product__supplier")

    # Cancel Order (order_delete below) is only shown for a placed order
    # (order_date set) from today, to the order's own customer or an
    # employee -- computed once here, not left for the template to
    # reason about, since order_delete itself re-checks both halves of
    # this same condition server-side regardless.
    can_cancel_order = order.order_date == timezone.now().date() and not _order_access_denied(
        request, order
    )

    context = {
        "order": order,
        "order_lines": order_lines,
        "can_cancel_order": can_cancel_order,
    }
    return render(request, "djtraders/orders/order_detail.html", context)


def login_view(request):
    """
    Employee login: pick a name from a dropdown instead of typing one,
    and enter the 4-digit year of that employee's own birth_date as the
    password (see Employee.authenticate, djtraders/models.py).

    On success, employee_id goes into request.session under
    "current_user" -- Django's session framework stores that in a
    per-visitor cookie-backed session, so it's remembered across
    requests without Django's own auth system (django.contrib.auth)
    being involved. The employee is then sent to their own
    employee_detail page (self-service), not straight into the full
    customer_list.

    Only one employee or customer can be logged in at a time, not both
    at once -- landing on this page (clicking "Employee Login") logs out
    whoever was previously logged in, employee or customer, before the
    form is even shown.
    """
    request.session.pop("current_user", None)
    request.session.pop("customer_id", None)
    request.session.pop("supplier_id", None)

    error = None
    if request.method == "POST":
        employee_id = request.POST.get("employee_id", "")
        password = request.POST.get("password", "")
        employee = Employee.authenticate(employee_id, password)
        if employee is not None:
            request.session["current_user"] = employee.employee_id
            return redirect("djtraders:employee_detail", employee_id=employee.employee_id)
        error = "Incorrect employee/password combination."

    employees = Employee.objects.order_by("last_name", "first_name")
    context = {"employees": employees, "error": error}
    return render(request, "djtraders/login.html", context)


def logout_view(request):
    """
    Clears "current_user" from the session, logging the employee out,
    then sends them back to the app home page -- home always renders
    regardless of login state (see its own docstring), so this just
    lands them back on the page with the login buttons showing again.
    """
    request.session.pop("current_user", None)
    return redirect("djtraders:home")


def customer_login_view(request):
    """
    Customer login: pick a company name from a dropdown instead of
    typing a customer_id (see Customer.authenticate, djtraders/models.py),
    same reasoning as the employee login's dropdown -- easier than
    remembering a 5-character ID.

    On success, customer_id goes into request.session under
    "customer_id" -- a separate session key from the employee login's
    "current_user". The customer is then sent straight to their own
    customer_detail page, not the full customer list an employee sees
    after logging in.

    Same one-at-a-time login rule as login_view above -- landing on this
    page logs out whoever was previously logged in first.
    """
    request.session.pop("current_user", None)
    request.session.pop("customer_id", None)
    request.session.pop("supplier_id", None)

    error = None
    if request.method == "POST":
        customer_id = request.POST.get("customer_id", "")
        password = request.POST.get("password", "")
        customer = Customer.authenticate(customer_id, password)
        if customer is not None:
            request.session["customer_id"] = customer.customer_id
            return redirect("djtraders:customer_detail", customer_id=customer.customer_id)
        error = "Incorrect customer/password combination."

    customers = Customer.objects.order_by("company_name")
    context = {"customers": customers, "error": error}
    return render(request, "djtraders/customers/customer_login.html", context)


def customer_logout_view(request):
    """
    Clears "customer_id" from the session, logging the customer out,
    then sends them back to the app home page -- same as logout_view
    above, home always renders regardless of login state, landing them
    back on the page with the login buttons showing again.
    """
    request.session.pop("customer_id", None)
    return redirect("djtraders:home")


def supplier_login_view(request):
    """
    Supplier login: pick a company name from a dropdown and enter the
    shared password (Supplier.authenticate, djtraders/models.py), the
    same shape as customer_login_view. On success, supplier_id goes into
    request.session under "supplier_id" -- a third session key beside
    "current_user" (employee) and "customer_id" -- and the supplier is
    sent to their own supplier_detail page.

    Same one-at-a-time rule as the other two logins: landing here logs
    out whoever was logged in first.
    """
    request.session.pop("current_user", None)
    request.session.pop("customer_id", None)
    request.session.pop("supplier_id", None)

    error = None
    if request.method == "POST":
        supplier = Supplier.authenticate(
            request.POST.get("supplier_id", ""), request.POST.get("password", "")
        )
        if supplier is not None:
            request.session["supplier_id"] = supplier.supplier_id
            return redirect("djtraders:supplier_detail", supplier_id=supplier.supplier_id)
        error = "Incorrect supplier/password combination."

    suppliers = Supplier.objects.order_by("company_name")
    return render(request, "djtraders/suppliers/supplier_login.html", {"suppliers": suppliers, "error": error})


def supplier_logout_view(request):
    """Clears "supplier_id" from the session and sends the supplier back to the home page."""
    request.session.pop("supplier_id", None)
    return redirect("djtraders:home")


# region [WHY] supplier pages are private to the supplier (and employees)
# A customer page is open to anonymous visitors, but a supplier page
# shows what each product earns, so it is not. Allowed: the logged-in
# supplier asking for their own supplier_id, or any logged-in employee.
# Everyone else is turned away -- a redirect to the supplier login for
# the page itself, a 403 for the AJAX tabs.
# endregion
def _supplier_access_denied(request, supplier_id):
    """True unless this visitor is that supplier or an employee."""
    if request.session.get("current_user"):
        return False
    return request.session.get("supplier_id") != supplier_id


def supplier_detail(request, supplier_id):
    """
    Supplier page shell: header plus a Bootstrap tab control (Info, Order
    History, Product Revenue). Each tab is a partial template loaded by
    AJAX (supplier_info, supplier_orders, supplier_products below), the
    same pattern as the customer page.
    """
    logged_in_supplier_id = request.session.get("supplier_id")
    if logged_in_supplier_id and logged_in_supplier_id != supplier_id:
        return redirect("djtraders:supplier_detail", supplier_id=logged_in_supplier_id)
    if _supplier_access_denied(request, supplier_id):
        return redirect("djtraders:supplier_login")
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    return render(request, "djtraders/suppliers/supplier_detail.html", {"supplier": supplier})


def _supplier_tab(request, supplier_id, template_name, build_context):
    """Shared body of the supplier tab views: access check, then render the partial."""
    if _supplier_access_denied(request, supplier_id):
        return HttpResponse(status=403)
    supplier = get_object_or_404(Supplier, pk=supplier_id)
    context = {"supplier": supplier}
    context.update(build_context(supplier))
    return render(request, template_name, context)


def supplier_info(request, supplier_id):
    """Info tab: contact details and headline numbers."""
    return _supplier_tab(request, supplier_id, "djtraders/suppliers/_supplier_info.html",
                         lambda supplier: {"summary": supplier.summary()})


def supplier_orders(request, supplier_id):
    """Order History tab: placed orders that include this supplier's products."""
    return _supplier_tab(request, supplier_id, "djtraders/suppliers/_supplier_orders.html",
                         lambda supplier: {"orders": supplier.order_history()})


def supplier_products(request, supplier_id):
    """Product Revenue tab: a table of units and revenue per product."""
    return _supplier_tab(request, supplier_id, "djtraders/suppliers/_supplier_products.html",
                         lambda supplier: {"rows": supplier.product_revenue()})


# region [WHY] who may see which employee page
# An employee's page shows their sales numbers, so it needs a logged-in
# employee. A regular employee sees only their own page; a manager (an
# employee other employees report to, Employee.is_manager) may open any
# employee's page and sees the Employees tab. Everyone else -- anonymous
# visitors, customers, suppliers -- is turned away.
# endregion
def _employee_access_denied(request, employee_id):
    """True unless a logged-in employee is viewing their own page, or is a manager."""
    viewer_id = request.session.get("current_user")
    if not viewer_id:
        return True
    if viewer_id == employee_id:
        return False
    viewer = Employee.objects.filter(pk=viewer_id).first()
    return viewer is None or not viewer.is_manager


def employee_detail(request, employee_id):
    """
    Employee page shell: header (with quick links into Customers and
    Products) plus a Bootstrap tab control -- Dashboard, Employee Info,
    and, for a manager, Employees. Each tab's content is a partial
    template loaded by AJAX (employee_dashboard, employee_info,
    employee_list below), the same pattern as the customer and supplier
    pages. login_view sends an employee here after a successful login.

    A visitor who is not logged in as an employee goes to the employee
    login; an employee asking for someone else's page goes back to their
    own, unless they are a manager.
    """
    viewer_id = request.session.get("current_user")
    if not viewer_id:
        return redirect("djtraders:login")
    if _employee_access_denied(request, employee_id):
        return redirect("djtraders:employee_detail", employee_id=viewer_id)

    employee = get_object_or_404(Employee, pk=employee_id)
    return render(request, "djtraders/employees/employee_detail.html", {"employee": employee})


def employee_dashboard(request, employee_id):
    """
    Dashboard tab: rank tiles and a "vs. the team" chart and table (plus,
    for a manager, a leaderboard naming every employee), then revenue over time (by year or by month, with a Details modal per period) and revenue by customer for the orders
    this employee handled, plus a revenue breakdown by supplier, product or
    category. The breakdown depends on who is viewing: a manager sees every
    group's revenue, anyone else sees their own share of each group's revenue
    (Employee.revenue_breakdown_plot).
    """
    if _employee_access_denied(request, employee_id):
        return HttpResponse(status=403)
    employee = get_object_or_404(Employee, pk=employee_id)
    viewer = Employee.objects.get(pk=request.session["current_user"])
    you_label = "You" if viewer.employee_id == employee.employee_id else employee.first_name
    revenue_plot = employee.revenue_over_time()
    return render(request, "djtraders/employees/_employee_dashboard.html", {
        "employee": employee,
        "viewer_is_manager": viewer.is_manager,
        "performance": employee.performance(),
        "you_label": you_label,
        "comparison": employee.team_comparison(),
        "comparison_plot": employee.team_comparison_plot(you_label),
        "leaderboard": employee.leaderboard() if viewer.is_manager else [],
        "revenue_plot": revenue_plot,
        "revenue_years": employee.revenue_years(),
        "customer_plot": employee.customer_revenue_plot(top=10),
        "breakdown_plot": employee.revenue_breakdown_plot("supplier", all_orders=viewer.is_manager, top=10),
    })


def employee_customer_chart(request, employee_id):
    """
    The dashboard's top-customers chart control: the chart for ?top= (5, 10 or
    all), as just the chart <div>. The value is checked against a fixed list
    before use. It covers this employee's own customers, as in employee_dashboard.
    """
    if _employee_access_denied(request, employee_id):
        return HttpResponse(status=403)
    employee = get_object_or_404(Employee, pk=employee_id)
    top = request.GET.get("top", "10")
    if top not in ("5", "10", "all"):
        return HttpResponse("Choose a valid top.", status=400)
    plot = employee.customer_revenue_plot(top=None if top == "all" else int(top))
    return HttpResponse(plot or "<p>No orders on record.</p>")


def employee_breakdown_chart(request, employee_id):
    """
    The dashboard's bottom chart controls: the revenue chart for ?by=
    (supplier, product or category) and ?top= (5, 10 or all), as just the
    chart <div>. Both values are checked against a fixed list before use.
    Who is asking decides what the chart shows, exactly as in
    employee_dashboard.
    """
    if _employee_access_denied(request, employee_id):
        return HttpResponse(status=403)
    employee = get_object_or_404(Employee, pk=employee_id)
    viewer = Employee.objects.get(pk=request.session["current_user"])
    by = request.GET.get("by", "supplier")
    top = request.GET.get("top", "10")
    if by not in Employee.BREAKDOWNS or top not in ("5", "10", "all"):
        return HttpResponse("Choose a valid breakdown and top.", status=400)
    plot = employee.revenue_breakdown_plot(
        by, all_orders=viewer.is_manager, top=None if top == "all" else int(top)
    )
    return HttpResponse(plot or "<p>No orders on record.</p>")


def employee_revenue_chart(request, employee_id):
    """
    The dashboard's revenue-over-time controls: the chart and the table of periods
    for ?level= ("year" or "month") and ?year= ("all" or one of the years this
    employee has orders in), as just the fragment that fills #dashboard-revenue.
    Both values are checked against what is allowed before use, and the year is
    ignored at the year level.
    """
    if _employee_access_denied(request, employee_id):
        return HttpResponse(status=403)
    employee = get_object_or_404(Employee, pk=employee_id)
    level = request.GET.get("level", "year")
    year = request.GET.get("year", "all")
    years = employee.revenue_years()
    if level not in ("year", "month") or (year != "all" and not (year.isdigit() and int(year) in years)):
        return HttpResponse("Choose a valid level and year.", status=400)
    plot = employee.revenue_over_time(level, None if year == "all" else int(year))
    return render(request, "djtraders/employees/_employee_revenue_chart.html", {
        "revenue_plot": plot,
    })


def employee_period_detail(request, employee_id):
    """
    The Details modal for one period of the revenue-over-time table: ?period= is
    "1997" or "1997-03", checked against the years this employee has orders in
    (and months 01 to 12) before use. Returns the modal's contents only.
    """
    if _employee_access_denied(request, employee_id):
        return HttpResponse(status=403)
    employee = get_object_or_404(Employee, pk=employee_id)
    period = request.GET.get("period", "")
    year, _, month = period.partition("-")
    valid_year = year.isdigit() and len(year) == 4 and int(year) in employee.revenue_years()
    valid_month = month == "" or (month.isdigit() and len(month) == 2 and 1 <= int(month) <= 12)
    if not (valid_year and valid_month):
        return HttpResponse("Choose a valid period.", status=400)
    return render(request, "djtraders/employees/_employee_period_detail.html", {
        "detail": employee.period_detail(period),
    })


def employee_info(request, employee_id):
    """Employee Info tab: title, manager, hire date, phone, address."""
    if _employee_access_denied(request, employee_id):
        return HttpResponse(status=403)
    employee = get_object_or_404(Employee, pk=employee_id)
    return render(request, "djtraders/employees/_employee_info.html", {"employee": employee})


def employee_list(request, employee_id):
    """
    Employees tab: every employee, with a link to each one's page.
    Managers only -- the URL's employee_id must be a page this viewer may
    open, and the viewer must be a manager.
    """
    if _employee_access_denied(request, employee_id):
        return HttpResponse(status=403)
    viewer = Employee.objects.filter(pk=request.session.get("current_user")).first()
    if viewer is None or not viewer.is_manager:
        return HttpResponse(status=403)
    employees = Employee.objects.select_related("reports_to").order_by("last_name", "first_name")
    return render(request, "djtraders/employees/_employee_list.html", {"employees": employees})


def _cart_lines(cart):
    """
    Turns a session cart's "lines" dict (no database row backing any of
    it) into a list of lightweight, OrderDetail-shaped objects:
    .product, .unit_price, .quantity, .discount, .discount_percent,
    .line_total. A plain types.SimpleNamespace, not a real model
    instance -- there might never be a real OrderDetail row, if this
    cart is abandoned -- but shaped so _order_line_row.html and the
    running total can be built exactly the same way as when these are
    real rows, with no template changes needed either way.

    Enhancement 3. Each line in cart["lines"] is itself a
    {"quantity": ..., "discount": ...} dict now, discount stored as the
    same 0.0-1.0 fraction OrderDetail.discount uses (order_add_line
    converts the form's percentage input to this fraction once, so nothing
    downstream -- this function, order_commit's bulk_create -- has to
    convert it again). .discount_percent is the one field on this
    namespace that exists purely for display (_order_line_row.html), so
    the template never has to redo that fraction-to-percent math itself.

    unit_price is each product's *current* price, looked up fresh every
    time this runs (including at commit), not frozen at the moment a
    line was added -- there's nothing to freeze it onto before an Order
    row exists.

    A cart line whose product_id no longer resolves to a real product
    (e.g. deleted) is silently skipped rather than raising -- nothing
    here enforces referential integrity the way a real ForeignKey would.
    """
    product_ids = [int(product_id) for product_id in cart.get("lines", {})]
    products_by_id = Product.objects.in_bulk(product_ids)

    lines = []
    for product_id_str, line_data in cart.get("lines", {}).items():
        product = products_by_id.get(int(product_id_str))
        if product is None:
            continue
        quantity = line_data["quantity"]
        discount = line_data["discount"]
        unit_price = product.unit_price or 0.0
        lines.append(
            SimpleNamespace(
                product=product,
                unit_price=unit_price,
                quantity=quantity,
                discount=discount,
                discount_percent=discount * 100,
                line_total=unit_price * quantity * (1 - discount),
            )
        )
    return lines


def order_create(request, customer_id):
    """
    Starts (or resumes) this customer's shopping cart in
    request.session["cart"] -- no database row at all until commit
    (order_commit below). POST-only (customer_detail.html's own "Start
    New Order" button is a real <form method="post">, not a link, since
    this writes session data). Available to the logged-in customer
    starting an order for themselves, or an employee starting one on
    that customer's behalf (Enhancement 7, _order_cart_denied above;
    see customer_detail's own can_start_order flag too).

    request.session["cart"] is only reused if it already belongs to this
    same customer_id -- a different customer logging in on the same
    browser never sees someone else's leftover cart; a mismatch is
    treated as no cart at all, and a fresh, empty one is started. At
    most one open cart per browser session -- clicking "Start New Order"
    again just returns to the same cart already open, instead of
    starting a second one.

    Redirects straight into order_build to start adding line items.
    """
    if _order_cart_denied(request, customer_id):
        return redirect("djtraders:customer_detail", customer_id=customer_id)

    if request.method != "POST":
        return redirect("djtraders:customer_detail", customer_id=customer_id)

    cart = request.session.get("cart")
    if not cart or cart.get("customer_id") != customer_id:
        request.session["cart"] = {"customer_id": customer_id, "lines": {}}

    return redirect("djtraders:order_build", customer_id=customer_id)


def _add_to_cart_context(request, customer, category_id=""):
    """
    Everything the Add to Cart card (_order_add_card.html) needs to
    render, as one dict -- shared by order_build and order_commit's
    error re-render (which include the card in the full page), and by
    order_add_line and order_add_card (which each render the card alone).
    category_id narrows the Product search the way product_list.html's
    own Category filter narrows its table; "" means every
    non-discontinued product.

    product_stock is {product_id: units_in_stock} for the products that
    category offers, embedded by the card's json_script tag so
    AddOrderLineItem (DjangoTraders.js) can block an obviously-too-large
    quantity before it's submitted. A courtesy check only --
    OrderDetailForm's own clean() (djtraders/forms.py) is the real,
    authoritative one.
    """
    detail_form = OrderDetailForm(
        category_id=category_id,
        employee_initiated=bool(request.session.get("current_user")),
    )
    return {
        "customer": customer,
        "detail_form": detail_form,
        "categories": Category.objects.order_by("category_name"),
        "search_category_id": category_id,
        "product_stock": dict(
            detail_form.fields["product"].queryset.values_list("product_id", "units_in_stock")
        ),
    }


def order_add_card(request, customer_id):
    """
    AJAX endpoint (DjangoTraders.js) behind the Add to Cart card's Filter
    by Category dropdown. Returns just the card's HTML
    (_order_add_card.html), rendered for the "category" GET parameter --
    the page swaps it in for the current card, so the Product search and
    the stock data both refresh for that category without reloading the
    page. An empty category means every non-discontinued product.

    Same access rule as the rest of the cart (_order_cart_denied). Reads
    nothing from the cart and writes nothing -- it only renders the card.
    """
    if _order_cart_denied(request, customer_id):
        return HttpResponse("Not allowed.", status=403)

    customer = get_object_or_404(Customer, pk=customer_id)
    return render(
        request,
        "djtraders/orders/_order_add_card.html",
        _add_to_cart_context(request, customer, category_id=request.GET.get("category", "")),
    )


def order_build(request, customer_id):
    """
    The shopping cart page. There is no Order row and no order_id at all
    until commit (order_commit below) -- everything here comes from
    request.session["cart"] (a plain {"customer_id": ...,
    "lines": {product_id: quantity}} dict, see _cart_lines above) and a
    fresh Customer/Product lookup, never a database Order. The Place
    Order card's Ship To and Shipping Address sections are prefilled with
    the customer's own on-file name/address, read live off Customer every
    time this renders (order_commit copies that same, current address
    onto the real Order's ship_* columns at commit). OrderCommitForm's employee field
    is required -- no order commits without one picked, a business rule,
    not a database one (see that form's own docstring, djtraders/forms.py).

    Access follows the same relaxed rule order_create uses
    (_order_cart_denied, Enhancement 7): the customer's own logged-in
    session, or any logged-in employee building a cart on that
    customer's behalf. A cart missing or belonging to a different
    customer_id is treated as empty and (re)started here, same as
    order_create -- this view alone is enough to reach a working cart
    page, even without ever visiting order_create first (e.g. a
    bookmarked or re-typed URL).
    """
    if _order_cart_denied(request, customer_id):
        return redirect("djtraders:customer_detail", customer_id=customer_id)

    customer = get_object_or_404(Customer, pk=customer_id)

    cart = request.session.get("cart")
    if not cart or cart.get("customer_id") != customer_id:
        cart = {"customer_id": customer_id, "lines": {}}
        request.session["cart"] = cart

    cart_lines = _cart_lines(cart)
    cart_total = sum(line.line_total for line in cart_lines)
    # required_date/shipped_date default to a business-convention guess
    # (order_date, today at commit, plus two weeks / one week) but stay
    # real, editable fields on this form -- see OrderCommitForm/
    # default_required_date/default_shipped_date (djtraders/forms.py).
    # Enhancement 6: ship_* fields default to this customer's own
    # on-file address (also editable, same "starting guess" shape).
    commit_form = OrderCommitForm(
        initial={
            "required_date": default_required_date(),
            "shipped_date": default_shipped_date(),
            "ship_name": customer.company_name,
            "ship_address": customer.address,
            "ship_city": customer.city,
            "ship_region": customer.region,
            "ship_postal_code": customer.postal_code,
            "ship_country": customer.country,
        }
    )

    context = {
        "customer": customer,
        "cart_lines": cart_lines,
        "cart_total": cart_total,
        "commit_form": commit_form,
        **_add_to_cart_context(request, customer),
    }
    return render(request, "djtraders/orders/order_build.html", context)


def order_add_line(request, customer_id):
    """
    AJAX endpoint (order_build.html's Add Line Item form,
    DjangoTraders.js) -- adds a product/quantity line to
    request.session["cart"]["lines"], or increases an already-existing
    line's quantity instead of a second entry for the same product_id (a
    plain dict key, doing by hand what a real OrderDetail row's own
    composite primary key would guarantee for free -- there is no
    database backstop here at all until commit).

    unit_price is never asked for on the form -- _cart_lines (above)
    prices every line fresh, including this one, whenever it's next
    read, right up through commit. Returns JSON, not a redirect/render
    -- this is the one genuinely AJAX-driven workflow in the app, so
    the page itself never reloads while lines are being added.

    On success the JSON carries two rendered partials plus the new
    total: row_html (the line's table row, _order_line_row.html) and
    card_html (a fresh, empty Add to Cart card, _order_add_card.html).
    Validation failures return only error messages -- no card_html -- so
    the user keeps what they typed while they fix it.

    Deliberately does not check quantity against the product's own
    units_in_stock -- adding more than what's technically in stock is
    not refused here.

    Access follows the same relaxed rule as order_create/order_build
    (_order_cart_denied, Enhancement 7). That same "is an employee
    driving this cart" flag is also what OrderDetailForm's
    employee_initiated argument uses to decide Enhancement 3's discount
    ceiling (10% for a plain customer cart, 100% for an employee's).
    """
    if _order_cart_denied(request, customer_id):
        return JsonResponse({"success": False, "errors": {"__all__": ["Not allowed."]}}, status=403)

    cart = request.session.get("cart")
    if not cart or cart.get("customer_id") != customer_id:
        return JsonResponse(
            {"success": False, "errors": {"__all__": ["Your cart isn't open anymore -- reload the page."]}},
            status=400,
        )

    employee_initiated = bool(request.session.get("current_user"))
    form = OrderDetailForm(request.POST, employee_initiated=employee_initiated)
    if not form.is_valid():
        # get_json_data(), not the bare ErrorDict form.errors itself --
        # Django's own error objects aren't directly JSON-serializable;
        # this returns a plain {field: [{"message": ..., "code": ...}]}
        # dict instead, which JsonResponse can actually encode.
        return JsonResponse({"success": False, "errors": form.errors.get_json_data()}, status=400)

    product = form.cleaned_data["product"]
    quantity = form.cleaned_data["quantity"]
    # Enhancement 3: the form validates/caps the percentage typed in;
    # this is the one place it's converted to the 0.0-1.0 fraction
    # OrderDetail.discount (and _cart_lines above) actually use.
    discount = form.cleaned_data["discount_percent"] / 100

    product_key = str(product.product_id)
    existing = cart["lines"].get(product_key, {"quantity": 0, "discount": 0.0})
    # Adding the same product again sums its quantity with what was
    # already there, but simply replaces the discount with whatever was
    # just entered -- there's one discount per line, not one per Add to
    # Cart click.
    cart["lines"][product_key] = {
        "quantity": existing["quantity"] + quantity,
        "discount": discount,
    }
    # Session middleware only notices a *replaced* top-level key by
    # default -- mutating cart["lines"] in place (as just above) doesn't
    # trigger that on its own, so this has to be set explicitly or the
    # change is silently dropped at the end of the request.
    request.session.modified = True

    cart_lines = _cart_lines(cart)
    line = next(line for line in cart_lines if line.product.product_id == product.product_id)
    row_html = render_to_string(
        "djtraders/orders/_order_line_row.html",
        {"line": line, "customer_id": customer_id},
        request=request,
    )
    cart_total = sum(line.line_total for line in cart_lines)
    # A fresh, empty Add to Cart card (no category chosen, quantity 1,
    # discount 0, nothing picked) -- the page swaps it in for the old
    # one, so what "starting over" looks like is decided here, in one
    # place, not by JavaScript clearing fields one at a time.
    customer = get_object_or_404(Customer, pk=customer_id)
    card_html = render_to_string(
        "djtraders/orders/_order_add_card.html",
        _add_to_cart_context(request, customer),
        request=request,
    )
    return JsonResponse(
        {
            "success": True,
            "row_html": row_html,
            "card_html": card_html,
            "product_id": product.product_id,
            "order_total": f"{cart_total:,.2f}",
        }
    )


def order_commit(request, customer_id):
    """
    Places the cart -- the one point where any of it is written to the
    database at all. Builds one real Order (order_date set to today;
    employee/required_date/shipped_date/ship_* all from OrderCommitForm,
    djtraders/forms.py -- ship_* defaults to the customer's own on-file
    address, order_build's own initial= values, but is a real, editable
    field a customer can override for this one order, Enhancement 6)
    and one real OrderDetail per
    cart line, inside a single transaction -- either the whole order is
    written, or, on any failure partway through, none of it is left
    half-written behind. Enhancement 5: that same transaction also
    decrements each product's units_in_stock by its line's quantity.
    The session cart is only cleared after all of that succeeds.

    OrderCommitForm is used unbound here (no instance=) -- it builds a
    brand-new Order via form.save(commit=False), rather than updating an
    existing one.

    Enhancement 5. Before writing anything, each cart line's product is
    re-read fresh from the database and checked against units_in_stock
    again -- OrderDetailForm's own clean() (djtraders/forms.py) already
    made this same check once, at add-to-cart time, but stock available
    then isn't guaranteed to still be available now. Any shortfall
    (stock_errors below) cancels the whole commit -- same all-or-nothing
    rule as the transaction itself, just checked one step earlier.

    Refuses to commit when there's no open cart for this customer, or it
    has no lines -- an order with nothing on it isn't a meaningful
    "placed" order -- redirecting back to order_build either way, which
    will itself (re)start an empty cart if needed. Access follows the
    same relaxed rule as order_create/order_build/order_add_line
    (_order_cart_denied, Enhancement 7).
    """
    if _order_cart_denied(request, customer_id):
        return redirect("djtraders:customer_detail", customer_id=customer_id)

    if request.method != "POST":
        return redirect("djtraders:order_build", customer_id=customer_id)

    cart = request.session.get("cart")
    if not cart or cart.get("customer_id") != customer_id or not cart.get("lines"):
        return redirect("djtraders:order_build", customer_id=customer_id)

    customer = get_object_or_404(Customer, pk=customer_id)
    cart_lines = _cart_lines(cart)
    if not cart_lines:
        return redirect("djtraders:order_build", customer_id=customer_id)

    form = OrderCommitForm(request.POST)
    # Enhancement 5, second check: a product's units_in_stock is
    # re-read fresh here, right before anything is written -- the
    # value each cart_line carries was current when that line was
    # added, not necessarily current now (someone else could have
    # bought the last few units in the meantime).
    fresh_products = Product.objects.in_bulk(
        [line.product.product_id for line in cart_lines]
    )
    stock_errors = []
    for line in cart_lines:
        product = fresh_products[line.product.product_id]
        if product.units_in_stock is not None and line.quantity > product.units_in_stock:
            stock_errors.append(
                f"Only {product.units_in_stock} of {product.product_name} left in stock."
            )

    if form.is_valid() and not stock_errors:
        # Enhancement 6: ship_* is one of OrderCommitForm's own Meta.fields
        # now, so form.save(commit=False) already set it from whatever
        # was submitted -- no longer copied from customer.* by hand here.
        order = form.save(commit=False)
        order.customer = customer
        order.order_date = timezone.now().date()

        with transaction.atomic():
            order.save()
            OrderDetail.objects.bulk_create(
                OrderDetail(
                    order=order,
                    product=line.product,
                    unit_price=line.unit_price,
                    quantity=line.quantity,
                    discount=line.discount,
                )
                for line in cart_lines
            )
            for line in cart_lines:
                product = fresh_products[line.product.product_id]
                if product.units_in_stock is not None:
                    product.units_in_stock -= line.quantity
                    product.save(update_fields=["units_in_stock"])

        del request.session["cart"]
        return redirect("djtraders:customer_detail", customer_id=customer_id)

    cart_total = sum(line.line_total for line in cart_lines)
    context = {
        "customer": customer,
        "cart_lines": cart_lines,
        "cart_total": cart_total,
        "commit_form": form,
        "stock_errors": stock_errors,
        **_add_to_cart_context(request, customer),
    }
    return render(request, "djtraders/orders/order_build.html", context)


def order_remove_line(request, customer_id, product_id):
    """
    Enhancement 1. Removes one product line from the in-progress cart
    entirely, rather than just lowering its quantity -- this only pops
    product_id out of request.session["cart"]["lines"], the same dict
    order_add_line reads/writes; there is no database row to delete
    before commit. Same access rule (_order_cart_denied, Enhancement 7)
    and POST-only/redirect shape as order_add_line/order_commit above.
    """
    if _order_cart_denied(request, customer_id):
        return redirect("djtraders:customer_detail", customer_id=customer_id)

    if request.method != "POST":
        return redirect("djtraders:order_build", customer_id=customer_id)

    cart = request.session.get("cart")
    if cart and cart.get("customer_id") == customer_id:
        cart["lines"].pop(str(product_id), None)
        request.session.modified = True

    return redirect("djtraders:order_build", customer_id=customer_id)


def order_clear_cart(request, customer_id):
    """
    Enhancement 4. Resets the in-progress cart back to empty
    (request.session["cart"]["lines"] = {}) without committing it --
    same one-click, no-confirm-step convention as order_remove_line
    above, just clearing every line instead of one. Same access rule
    (_order_cart_denied, Enhancement 7) and POST-only/redirect shape as
    every other cart-mutating view in this file.
    """
    if _order_cart_denied(request, customer_id):
        return redirect("djtraders:customer_detail", customer_id=customer_id)

    if request.method != "POST":
        return redirect("djtraders:order_build", customer_id=customer_id)

    cart = request.session.get("cart")
    if cart and cart.get("customer_id") == customer_id:
        cart["lines"] = {}
        request.session.modified = True

    return redirect("djtraders:order_build", customer_id=customer_id)


def order_delete(request, order_id):
    """
    Cancels a placed order -- a real, hard DELETE (OrderDetail's own
    CASCADE on its order FK, models.py, cleans up its lines for free) --
    but only on the same calendar day it was placed. order_date itself
    is the placed/draft flag and never touched after commit, so "today"
    here is compared against that same value order_commit set, not
    recomputed some other way.

    A still-open cart (order_date is None) is refused here too -- there
    is nothing "placed" yet to cancel. Access is the order's own
    customer, or an employee (_order_access_denied, above), same as
    build/commit.

    No confirmation step (no "are you sure?" page or JS dialog) -- a
    single-click POST, the same convention Commit Order itself already
    uses. order_detail.html's own Cancel Order button is gated
    (can_cancel_order, order_detail above) so it's only shown when this
    would actually succeed; reaching this view any other way (a stale
    page, a same-day order that ticks past midnight while the tab is
    still open, or the URL typed directly) fails this same check and is
    silently redirected back, same as every other guard in this file.
    """
    order = get_object_or_404(Order, pk=order_id)

    if _order_access_denied(request, order):
        return redirect("djtraders:home")

    if request.method != "POST":
        return redirect("djtraders:order_detail", order_id=order.order_id)

    if order.order_date is None or order.order_date != timezone.now().date():
        return redirect("djtraders:order_detail", order_id=order.order_id)

    customer_id = order.customer_id
    order.delete()

    if customer_id:
        return redirect("djtraders:customer_detail", customer_id=customer_id)
    return redirect("djtraders:home")
