"""
URL configuration for the djtraders app.

Each Django *app* gets its own urls.py so its routes stay self-contained;
the project-level urls.py (DjangoTraders/urls.py) "includes" this file
under a prefix. Every route below is a path() call bound to a name --
templates/views reverse() a URL by that name (e.g.
"djtraders:customer_detail") instead of hard-coding the path string, so
a path can change here without hunting down every place it's linked
from.

Path converters (<str:customer_id>, <int:order_id>, ...) capture a
segment of the URL and pass it to the view as a keyword argument, typed
to match that model's primary key -- <str:...> for Customer's
CharField id, <int:...> for the AutoField ids (Product, Order,
Employee).

A few routes need a specific order in urlpatterns below: customer_create_url
must come before customer_detail_url, since <str:customer_id> would
otherwise happily match the literal word "create" as a customer_id
(Django tries patterns top to bottom and stops at the first match).

order_build/order_add_line/order_commit are keyed by customer_id, not
an order_id -- an in-progress order is only ever session state
(request.session["cart"], see views.py) until order_commit writes it
to the database, so there's no Order row yet to key a URL by. order_
detail/order_delete act on a real, already-placed Order row, so they
stay keyed by order_id.
"""
from django.urls import path

from . import views

# NAMESPACE for every route below -- lets templates/reverse() use
# "djtraders:customer_list" instead of a bare "customer_list", avoiding
# name collisions as more apps are added.
app_name = "djtraders"

# GET /djtraders/ -> views.home. An empty path means "the root of
# whatever prefix this urls.py was include()'d under" (djtraders/).
home_url = path("", views.home, name="home")

# GET /djtraders/customers/ -> views.customer_list
customer_list_url = path("customers/", views.customer_list, name="customer_list")

# GET /djtraders/products/ -> views.product_list
product_list_url = path("products/", views.product_list, name="product_list")

# GET/POST /djtraders/customers/create/ -> views.customer_create
# Must come before customer_detail_url below in urlpatterns (see this
# file's own docstring).
customer_create_url = path("customers/create/", views.customer_create, name="customer_create")

# <str:...>, not <int:...> -- Customer's primary key is a CharField
# (e.g. "ALFKI"), which an int converter would reject.
customer_detail_url = path(
    "customers/<str:customer_id>/", views.customer_detail, name="customer_detail"
)

order_detail_url = path(
    "orders/<int:order_id>/", views.order_detail, name="order_detail"
)

# GET/POST /djtraders/login/ -> views.login_view
login_url = path("login/", views.login_view, name="login")

# GET /djtraders/logout/ -> views.logout_view
logout_url = path("logout/", views.logout_view, name="logout")

product_detail_url = path(
    "products/<int:product_id>/", views.product_detail, name="product_detail"
)

# GET /djtraders/products/search-json/?term=... -> views.product_search_json
# (JSON for the order_build Product autocomplete)
product_search_json_url = path(
    "products/search-json/", views.product_search_json, name="product_search_json"
)

# GET/POST /djtraders/customer-login/ -> views.customer_login_view
customer_login_url = path(
    "customer-login/", views.customer_login_view, name="customer_login"
)

# GET /djtraders/customer-logout/ -> views.customer_logout_view
customer_logout_url = path(
    "customer-logout/", views.customer_logout_view, name="customer_logout"
)

# GET/POST /djtraders/customers/<customer_id>/edit/ -> views.customer_edit
customer_edit_url = path(
    "customers/<str:customer_id>/edit/",
    views.customer_edit,
    name="customer_edit",
)

# POST /djtraders/customers/<customer_id>/delete/ -> views.customer_delete
customer_delete_url = path(
    "customers/<str:customer_id>/delete/", views.customer_delete, name="customer_delete"
)

employee_detail_url = path(
    "employees/<int:employee_id>/", views.employee_detail, name="employee_detail"
)

# GET /djtraders/employees/<id>/dashboard/, /info/, /list/ -> views.employee_dashboard,
# employee_info, employee_list (HTML fragments that employee_detail.html's tab
# control loads by AJAX; /list/ is managers only)
employee_dashboard_url = path(
    "employees/<int:employee_id>/dashboard/", views.employee_dashboard, name="employee_dashboard"
)
employee_customer_chart_url = path(
    "employees/<int:employee_id>/customer-chart/", views.employee_customer_chart, name="employee_customer_chart"
)
employee_breakdown_chart_url = path(
    "employees/<int:employee_id>/breakdown-chart/", views.employee_breakdown_chart, name="employee_breakdown_chart"
)
employee_revenue_chart_url = path(
    "employees/<int:employee_id>/revenue-chart/", views.employee_revenue_chart, name="employee_revenue_chart"
)
employee_period_detail_url = path(
    "employees/<int:employee_id>/revenue-period/", views.employee_period_detail, name="employee_period_detail"
)
employee_info_url = path(
    "employees/<int:employee_id>/info/", views.employee_info, name="employee_info"
)
employee_list_url = path(
    "employees/<int:employee_id>/list/", views.employee_list, name="employee_list"
)

# POST /djtraders/customers/<customer_id>/orders/create/ -> views.order_create
order_create_url = path(
    "customers/<str:customer_id>/orders/create/", views.order_create, name="order_create"
)

# GET /djtraders/customers/<customer_id>/orders/build/ -> views.order_build
order_build_url = path(
    "customers/<str:customer_id>/orders/build/", views.order_build, name="order_build"
)

# POST /djtraders/customers/<customer_id>/orders/add-line/ -> views.order_add_line (AJAX)
order_add_line_url = path(
    "customers/<str:customer_id>/orders/add-line/", views.order_add_line, name="order_add_line"
)

# GET /djtraders/customers/<customer_id>/orders/add-card/?category=... -> views.order_add_card (AJAX)
order_add_card_url = path(
    "customers/<str:customer_id>/orders/add-card/", views.order_add_card, name="order_add_card"
)

# POST /djtraders/customers/<customer_id>/orders/commit/ -> views.order_commit
order_commit_url = path(
    "customers/<str:customer_id>/orders/commit/", views.order_commit, name="order_commit"
)

# Enhancement 1. POST /djtraders/customers/<customer_id>/orders/remove-line/<product_id>/
# -> views.order_remove_line
order_remove_line_url = path(
    "customers/<str:customer_id>/orders/remove-line/<int:product_id>/",
    views.order_remove_line,
    name="order_remove_line",
)

# Enhancement 4. POST /djtraders/customers/<customer_id>/orders/clear/
# -> views.order_clear_cart
order_clear_cart_url = path(
    "customers/<str:customer_id>/orders/clear/",
    views.order_clear_cart,
    name="order_clear_cart",
)

# POST /djtraders/orders/<order_id>/delete/ -> views.order_delete
order_delete_url = path(
    "orders/<int:order_id>/delete/", views.order_delete, name="order_delete"
)

# GET /djtraders/customers/<id>/dashboard/, /info/, /orders/ -> views.customer_dashboard,
# customer_info, customer_orders (HTML fragments that customer_detail.html's
# tab control loads by AJAX)
customer_dashboard_url = path(
    "customers/<str:customer_id>/dashboard/",
    views.customer_dashboard, name="customer_dashboard",
)
# GET /djtraders/customers/<id>/monthly-chart/?year=2025 -> views.customer_monthly_chart
# (the chart the dashboard's year dropdown loads, as an HTML fragment)
customer_monthly_chart_url = path(
    "customers/<str:customer_id>/monthly-chart/",
    views.customer_monthly_chart, name="customer_monthly_chart",
)
customer_info_url = path(
    "customers/<str:customer_id>/info/",
    views.customer_info, name="customer_info",
)
customer_orders_url = path(
    "customers/<str:customer_id>/orders/",
    views.customer_orders, name="customer_orders",
)

# Supplier portal: login/logout, then the supplier page and its three AJAX tabs
# (views.supplier_login_view / supplier_logout_view / supplier_detail /
# supplier_info / supplier_orders / supplier_products)
supplier_login_url = path("supplier-login/", views.supplier_login_view, name="supplier_login")
supplier_logout_url = path("supplier-logout/", views.supplier_logout_view, name="supplier_logout")
supplier_detail_url = path(
    "suppliers/<int:supplier_id>/", views.supplier_detail, name="supplier_detail"
)
supplier_info_url = path(
    "suppliers/<int:supplier_id>/info/", views.supplier_info, name="supplier_info"
)
supplier_orders_url = path(
    "suppliers/<int:supplier_id>/orders/", views.supplier_orders, name="supplier_orders"
)
supplier_products_url = path(
    "suppliers/<int:supplier_id>/products/", views.supplier_products, name="supplier_products"
)

# region [CONCEPT] why this list must be named "urlpatterns"
# urlpatterns is the one name Django's URL resolver actually looks for in
# this module -- it must be called exactly that (not e.g. "urls" or
# "routes") for the project-level urls.py's include("djtraders.urls") to
# find these routes at all. Each entry above is just a plain variable
# (home_url, customer_list_url, ...); this list is what turns them into
# the app's real, ordered set of routes.
# endregion
urlpatterns = [
    home_url,
    customer_list_url,
    product_list_url,
    customer_create_url,
    customer_detail_url,
    order_detail_url,
    login_url,
    logout_url,
    product_detail_url,
    product_search_json_url,
    customer_login_url,
    customer_logout_url,
    customer_edit_url,
    employee_detail_url,
    employee_dashboard_url,
    employee_breakdown_chart_url,
    employee_customer_chart_url,
    employee_revenue_chart_url,
    employee_period_detail_url,
    employee_info_url,
    employee_list_url,
    customer_delete_url,
    order_create_url,
    order_build_url,
    order_add_line_url,
    order_add_card_url,
    order_commit_url,
    order_remove_line_url,
    order_clear_cart_url,
    order_delete_url,
    customer_dashboard_url,
    customer_monthly_chart_url,
    customer_info_url,
    customer_orders_url,
    supplier_login_url,
    supplier_logout_url,
    supplier_detail_url,
    supplier_info_url,
    supplier_orders_url,
    supplier_products_url,
]
