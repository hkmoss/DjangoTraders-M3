"""
Django Forms for the djtraders app.

A Form (or ModelForm, below) is Django's own way of describing an HTML
form's fields, validation, and rendering as a Python class, instead of
hand-written <input> tags. CustomerEditForm below is the customer edit
page's form, rendered by customer_edit.html through django-crispy-forms'
{% crispy %} tag (see settings.py's INSTALLED_APPS/CRISPY_* settings).
It declares its fields and layout once as a class, and gets validation
Django builds in for free (a required field, a max length) without any
hand-written checks in the view.

CustomerEditForm's fields also carry a running example of Django's
three validation layers, each one enforcing the same rule a different
way:
  - Browser layer (courtesy only): an HTML5 pattern=/required/min=
    attribute on the widget, set in __init__ below. Blocks an obviously
    bad value before a request is even sent -- but proves nothing,
    since disabling JS or editing the request in DevTools skips it
    entirely.
  - Server layer (the real check): a clean_<field>() method (or the
    cross-field clean() on OrderCommitForm below) re-checks the same
    rule and raises ValidationError if it fails. This is the one layer
    that can't be bypassed from the browser.
  - Database layer (final backstop, when there is one): a column
    constraint like max_length that Postgres enforces regardless of
    the two layers above. Some rules (no digits in a company name, a
    required contact name) have no database layer behind them at all --
    the schema simply doesn't express that rule, so the form is the
    only thing enforcing it.
phone (clean_phone), company_name/city (clean_company_name/clean_city,
no-digits), and contact_name (required=True override in __init__) are
four small, independent examples of this pattern -- useful as a
template for writing a new business rule elsewhere in the app.
"""
import re
from datetime import timedelta

from crispy_forms.helper import FormHelper
from crispy_forms.layout import HTML, Column, Layout, Row
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import Customer, Order, OrderDetail

# Digits, spaces, parentheses, and dashes only, 7-20 characters -- loose
# enough to accept "(206) 555-9857" or "030-0074321", tight enough to
# reject obvious garbage. Shared by the widget's HTML5 pattern attribute
# (browser layer) and clean_phone() below (server layer), so the two
# can never quietly drift apart.
PHONE_PATTERN = r"[0-9()\-\s]{7,20}"

# No digit characters anywhere -- "[^0-9]*" reads as "zero or more
# non-digit characters," which as a FULL match (see clean_company_name/
# clean_city below, and the pattern= attribute __init__ sets) means "the
# whole string, and there's not a single digit in it." Shared the same
# way PHONE_PATTERN is, between the browser-layer widget attribute and
# the server-layer clean_<field>() checks.
NO_DIGITS_PATTERN = r"[^0-9]*"


class CustomerEditForm(forms.ModelForm):
    """
    Edits every Customer field except customer_id (the primary key --
    ModelForm never includes it unless told to) and inactive_date
    (deliberately left out of Meta.fields below, since it's not part of
    this edit page).

    self.helper (a crispy-forms FormHelper) is what {% crispy form %}
    (customer_edit.html) actually reads to render this form --
    without one, crispy still renders every field, but adds no submit
    button at all, and stacks every field one per row instead of the
    grid self.helper.layout describes below. The HTML(...) at the end
    of that layout is a real, hand-written <button> tag: crispy's own
    Submit/StrictButton layout objects both render a plain <input>,
    which can't hold the icon this project's buttons all carry.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Browser layer for phone (see module docstring): pattern=
        # matches PHONE_PATTERN so it can't drift from clean_phone()
        # below. title= is the tooltip browsers show on a mismatch.
        self.fields["phone"].widget.attrs.update({
            "pattern": PHONE_PATTERN,
            "title": "Digits, spaces, parentheses, and dashes only (7-20 characters).",
        })
        # Same idea for the no-digits examples -- except neither has a
        # database constraint backing it up.
        self.fields["company_name"].widget.attrs.update({
            "pattern": NO_DIGITS_PATTERN,
            "title": "No numbers in a company name.",
        })
        self.fields["city"].widget.attrs.update({
            "pattern": NO_DIGITS_PATTERN,
            "title": "No numbers in a city name.",
        })
        # Contact Name can't be blank; the model allows it (blank=True,
        # null=True), so required=True here is the entire fix -- it
        # covers both the browser (HTML5 required attr) and server
        # (field-level validation, before clean_<field>() runs) layers
        # at once, with no database layer behind it either.
        self.fields["contact_name"].required = True
        self.helper = FormHelper()
        # A real id= on the rendered <form>, so customer_edit.html's own
        # {% block scripts %} can target it by id (ValidateCustomerEditForm,
        # DjangoTraders.js) -- crispy renders no id at all by default.
        self.helper.form_id = "customer-edit-form"
        # The field grid -- Row/Column are crispy's own layout objects,
        # each Column's css_class a Bootstrap col-md-* width. The trailing
        # HTML(...) is the Save button itself (see this class's docstring).
        self.helper.layout = Layout(
            Row(
                Column("company_name", css_class="col-md-6"),
                Column("contact_name", css_class="col-md-6"),
            ),
            Row(
                Column("contact_title", css_class="col-md-6"),
                Column("phone", css_class="col-md-6"),
            ),
            Row(
                Column("fax", css_class="col-md-6"),
                Column("password", css_class="col-md-6"),
            ),
            Row(
                Column("address", css_class="col-md-8"),
                Column("city", css_class="col-md-4"),
            ),
            Row(
                Column("region", css_class="col-md-4"),
                Column("postal_code", css_class="col-md-4"),
                Column("country", css_class="col-md-4"),
            ),
            HTML(
                """
                <div class="d-flex gap-2 mt-3 justify-content-end">
                    <button type="submit" class="btn dt-btn-primary-customer w3-hover-shadow" title="Save changes">
                        <i class="fa-solid fa-floppy-disk me-1 dt-icon-success"></i>Save
                    </button>
                    <div class="dt-link-wrap btn dt-btn-secondary-customer w3-hover-shadow">
                        {% if new_customer %}
                            <a href="{% url 'djtraders:customer_list' %}" title="Cancel -- nothing has been saved yet">
                                <i class="fa-solid fa-xmark me-1 dt-icon-danger"></i>Cancel
                            </a>
                        {% else %}
                            <a href="{% url 'djtraders:customer_detail' customer.customer_id %}" title="Cancel and discard changes">
                                <i class="fa-solid fa-xmark me-1 dt-icon-danger"></i>Cancel
                            </a>
                        {% endif %}
                    </div>
                </div>
                """
            ),
        )

    class Meta:
        model = Customer
        fields = [
            "company_name",
            "contact_name",
            "contact_title",
            "address",
            "city",
            "region",
            "postal_code",
            "country",
            "phone",
            "fax",
            "password",
        ]
        widgets = {
            "password": forms.PasswordInput(render_value=True),
        }

    def clean_phone(self):
        """
        Server layer of the phone validation example. Django calls
        clean_<field_name>() automatically for any field named this
        way, after that field's own basic type/max_length checks
        already passed and before clean() (there isn't one on this
        class) runs -- this is a hand-written business rule, raising
        ValidationError directly, rather than something Django enforces
        for free.

        phone is optional (blank=True, null=True on the model), so an
        empty value is valid and skips the pattern check entirely --
        only a non-blank value gets held to PHONE_PATTERN. Runs whether
        or not the browser's own pattern= attribute (__init__ above) was
        honored, bypassed, or never sent at all -- a POST straight to
        this view (curl, DevTools, an edited request) hits this exact
        same check.
        """
        phone = self.cleaned_data.get("phone", "")
        if phone and not re.fullmatch(PHONE_PATTERN, phone):
            raise ValidationError(
                "Enter a valid phone number (digits, spaces, parentheses, "
                "and dashes only, 7-20 characters)."
            )
        return phone

    def clean_company_name(self):
        """
        Server layer of the first no-digits example. company_name is
        required, and Django's own required check runs before
        clean_<field_name>(), so no blank check is needed here -- only
        the digits rule.
        """
        name = self.cleaned_data.get("company_name", "")
        if not re.fullmatch(NO_DIGITS_PATTERN, name):
            raise ValidationError("Company name can't contain numbers.")
        return name

    def clean_city(self):
        """
        Server layer of the second no-digits example. city is optional
        (blank=True, null=True on the model, unlike company_name
        above), so an empty value is valid and skips the digits check
        entirely, the same pattern clean_phone() above already uses.
        """
        city = self.cleaned_data.get("city", "")
        if city and not re.fullmatch(NO_DIGITS_PATTERN, city):
            raise ValidationError("City can't contain numbers.")
        return city


class OrderDetailForm(forms.ModelForm):
    """
    Adds one line item (product + quantity + discount) to a draft Order.

    product/quantity/discount_percent are the only fields ever collected
    from the user; unit_price (a required, non-null column on
    OrderDetail -- djtraders/models.py) is set by the view from the
    chosen product's own current unit_price, not asked for here.

    discount_percent is a plain, non-model field (not in Meta.fields
    below) rather than a direct ModelForm field over OrderDetail's own
    discount column, because the two use different units: a customer
    enters a percentage ("10" meaning 10%), while OrderDetail.discount
    stores that same rate as a fraction (0.10) -- see its own line_total
    property. clean_discount_percent below is the one place that
    percent-to-fraction conversion has to be remembered at all; the view
    (order_add_line, djtraders/views.py) divides by 100 once validation
    passes and never touches the raw percentage again.

    Enhancement 3. Up to 10% is accepted with no further check -- a
    normal, self-service discount. Anything higher needs a manager's
    say-so, which this project expresses the same way Enhancement 7
    already relaxes the cart's own access rule: only a cart an employee
    is driving (employee_initiated=True, passed in by the view from
    request.session["current_user"]) may go as high as 100%; a plain
    customer cart is capped at 10% no matter what's typed in.

    Enhancement 5. clean() below checks quantity against the selected
    product's own units_in_stock -- a cross-field rule, unlike
    CustomerEditForm's clean_phone()/clean_company_name()/clean_city()
    above, since it needs product and quantity together rather than
    either field alone. This is only the first of two stock checks:
    a courtesy check here, at add-to-cart time, plus the real,
    authoritative re-check order_commit (djtraders/views.py) makes
    against each product's *current* units_in_stock right before
    writing the order -- stock available when a line was added isn't
    guaranteed to still be available by the time the cart is committed.

    Enhancement 2. category_id (order_build's own "category" GET
    parameter) narrows the Product dropdown to one category at a time,
    the same filter Product.search already offers on product_list.html
    -- optional, since order_build's other callers (order_commit's own
    error-path re-render) construct this form with no category chosen.
    """
    discount_percent = forms.FloatField(
        required=False, initial=0, label="Discount %"
    )

    def __init__(self, *args, category_id=None, employee_initiated=False, **kwargs):
        super().__init__(*args, **kwargs)
        # Enhancement 3: clean_discount_percent below reads this same
        # flag to pick the 10%/100% ceiling.
        self.employee_initiated = employee_initiated

        # Only non-discontinued products are offered -- same reasoning
        # as Product.search's own show_all=False default (models.py).
        products = self.fields["product"].queryset.filter(discontinued=0)
        if category_id:
            products = products.filter(category_id=category_id)
        self.fields["product"].queryset = products
        # The product is chosen through order_build.html's autocomplete
        # text box (product_search_json), which writes the chosen
        # product's pk into this field -- so it renders as a hidden
        # <input id="id_product">, not a dropdown. The queryset above is
        # still the server-side gate: a pk that doesn't exist, or belongs
        # to a discontinued product, fails ModelChoiceField validation
        # no matter what the browser sent.
        self.fields["product"].widget = forms.HiddenInput()
        self.fields["product"].error_messages["invalid_choice"] = (
            "Pick a product from the suggestions -- that one isn't available."
        )
        # Browser layer (courtesy): a real HTML5 min= on the rendered
        # <input>, blocking an obviously-bad quantity (zero or negative)
        # before a request is even sent. Not a guarantee -- same caveat
        # as every other pattern= attribute in this file.
        self.fields["quantity"].widget.attrs.update({"min": 1, "class": "form-control"})
        # Starts at 1 -- the same value the card shows again after every
        # successful add (order_add_line renders a fresh card).
        self.fields["quantity"].initial = 1
        # Same browser-layer courtesy for discount_percent -- max=
        # matches whichever ceiling clean_discount_percent below will
        # actually enforce, so an employee's cart shows a wider allowed
        # range than a plain customer cart, right on the input itself.
        self.fields["discount_percent"].widget.attrs.update({
            "min": 0,
            "max": 100 if employee_initiated else 10,
            "step": "0.01",
            "class": "form-control",
        })

    class Meta:
        model = OrderDetail
        fields = ["product", "quantity"]

    def clean_quantity(self):
        """
        Server layer: quantity has to be a positive number.
        """
        quantity = self.cleaned_data.get("quantity")
        if quantity is not None and quantity < 1:
            raise ValidationError("Quantity must be at least 1.")
        return quantity

    def clean_discount_percent(self):
        """
        Server layer for Enhancement 3's discount ceiling (see this
        class's own docstring). A blank field defaults to 0 -- discount
        is optional, same as it was before this form collected one at
        all.
        """
        discount_percent = self.cleaned_data.get("discount_percent")
        if discount_percent is None:
            return 0.0
        if discount_percent < 0:
            raise ValidationError("Discount can't be negative.")
        ceiling = 100 if self.employee_initiated else 10
        if discount_percent > ceiling:
            raise ValidationError(
                f"Discount can't exceed {ceiling:g}% -- ask an employee to "
                f"place this order for a higher discount."
            )
        return discount_percent

    def clean(self):
        """
        Enhancement 5, courtesy check (see this class's own docstring):
        quantity can't exceed the selected product's own units_in_stock.
        A cross-field rule, so it belongs in clean() rather than a
        single-field clean_<field>() -- same reasoning as
        OrderCommitForm.clean() below.

        Only runs once product and quantity have each already passed
        their own field-level checks (a missing product, or a quantity
        clean_quantity above already rejected, cleaned_data simply won't
        have that key). units_in_stock can be None on some products
        (an ordinary nullable column, models.py) -- treated as "no
        stock limit to check" rather than "zero in stock."
        """
        cleaned_data = super().clean()
        product = cleaned_data.get("product")
        quantity = cleaned_data.get("quantity")
        stock_known = product is not None and product.units_in_stock is not None
        if stock_known and quantity is not None and quantity > product.units_in_stock:
            self.add_error(
                "quantity",
                f"Only {product.units_in_stock} of {product.product_name} left in stock.",
            )
        return cleaned_data


class OrderCommitForm(forms.ModelForm):
    """
    Sets an order's employee/required_date/shipped_date at commit time
    -- the one point where a cart becomes a real, placed Order.
    order_date itself is set by the view (order_commit, djtraders/
    views.py), not by this form -- it's always today, on commit, not a
    value anyone picks.

    employee is a real, required field on this form even though the
    model column itself is nullable (Order.employee, models.py,
    SET_NULL) -- required here is a business rule ("every placed order
    needs an employee of record"), not a database constraint, the same
    "form is stricter than the column" shape as everywhere else in this
    file. __init__ below overrides the ModelForm default (a nullable
    model field would otherwise make this field optional on its own)
    and gives it a label_from_instance, the same reason OrderDetailForm's
    product field needs one -- Employee (models.py) has no __str__ of
    its own, so without this override each option would render as
    Django's default "Employee object (5)".

    required_date/shipped_date both come with a sensible default (two
    weeks out / one week out from today) computed in the view and
    passed in as this form's initial= values, but both stay real,
    editable fields -- a business-convention starting guess, not a
    fixed rule.

    Enhancement 6. ship_name/ship_address/ship_city/ship_region/
    ship_postal_code/ship_country (Order's own columns, models.py) are
    real, editable fields here too, instead of order_commit copying the
    customer's on-file address onto them unconditionally -- the view
    passes that same on-file address in as this form's initial= values
    (same "sensible starting guess, stays editable" shape as
    required_date/shipped_date above), so a customer sees their usual
    address prefilled but can ship somewhere else for this one order.
    ship_name/ship_address/ship_city/ship_country are required as a
    business rule (a real shipment needs at least those); ship_region/
    ship_postal_code stay optional, the same as Customer's own
    region/postal_code fields (not every address uses them).

    Used unbound (no instance=) -- order_commit (djtraders/views.py)
    calls form.save(commit=False) to build a brand-new Order. A
    ModelForm behaves as a create form or an update form purely based
    on whether instance= was passed at construction, not on anything
    declared here.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["employee"].required = True
        self.fields["employee"].empty_label = "Select an employee..."
        self.fields["employee"].queryset = self.fields["employee"].queryset.order_by(
            "last_name", "first_name"
        )
        self.fields["employee"].label_from_instance = (
            lambda employee: f"{employee.first_name} {employee.last_name}"
        )
        self.fields["employee"].widget.attrs.update({"class": "form-select"})

        # Enhancement 6: required as a business rule, same "form is
        # stricter than the column" shape as employee above -- every
        # one of these columns is nullable on Order itself (models.py).
        for field_name in ("ship_name", "ship_address", "ship_city", "ship_country"):
            self.fields[field_name].required = True
        for field_name in (
            "ship_name", "ship_address", "ship_city",
            "ship_region", "ship_postal_code", "ship_country",
        ):
            self.fields[field_name].widget.attrs.update({"class": "form-control"})

    class Meta:
        model = Order
        fields = [
            "employee",
            "required_date",
            "shipped_date",
            "ship_name",
            "ship_address",
            "ship_city",
            "ship_region",
            "ship_postal_code",
            "ship_country",
        ]
        widgets = {
            "required_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "shipped_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        }

    def clean(self):
        """
        Same "no database backstop" shape as every other business rule
        in this file: nothing stops Postgres from storing a required/
        shipped date before the order was even placed -- these two
        checks are the only thing that would catch it.
        """
        cleaned_data = super().clean()
        today = timezone.now().date()
        for field_name, label in (("required_date", "Required date"), ("shipped_date", "Ship-by date")):
            value = cleaned_data.get(field_name)
            if value is not None and value < today:
                self.add_error(field_name, f"{label} can't be before today's order date.")
        return cleaned_data


def default_required_date():
    """order_date (today, at commit) + 2 weeks -- see OrderCommitForm."""
    return timezone.now().date() + timedelta(weeks=2)


def default_shipped_date():
    """order_date (today, at commit) + 1 week -- see OrderCommitForm."""
    return timezone.now().date() + timedelta(weeks=1)
