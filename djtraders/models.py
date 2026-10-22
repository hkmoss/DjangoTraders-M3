"""
Cleaned-up models generated from `manage.py inspectdb` (see
rev_engineer_models.py for the raw, unedited output). inspectdb reads
an existing database's tables and writes a first-draft model per table,
but leaves manual work behind: every model here is set managed=False
(this app reads a database Django didn't create, so it should never try
to migrate these tables), model names were singularized (Category,
Customer, ...) and reordered so each is defined before anything that
references it by bare class name, and every foreign key was given a
real on_delete (inspectdb defaults to DO_NOTHING) matching what should
actually happen when the related row is removed.

Beyond that baseline, most models add a few computed @property values
(e.g. Order.order_total, Customer.formatted_address) and a couple carry
classmethods used by views.py: *.search() backs a list page's search
form, and Employee.authenticate/Customer.authenticate back this app's
two hand-rolled logins (no django.contrib.auth involved). Each one's
own docstring below explains the specifics.
"""

import calendar

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from django.db import models
from django.db.models import Count, ExpressionWrapper, F, FloatField, Sum


# region [WHY] one fixed color per bar
# The eight categorical hues of the project's chart palette, in a fixed
# order (blue, orange, aqua, yellow, magenta, green, violet, red). A bar
# chart gives each x value its own hue so bars are easy to tell apart;
# _bar_figure picks them by position in a stable ordering, so
# the same category or product keeps the same color in every chart on
# the dashboard. With more than eight bars the colors repeat -- the axis
# label, not the color, is what identifies a bar.
# endregion
CHART_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]


# region [WHY] chart helpers shared by every portal
# The functions below turn order lines into DataFrames and DataFrames
# into chart HTML. They live at module level, not on one model, so the
# customer, employee and supplier pages all build their charts the same
# way: get a queryset of OrderDetail rows for that portal's user, pass
# it to _lines_frame, group with pandas, and hand the result to
# _bar_figure. Revenue is each line's unit_price * quantity *
# (1 - discount), the same formula as OrderDetail.line_total -- not
# Product.unit_price, which is today's list price and ignores both
# discounts and any price change since the order was placed.
# endregion
def _lines_frame(lines):
    """
    Turns a queryset of OrderDetail rows into a pandas DataFrame, one
    row per line, with the columns the chart methods group on:
    order_id, order_date, year, month, product_name, category_name,
    customer_name, quantity, and revenue (an empty DataFrame when there
    are no lines).

    .values() asks the database for just those columns as plain dicts
    instead of building a model object per row, which is what
    pd.DataFrame wants.
    """
    rows = lines.values(
        "order_id",
        "order__order_date",
        "order__customer__company_name",
        "product__product_name",
        "product__category__category_name",
        "unit_price",
        "quantity",
        "discount",
    )
    frame = pd.DataFrame(list(rows))
    if frame.empty:
        return frame
    frame = frame.rename(columns={
        "order__order_date": "order_date",
        "order__customer__company_name": "customer_name",
        "product__product_name": "product_name",
        "product__category__category_name": "category_name",
    })
    frame["order_date"] = pd.to_datetime(frame["order_date"])
    frame["year"] = frame["order_date"].dt.year
    frame["month"] = frame["order_date"].dt.month
    frame["revenue"] = frame["unit_price"] * frame["quantity"] * (1 - frame["discount"])
    frame["category_name"] = frame["category_name"].fillna("Uncategorized")
    frame["customer_name"] = frame["customer_name"].fillna("Unknown customer")
    return frame


def _figure_html(figure):
    """
    Turns a Plotly figure into an HTML <div> (plus the small <script>
    that draws it). include_plotlyjs=False leaves the ~4 MB plotly.js
    library out of every chart: the page loads it once itself
    (customer_detail.html) instead of re-sending it with each tab.
    """
    # The chart title is styled like a card title in the page (Bootstrap's h5: 20px, dark
    # text, flush left in the card), so a chart and an HTML card heading look alike.
    figure.update_layout(
        template="plotly_white", margin=dict(l=40, r=20, t=50, b=40),
        title=dict(x=0, xref="container", xanchor="left", font=dict(size=20, color="#212529", family='"Segoe UI", Tahoma, "Trebuchet MS", sans-serif')),
    )
    return figure.to_html(full_html=False, include_plotlyjs=False)


def _color_map(names):
    """Maps each distinct name to a CHART_COLORS entry by its position in sorted order (repeating after eight)."""
    ordered = sorted(set(names), key=str)
    return {name: CHART_COLORS[i % len(CHART_COLORS)] for i, name in enumerate(ordered)}


def _bar_figure(data, category, value, title, labels, color_names=None,
                horizontal=False, height=None, trend=True, text=None, hover=None):
    """
    Builds one bar chart the same way for every chart on the dashboard:
    a bar per row of data, each bar its own color (see CHART_COLORS),
    plus (when trend=True) a dashed linear trend line over the bars.

    data is a DataFrame already in display order; category is the
    column of bar names and value the column of bar lengths.
    color_names is the full set of names to assign colors from (so a
    chart showing only the top ten products still uses the same colors
    as a chart showing all of them); it defaults to data[category].

    The trend line is a straight least-squares fit (np.polyfit,
    degree 1) of value against bar position, 0, 1, 2, ... For
    time-ordered bars (months, years) that is a real trend. For bars
    sorted by size (products, categories) it is the average rate at
    which the bars fall off from largest to smallest. The product and
    category charts pass trend=False for that reason: the line says
    little about bars already sorted by size. The fitted line is clamped at zero,
    since a negative revenue or unit count makes no sense.

    Every bar is labeled with its value at the end of the bar: whole
    units for the quantity column, whole dollars for anything else. Pass
    text (a list of labels, one per bar) to replace those labels; the
    supplier chart does, to show percentages. Pass hover (a list of strings, one
    per bar, with <br> for line breaks) to replace the hover box's text, as the
    revenue-over-time chart does to add the order count. Plotly needs room beyond
    the longest bar for the label, so the value axis is stretched 25%
    (55% for long labels like dollars plus a percentage) past the largest bar,
    and the label font is 11 pt.

    Every figure gets an explicit height: left unset, Plotly sizes to
    its container, and inside the dashboard's equal-height cards that
    container's height depends on the figure itself, so the chart
    collapses to a sliver.
    """
    colors = _color_map(data[category] if color_names is None else color_names)
    names = list(data[category])
    values = list(data[value])
    bar_colors = [colors[name] for name in names]
    if text is None:
        text = [f"{v:,.0f}" if value == "quantity" else f"${v:,.0f}" for v in values]

    # The hover box shows the bar's name and its label (the same text printed
    # at the bar's end). Without a hovertemplate Plotly labels an unnamed
    # trace "trace 0" and prints the raw axis numbers.
    tip_h, tip_v = "<b>%{y}</b><br>%{text}<extra></extra>", "<b>%{x}</b><br>%{text}<extra></extra>"
    if hover is not None:
        tip_h = tip_v = "%{customdata}<extra></extra>"
    figure = go.Figure()
    if horizontal:
        figure.add_bar(x=values, y=names, orientation="h", marker_color=bar_colors, showlegend=False,
                       text=text, textposition="outside", cliponaxis=False,
                       customdata=hover, hovertemplate=tip_h)
    else:
        figure.add_bar(x=names, y=values, marker_color=bar_colors, showlegend=False,
                       text=text, textposition="outside", cliponaxis=False,
                       customdata=hover, hovertemplate=tip_v)

    if trend and len(values) >= 2:
        slope, intercept = np.polyfit(np.arange(len(values)), values, 1)
        fitted = list(np.maximum(slope * np.arange(len(values)) + intercept, 0))
        prefix = "" if value == "quantity" else "$"
        trend = dict(mode="lines", name="Trend", line=dict(color="#444444", width=2, dash="dash"),
                     hovertemplate="Trend: " + prefix + "%{y:,.0f}<extra></extra>")
        if horizontal:
            figure.add_scatter(x=fitted, y=names, **trend)
        else:
            figure.add_scatter(x=names, y=fitted, **trend)

    figure.update_layout(
        title=title, bargap=0.2, height=height or 420,
        xaxis_title=labels.get(category if not horizontal else value),
        yaxis_title=labels.get(value if not horizontal else category),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1.0),
    )
    if values:
        # Long labels ("$56,526 (10.7%)") need more room past the bar than short ones.
        room = 1.25 if max(len(label) for label in text) <= 8 else 1.55
        headroom = [0, max(values) * room]
        if horizontal:
            figure.update_xaxes(range=headroom)
        else:
            figure.update_yaxes(range=headroom)
    figure.update_traces(textfont_size=11, selector=dict(type="bar"))
    if not horizontal:
        figure.update_xaxes(type="category")
    return _figure_html(figure)


def _line_figure(data, x, y, title, labels, height=360, hover=None):
    """
    Builds one line chart (with a marker on each point) for values that run
    in time order, such as revenue by month: bars suit separate groups, a
    line suits a sequence. data is a DataFrame already in time order; x is
    the column of point names (months) and y the column of values.

    The line is smoothed into a curve (shape="spline"; smoothing runs from 0,
    straight segments, up to 1.3). The markers stay on the real values, so
    the curve is only a visual aid: between two points it can dip a little
    below or rise above them.

    Like _bar_figure, it passes hover (a list of strings, one per point) to
    the hover box and ends in _figure_html. The value axis starts at zero so
    a quiet month looks quiet, and the x names are treated as categories so
    Plotly keeps them in the order given instead of guessing they are dates.
    """
    figure = go.Figure()
    figure.add_scatter(
        x=list(data[x]), y=list(data[y]), mode="lines+markers", showlegend=False,
        line=dict(color=CHART_COLORS[0], width=3, shape="spline", smoothing=0.8), marker=dict(size=7),
        customdata=hover, hovertemplate="%{customdata}<extra></extra>",
    )
    figure.update_layout(
        title=title, height=height,
        xaxis_title=labels.get(x), yaxis_title=labels.get(y),
    )
    figure.update_xaxes(type="category")
    figure.update_yaxes(rangemode="tozero", tickprefix="$")
    return _figure_html(figure)


class Category(models.Model):
    """
    A product category. Defined before Product (the model that references
    it) so Product.category can use the bare class name instead of a
    forward-reference string - see the module docs for why order
    matters here.
    """
    category_id = models.SmallIntegerField(primary_key=True)
    category_name = models.CharField(max_length=15)
    description = models.TextField(blank=True, null=True)
    picture = models.BinaryField(blank=True, null=True)

    class Meta:
        """
        Meta configures the model/table itself, not a database column.
        managed=False: table already exists, Django shouldn't migrate it.
        db_table: the real table name, since it doesn't match Django's
        default ("djtraders_category").
        """
        managed = False
        db_table = 'categories'


class Customer(models.Model):
    """A DjangoTraders customer. No foreign keys, so no on_delete concerns."""
    customer_id = models.CharField(primary_key=True, max_length=5)
    company_name = models.CharField(max_length=40)
    contact_name = models.CharField(max_length=30, blank=True, null=True)
    contact_title = models.CharField(max_length=30, blank=True, null=True)
    address = models.CharField(max_length=60, blank=True, null=True)
    city = models.CharField(max_length=15, blank=True, null=True)
    region = models.CharField(max_length=15, blank=True, null=True)
    postal_code = models.CharField(max_length=10, blank=True, null=True)
    country = models.CharField(max_length=15, blank=True, null=True)
    phone = models.CharField(max_length=24, blank=True, null=True)
    fax = models.CharField(max_length=24, blank=True, null=True)
    password = models.CharField(db_column='Password', max_length=64, blank=True, null=True)  # Field name made lowercase.
    inactive_date = models.DateField(blank=True, null=True)

    @property
    def formatted_address(self):
        """
        This customer's address, city, region, postal_code, and country
        joined into one line (blank ones skipped), instead of five
        separate fields -- used by customer_detail.html.
        """
        parts = [self.address, self.city, self.region, self.postal_code, self.country]
        return ", ".join(part for part in parts if part)

    # region [WHY] charts built from a DataFrame
    # Each *_plot method below follows the same four steps: (1) pull
    # this customer's placed order lines out of the database as a
    # DataFrame (_order_lines_frame), (2) group and sum with pandas,
    # (3) hand the result to _bar_figure to draw a Plotly figure, (4) turn
    # that figure into an HTML <div> string a template can print with
    # |safe. Revenue is each line's unit_price * quantity * (1 - discount),
    # the same formula as OrderDetail.line_total -- not Product.unit_price,
    # which is today's list price and ignores both discounts and any
    # price change since the order was placed.
    # endregion
    def _order_lines_frame(self):
        """
        Every line on this customer's placed orders as a pandas DataFrame
        (see _lines_frame, above the models, for the columns).
        order_date__isnull=False leaves out an unplaced cart, the same
        "order_date is the placed flag" rule customer_detail uses.
        """
        return _lines_frame(OrderDetail.objects.filter(
            order__customer=self, order__order_date__isnull=False
        ))

    def order_years(self):
        """Distinct years this customer has placed orders in, newest first."""
        years = self.order_set.filter(order_date__isnull=False).dates("order_date", "year")
        return sorted((d.year for d in years), reverse=True)

    def annual_orders_plot(self):
        """Bar chart of this customer's total revenue for each year."""
        frame = self._order_lines_frame()
        if frame.empty:
            return None
        annual = frame.groupby("year", as_index=False)["revenue"].sum()
        annual["year"] = annual["year"].astype(str)
        return _bar_figure(
            annual, "year", "revenue", "Revenue by year",
            {"year": "Year", "revenue": "Revenue ($)"},
        )

    def orders_placed_plot(self, year):
        """
        Bar chart of this customer's revenue for each month of one year (the
        chart the dashboard's year dropdown loads), or None when that year
        has no placed orders. The view has already checked that year is one
        of order_years().

        Same four steps as annual_orders_plot, with one filter first and a
        different grouping. reindex(range(1, 13), fill_value=0) puts all
        twelve months on the chart: without it a month with no orders would
        be missing from the grouped result instead of showing as $0.
        """
        frame = self._order_lines_frame()
        frame = frame[frame["year"] == year]
        if frame.empty:
            return None
        monthly = (
            frame.groupby("month")["revenue"].sum()
            .reindex(range(1, 13), fill_value=0)
            .reset_index()
        )
        monthly["month"] = [calendar.month_abbr[m] for m in monthly["month"]]
        return _bar_figure(
            monthly, "month", "revenue", f"Revenue by month, {year}",
            {"month": "Month", "revenue": "Revenue ($)"},
        )

    def dashboard_stats(self):
        frame = self._order_lines_frame()

        if frame.empty:
            return None

        revenue = frame["revenue"].sum()
        orders = frame["order_id"].nunique()
        average_order = revenue / orders if orders else 0
        

        return {
            "orders": orders,
            "average_order": average_order,
            "last_order": frame["order_date"].max(),
        }

    @classmethod
    def search(cls, company_name="", contact_name="", contact_title="", city="", country=""):
        """
        Filters customers by any combination of company name, contact
        name, contact title, city, and country, returning every customer
        when none are given. Used by customer_list (djtraders/views.py)
        to back its search form.

        A @classmethod, not an instance method: it builds a fresh
        queryset from scratch (cls.objects...) rather than acting on an
        existing Customer, so it needs the class (cls) instead of self.

        company_name/contact_name use "icontains" (case-insensitive
        substring match) since they're free-text; contact_title/city/
        country use an exact match, since those values always come from
        a dropdown, not free text.
        """
        queryset = cls.objects.order_by("company_name")
        if company_name:
            queryset = queryset.filter(company_name__icontains=company_name)
        if contact_name:
            queryset = queryset.filter(contact_name__icontains=contact_name)
        if contact_title:
            queryset = queryset.filter(contact_title=contact_title)
        if city:
            queryset = queryset.filter(city=city)
        if country:
            queryset = queryset.filter(country=country)
        return queryset

    @classmethod
    def authenticate(cls, customer_id, password):
        """
        Looks up the customer by the ID entered in the login form and
        checks their password: a direct string compare against this
        customer's own password column (unlike Employee, which has no
        password column and uses a derived birth-year stand-in instead).
        Returns the matching Customer on success, None otherwise.
        """
        customer = cls.objects.filter(pk=customer_id).first()
        if customer is None:
            return None
        if customer.password != password:
            return None
        return customer

    @classmethod
    def generate_customer_id(cls, company_name):
        """
        Builds a new, unique 5-letter customer_id from a company name,
        matching Northwind's own existing style (e.g. "Alfreds
        Futterkiste" -> ALFKI). Called only from customer_create's POST
        handler (djtraders/views.py), after CustomerEditForm's own
        validation has already passed -- a customer never types or picks
        this value themselves, the same way Order.order_id comes from
        the database's auto-increment rather than from whoever places
        the order.

        Takes the company name's letters (spaces/punctuation/digits
        stripped, uppercased), first five, padding a short name with
        "X". customer_id's own primary-key uniqueness constraint is the
        real, final guarantee against a collision; the loop below just
        makes it likely a plausible ID is found on the first try, rather
        than a user ever seeing that constraint reject one.
        """
        letters = "".join(char for char in company_name.upper() if char.isalpha())
        base = (letters + "XXXXX")[:5]

        if not cls.objects.filter(pk=base).exists():
            return base

        # base alone is taken -- replace its trailing digits with a
        # counter (e.g. ALFK1, ALFK2, ... ALFK9, ALF10, ALF11, ...) until
        # an unused 5-character value turns up.
        suffix = 1
        while suffix < 100_000:
            digits = str(suffix)
            candidate = base[: 5 - len(digits)] + digits
            if not cls.objects.filter(pk=candidate).exists():
                return candidate
            suffix += 1

        # Practically unreachable for a class-sized dataset -- every
        # 5-character value derived from this base is already taken.
        raise ValueError(f"Could not generate a unique customer_id from {company_name!r}")

    class Meta:
        managed = False
        db_table = 'customers'


class Employee(models.Model):
    """A DjangoTraders employee. Has a self-referencing FK for its manager (reports_to)."""
    employee_id = models.SmallIntegerField(primary_key=True)
    last_name = models.CharField(max_length=20)
    first_name = models.CharField(max_length=10)
    title = models.CharField(max_length=30, blank=True, null=True)
    title_of_courtesy = models.CharField(max_length=25, blank=True, null=True)
    birth_date = models.DateField(blank=True, null=True)
    hire_date = models.DateField(blank=True, null=True)
    address = models.CharField(max_length=60, blank=True, null=True)
    city = models.CharField(max_length=15, blank=True, null=True)
    region = models.CharField(max_length=15, blank=True, null=True)
    postal_code = models.CharField(max_length=10, blank=True, null=True)
    country = models.CharField(max_length=15, blank=True, null=True)
    home_phone = models.CharField(max_length=24, blank=True, null=True)
    extension = models.CharField(max_length=4, blank=True, null=True)
    photo = models.BinaryField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)
    photo_path = models.CharField(max_length=255, blank=True, null=True)
    # region [CONCEPT] self-referencing FK (reports_to)
    # FK to Employee itself, for the manager hierarchy: gives us
    # employee.reports_to.first_name (up to the manager) and
    # employee.employee_set.all() (down to their reports).
    # SET_NULL so deleting a manager just clears the link, not their reports.
    # endregion
    reports_to = models.ForeignKey('self', models.SET_NULL, db_column='reports_to', blank=True, null=True)

    @property
    def formatted_address(self):
        """
        This employee's address, city, region, postal_code, and country
        joined into one line (blanks skipped), same pattern as
        Customer.formatted_address -- used by employee_detail.html.
        """
        parts = [self.address, self.city, self.region, self.postal_code, self.country]
        return ", ".join(part for part in parts if part)

    @property
    def is_manager(self):
        """
        True when at least one employee reports to this one. A manager
        may open any employee's page and sees the Employees tab; everyone
        else only sees their own. employee_set is the reverse side of the
        reports_to foreign key above (every employee whose manager is
        this one).
        """
        return self.employee_set.exists()

    def _order_lines_frame(self):
        """
        Every line on the placed orders this employee handled
        (Order.employee), as a pandas DataFrame -- see _lines_frame,
        above the models, for the columns. The same pattern as
        Customer._order_lines_frame; only the filter is different.
        """
        return _lines_frame(OrderDetail.objects.filter(
            order__employee=self, order__order_date__isnull=False
        ))

    def annual_orders_plot(self):
        """Bar chart of the revenue on this employee's orders, by year."""
        frame = self._order_lines_frame()
        if frame.empty:
            return None
        annual = frame.groupby("year", as_index=False)["revenue"].sum()
        annual["year"] = annual["year"].astype(str)
        return _bar_figure(
            annual, "year", "revenue", "Revenue by year",
            {"year": "Year", "revenue": "Revenue ($)"}, height=360,
        )

    def revenue_years(self):
        """The years in which this employee handled placed orders, oldest first (for the year dropdown)."""
        frame = self._order_lines_frame()
        if frame.empty:
            return []
        return sorted(int(year) for year in frame["year"].unique())

    def revenue_over_time(self, level="year", year=None, height=360):
        """
        The dashboard's revenue-over-time chart, as chart HTML (None when this
        employee has no orders). Each bar's hover shows the period, its revenue
        and its number of orders.

        level "year": one bar per year (year is ignored).
        level "month" with a year: the twelve months of that year, as a line chart.
        level "month" with year=None: every month from the first order to the last,
        across all years, as a line chart, so it reads as revenue over time.

        Orders are distinct orders. Months with no orders are filled in with zero
        (reindex over a full period range), so a quiet month shows as an empty
        slot instead of vanishing.
        """
        frame = self._order_lines_frame()
        if frame.empty:
            return None
        if level == "year":
            grouped = frame.groupby("year").agg(revenue=("revenue", "sum"), orders=("order_id", "nunique"))
            table = grouped.reset_index()
            table["label"] = table["year"].astype(str)
            table["full_label"] = table["label"]
            title, axis = "Revenue by year", "Year"
        else:
            if year is not None:
                frame = frame[frame["year"] == year]
            frame = frame.assign(period=frame["order_date"].dt.to_period("M"))
            grouped = frame.groupby("period").agg(revenue=("revenue", "sum"), orders=("order_id", "nunique"))
            if year is None:
                full_range = pd.period_range(grouped.index.min(), grouped.index.max(), freq="M")
                title = "Revenue by month, all years"
            else:
                full_range = pd.period_range(f"{year}-01", f"{year}-12", freq="M")
                title = f"Revenue by month, {year}"
            grouped = grouped.reindex(full_range, fill_value=0)
            table = grouped.reset_index(names="period")
            table["label"] = table["period"].dt.strftime("%b" if year is not None else "%b %Y")
            table["full_label"] = table["period"].dt.strftime("%B %Y")
            axis = "Month"
        hover = [
            f"<b>{row.full_label}</b><br>Revenue: ${row.revenue:,.0f}<br>Orders: {row.orders:,}"
            for row in table.itertuples()
        ]
        labels = {"label": axis, "revenue": "Revenue ($)"}
        if level == "year":
            return _bar_figure(table, "label", "revenue", title, labels, height=height, hover=hover)
        # Months run in time order, so a line reads better than bars.
        return _line_figure(table, "label", "revenue", title, labels, height=height, hover=hover)

    def period_detail(self, key):
        """
        What the Details modal shows for one period of this employee's orders: key
        is "1997" (a year) or "1997-03" (a month). Returns a dict with label,
        revenue, orders and products (the five products with the most revenue in
        that period, each with units and revenue). For a whole year it also returns
        months_plot, that year's revenue by month; for a single month it is None.
        The view has already checked
        that key is a real period, so it is only split here.
        """
        year, _, month = key.partition("-")
        frame = self._order_lines_frame()
        in_period = frame["year"] == int(year)
        label = year
        if month:
            in_period &= frame["month"] == int(month)
            label = pd.Timestamp(year=int(year), month=int(month), day=1).strftime("%B %Y")
        part = frame[in_period]
        products = (
            part.groupby("product_name", as_index=False)
            .agg(units=("quantity", "sum"), revenue=("revenue", "sum"))
            .sort_values("revenue", ascending=False).head(5)
        )
        months_plot = None
        if not month:
            months_plot = self.revenue_over_time("month", int(year), height=300)
        return {
            "label": label,
            "revenue": part["revenue"].sum(),
            "orders": part["order_id"].nunique(),
            "products": products.to_dict("records"),
            "months_plot": months_plot,
        }

    @classmethod
    def _performance_frame(cls):
        """
        One row per employee who handled at least one placed order:
        revenue, orders (distinct orders), customers (distinct customers),
        average_order, revenue_per_customer, share (percent of all company
        revenue), and a rank for each measure (revenue_rank, orders_rank,
        average_order_rank, customers_rank, revenue_per_customer_rank;
        1 = best, ties share a rank). The database does the grouping with
        values()/annotate(); pandas adds the derived columns. Sorted by
        revenue_rank. The base for performance(), team_comparison() and
        leaderboard().
        """
        rows = (
            OrderDetail.objects.filter(order__order_date__isnull=False)
            .values(employee_key=F("order__employee_id"))
            .annotate(
                revenue=Sum(Supplier._line_revenue()),
                orders=Count("order", distinct=True),
                customers=Count("order__customer", distinct=True),
            )
        )
        frame = pd.DataFrame(list(rows)).dropna(subset=["employee_key"]) if rows else pd.DataFrame()
        if frame.empty:
            return frame
        frame["employee_key"] = frame["employee_key"].astype(int)
        frame["average_order"] = frame["revenue"] / frame["orders"]
        frame["revenue_per_customer"] = frame["revenue"] / frame["customers"].where(frame["customers"] > 0)
        frame["share"] = frame["revenue"] / frame["revenue"].sum() * 100
        for measure in ("revenue", "orders", "average_order", "customers", "revenue_per_customer"):
            frame[f"{measure}_rank"] = frame[measure].rank(ascending=False, method="min")
        return frame.sort_values("revenue_rank")

    def performance(self):
        """
        This employee compared with the other employees, for the
        dashboard's summary tiles: a dict with their revenue, orders,
        average_order, share of company revenue, revenue_rank and
        orders_rank, employee_count (how many employees have orders),
        colleagues_behind, team_share (an even split, 100 / employee_count),
        team_average_order (the mean of the employees' average orders, the same
        figure the "vs. the team" table shows) and
        average_order_diff (percent above or below that team figure).
        Returns None when this employee has no placed orders.
        """
        frame = self._performance_frame()
        if frame.empty:
            return None
        mine = frame[frame["employee_key"] == self.employee_id]
        if mine.empty:
            return None
        row = mine.iloc[0]
        count = len(frame)
        team_average_order = frame["average_order"].mean()
        return {
            "revenue": row["revenue"],
            "orders": int(row["orders"]),
            "average_order": row["average_order"],
            "share": row["share"],
            "revenue_rank": int(row["revenue_rank"]),
            "orders_rank": int(row["orders_rank"]),
            "employee_count": count,
            "colleagues_behind": count - int(row["revenue_rank"]),
            "team_share": 100 / count,
            "team_average_order": team_average_order,
            "average_order_diff": (row["average_order"] / team_average_order - 1) * 100,
        }

    def team_comparison(self):
        """
        This employee against the team on five measures, as a list of
        dicts for the dashboard's "vs. the team" table and chart: label,
        kind ("money" or "count", for formatting), you, team_average
        (the mean across employees), best (the highest employee, nameless),
        rank, employee_count, and you_index / best_index (each as a
        percent of the team average, so the team average is always 100).
        The index puts dollars, orders and customers on one scale, which
        is what lets a single chart show all five. Returns [] when this
        employee has no placed orders.
        """
        frame = self._performance_frame()
        mine = frame[frame["employee_key"] == self.employee_id] if not frame.empty else frame
        if mine.empty:
            return []
        row = mine.iloc[0]
        measures = [
            ("Revenue", "revenue", "money"),
            ("Orders", "orders", "count"),
            ("Average order", "average_order", "money"),
            ("Customers served", "customers", "count"),
            ("Revenue per customer", "revenue_per_customer", "money"),
        ]
        comparison = []
        for label, column, kind in measures:
            team_average = frame[column].mean()
            comparison.append({
                "label": label,
                "kind": kind,
                "you": row[column],
                "team_average": team_average,
                "best": frame[column].max(),
                "rank": int(row[f"{column}_rank"]),
                "employee_count": len(frame),
                "you_index": row[column] / team_average * 100,
                "best_index": frame[column].max() / team_average * 100,
            })
        return comparison

    def team_comparison_plot(self, you_label="You"):
        """
        Grouped bar chart of team_comparison(): for each measure, three
        bars -- this employee, the team average (always 100%) and the
        best employee -- all as a percent of the team average. The best
        bar is nameless. Hovering a bar shows the real figure behind the
        percentage. Returns None when there is nothing to compare.
        """
        comparison = self.team_comparison()
        if not comparison:
            return None

        def show(row, key):
            return f"${row[key]:,.0f}" if row["kind"] == "money" else f"{row[key]:,.0f}"

        measures = [row["label"].replace(" ", "<br>", 1) if len(row["label"]) > 8 else row["label"] for row in comparison]
        series = [
            (you_label, [r["you_index"] for r in comparison], [show(r, "you") for r in comparison], CHART_COLORS[0]),
            ("Team average", [100] * len(comparison), [show(r, "team_average") for r in comparison], "#5f6b76"),
            ("Best", [r["best_index"] for r in comparison], [show(r, "best") for r in comparison], CHART_COLORS[2]),
        ]
        figure = go.Figure()
        for name, indexes, actuals, color in series:
            figure.add_bar(
                x=measures, y=indexes, name=name, marker_color=color, customdata=actuals,
                text=[f"{v:.0f}%" if name != "Team average" else "" for v in indexes],
                textposition="outside", cliponaxis=False, textfont_size=11,
                hovertemplate="%{x}<br>" + name + ": %{customdata} (%{y:.0f}% of team average)<extra></extra>",
            )
        figure.update_layout(
            title="Compared with the team (team average = 100%)", barmode="group", bargap=0.25,
            yaxis_title="Percent of team average", height=340,
            legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1.0),
        )
        figure.update_yaxes(range=[0, max(r["best_index"] for r in comparison) * 1.25])
        return _figure_html(figure)

    def leaderboard(self):
        """
        Every employee ranked by revenue, as a list of dicts for the
        manager-only leaderboard table: rank, name, orders, revenue,
        average_order, share, is_self (True on this page's employee).
        Names and dollars for every employee, so the view only calls
        this for a manager; everyone else gets team_comparison(), which
        shows averages and a nameless best instead of other people.
        """
        frame = self._performance_frame()
        if frame.empty:
            return []
        names = {e.employee_id: f"{e.first_name} {e.last_name}" for e in Employee.objects.all()}
        return [
            {
                "rank": int(row.revenue_rank),
                "name": names.get(row.employee_key, "Unknown"),
                "orders": row.orders,
                "revenue": row.revenue,
                "average_order": row.average_order,
                "share": row.share,
                "is_self": row.employee_key == self.employee_id,
            }
            for row in frame.itertuples()
        ]

    def customer_revenue_plot(self, top=10):
        """
        Horizontal bar chart: revenue on this employee's orders by
        customer, largest at the top. top=10 keeps the ten biggest
        customers; top=None charts every customer. Each bar is labeled
        with its dollars and the percentage of this employee's total
        revenue (all customers, not just the ones charted) that the
        customer generated.
        """
        frame = self._order_lines_frame()
        if frame.empty:
            return None
        by_customer = (
            frame.groupby("customer_name", as_index=False)["revenue"].sum()
            .sort_values("revenue")
        )
        total = by_customer["revenue"].sum()
        if top:
            by_customer = by_customer.tail(top)
        text = [f"${row.revenue:,.0f} ({row.revenue / total * 100:.1f}%)" for row in by_customer.itertuples()]
        # Same sizing rule as revenue_breakdown_plot, so the two charts sharing a dashboard row match.
        per_bar = 32 if len(by_customer) <= 12 else 24
        return _bar_figure(
            by_customer, "customer_name", "revenue",
            f"Top {top} customers by revenue" if top else "Revenue by customer",
            {"customer_name": "Customer", "revenue": "Revenue ($)"},
            color_names=frame["customer_name"], horizontal=True,
            height=max(420, per_bar * len(by_customer) + 100), trend=False, text=text,
        )

    # What the dashboard's "Revenue by" dropdown can group by: the key, the
    # singular word used in chart titles, and the OrderDetail field to group on.
    BREAKDOWNS = {
        "supplier": ("supplier", "product__supplier__company_name"),
        "product": ("product", "product__product_name"),
        "category": ("category", "product__category__category_name"),
    }

    def revenue_breakdown_plot(self, by="supplier", all_orders=False, top=None):
        """
        Horizontal bar chart of revenue by supplier, product or category
        (by = "supplier", "product" or "category"), largest at the top.
        What it shows depends on who is looking (the view passes
        all_orders=viewer.is_manager):

        all_orders=True (a manager): each group's revenue across every
        placed order, whoever handled it. Each bar is labeled with its
        dollars and its percentage of all revenue.

        all_orders=False (any other employee): for each group, the share
        of that group's total revenue that came from this employee's own
        orders, as a percentage. Only the percentage is charted and
        labeled, never the group's total, so a regular employee can see
        how much of each supplier, product or category they brought in
        without seeing what it earns overall.

        top limits the chart to the largest N bars (5, 10); None shows
        every group. The bar colors are assigned from the full list of
        groups, so a group keeps its color whichever top is chosen.

        Each version groups OrderDetail rows with values()/annotate(),
        then passes the result through a DataFrame to _bar_figure, like
        the other charts.
        """
        word, field = self.BREAKDOWNS[by]
        placed = OrderDetail.objects.filter(order__order_date__isnull=False)
        revenue = Sum(Supplier._line_revenue())

        def revenue_by_group(lines):
            rows = lines.values(group_name=F(field)).annotate(revenue=revenue)
            frame = pd.DataFrame(list(rows))
            if frame.empty:
                return frame
            frame["group_name"] = frame["group_name"].fillna(f"Unknown {word}")
            return frame.groupby("group_name", as_index=False)["revenue"].sum()

        totals = revenue_by_group(placed)
        if totals.empty:
            return None

        if all_orders:
            chart_data = totals.copy()
            chart_data["percent"] = chart_data["revenue"] / chart_data["revenue"].sum() * 100
            chart_data = chart_data.sort_values("revenue", ascending=False)
            value, title = "revenue", f"Revenue by {word} (all orders)"
            labels = {"group_name": word.capitalize(), "revenue": "Revenue ($)"}
        else:
            mine = revenue_by_group(placed.filter(order__employee=self))
            chart_data = totals.merge(mine, on="group_name", how="left", suffixes=("_all", "_mine"))
            chart_data["revenue_mine"] = chart_data["revenue_mine"].fillna(0)
            chart_data = chart_data[chart_data["revenue_all"] > 0]
            chart_data["share"] = chart_data["revenue_mine"] / chart_data["revenue_all"] * 100
            chart_data["percent"] = chart_data["share"]
            chart_data = chart_data.sort_values("share", ascending=False)
            value, title = "share", f"Your share of each {word}'s revenue (%)"
            labels = {"group_name": word.capitalize(), "share": f"Share of {word} revenue (%)"}

        if top:
            chart_data = chart_data.head(top)
            title = f"{title} -- top {top}"
        # Plotly draws the first horizontal bar at the bottom; flip so the largest is on top.
        chart_data = chart_data.iloc[::-1]

        if all_orders:
            text = [f"${row.revenue:,.0f} ({row.percent:.1f}%)" for row in chart_data.itertuples()]
        else:
            text = [f"{row.percent:.1f}%" for row in chart_data.itertuples()]

        per_bar = 32 if len(chart_data) <= 12 else 24
        return _bar_figure(
            chart_data, "group_name", value, title, labels,
            color_names=totals["group_name"], horizontal=True,
            height=max(420, per_bar * len(chart_data) + 100), trend=False, text=text,
        )

    @classmethod
    def authenticate(cls, employee_id, password):
        """
        Looks up the employee picked in the login form and checks their
        password: the 4-digit year of their own birth_date, as a string
        (e.g. birth_date of 1985-03-12 -> password "1985"). Returns the
        matching Employee on success, or None if the employee_id doesn't
        exist, has no birth_date on record, or the password is wrong.
        """
        employee = cls.objects.filter(pk=employee_id).first()
        if employee is None or employee.birth_date is None:
            return None
        if str(employee.birth_date.year) != password:
            return None
        return employee

    class Meta:
        managed = False
        db_table = 'employees'


class OrderDetail(models.Model):
    """
    A single line item on an order (composite primary key: order_id + product_id).
    """
    # region [WARNING] order+product form the composite PK, not a separate id column
    # order and product below are ordinary FKs, but they're ALSO the two
    # columns making up this table's primary key (CompositePrimaryKey, not
    # a separate id column) - a product can only appear once per order.
    # endregion
    pk = models.CompositePrimaryKey('order_id', 'product_id')

    # FK to Order (order_detail.order.order_date, order.orderdetail_set.all()).
    # CASCADE: a line item is meaningless without its order.
    order = models.ForeignKey('Order', models.CASCADE)

    # FK to Product (order_detail.product.product_name, product.orderdetail_set.all()).
    # PROTECT: refuse to delete a product still on a historical order line.
    product = models.ForeignKey('Product', models.PROTECT)
    unit_price = models.FloatField()
    quantity = models.SmallIntegerField()
    discount = models.FloatField()

    @property
    def line_total(self):
        """
        This line's own revenue: unit_price times quantity, minus the
        discount fraction. A @property, not a field, since it's derived
        from the three fields above rather than stored -- Order.order_total
        sums this same property across every line instead of repeating
        the formula.
        """
        return self.unit_price * self.quantity * (1 - self.discount)

    class Meta:
        managed = False
        db_table = 'order_details'


class Order(models.Model):
    """
    A customer order. The customer/employee/shipper links are all nullable, so
    on_delete=SET_NULL keeps the order history intact even if one of those
    related records is later removed.
    """
    # region [WHY] AutoField only for order_id
    # SmallAutoField, unlike this app's other primary keys: order_id's
    # database column is backed by a real auto-incrementing sequence, so
    # the other models' IDs (category_id, etc.) aren't - they're fixed
    # reference IDs the database won't generate for you.
    # endregion
    order_id = models.SmallAutoField(primary_key=True)
    order_date = models.DateField(blank=True, null=True)
    required_date = models.DateField(blank=True, null=True)
    shipped_date = models.DateField(blank=True, null=True)
    freight = models.FloatField(blank=True, null=True)
    ship_name = models.CharField(max_length=40, blank=True, null=True)
    ship_address = models.CharField(max_length=60, blank=True, null=True)
    ship_city = models.CharField(max_length=15, blank=True, null=True)
    ship_region = models.CharField(max_length=15, blank=True, null=True)
    ship_postal_code = models.CharField(max_length=10, blank=True, null=True)
    ship_country = models.CharField(max_length=15, blank=True, null=True)

    # FK to Customer (order.customer.company_name, customer.order_set.all()).
    customer = models.ForeignKey(Customer, models.SET_NULL, blank=True, null=True)

    # FK to Employee (order.employee.last_name, employee.order_set.all()).
    employee = models.ForeignKey(Employee, models.SET_NULL, blank=True, null=True)

    # FK to Shipper, stored in a column named ship_via (db_column below) --
    # that's the existing table's column name, not shipper_id.
    ship_via = models.ForeignKey('Shipper', models.SET_NULL, db_column='ship_via', blank=True, null=True)

    @property
    def order_total(self):
        """
        This order's total revenue -- every line item's own line_total
        (OrderDetail.line_total) added together, not recomputed here.
        order.customer is already a real field (the FK above), not a
        property -- it needs no extra code to access.
        """
        return sum(line.line_total for line in self.orderdetail_set.all())

    @property
    def formatted_ship_address(self):
        """
        This order's ship_address, ship_city, ship_region,
        ship_postal_code, and ship_country joined into one line (blanks
        skipped), instead of four separate fields -- used by
        order_detail.html, same pattern as Customer.formatted_address.
        """
        parts = [self.ship_address, self.ship_city, self.ship_region, self.ship_postal_code, self.ship_country]
        return ", ".join(part for part in parts if part)

    class Meta:
        managed = False
        db_table = 'orders'


class Product(models.Model):
    """
    A DjangoTraders product. Supplier and category are both nullable, so removing
    either one just clears the link (SET_NULL) instead of touching the product.
    """
    product_id = models.SmallIntegerField(primary_key=True)
    product_name = models.CharField(max_length=40)
    quantity_per_unit = models.CharField(max_length=20, blank=True, null=True)
    unit_price = models.FloatField(blank=True, null=True)
    units_in_stock = models.SmallIntegerField(blank=True, null=True)
    units_on_order = models.SmallIntegerField(blank=True, null=True)
    reorder_level = models.SmallIntegerField(blank=True, null=True)
    discontinued = models.IntegerField()
    date_discontinued = models.DateField(blank=True, null=True)
    
    # FK to Supplier (product.supplier.company_name, supplier.product_set.all()).
    supplier = models.ForeignKey('Supplier', models.SET_NULL, blank=True, null=True)

    # FK to Category (product.category.category_name, category.product_set.all()).
    category = models.ForeignKey(Category, models.SET_NULL, blank=True, null=True)

    @property
    def is_discontinued(self):
        """
        discontinued is a plain 1/0 IntegerField, not a BooleanField -- this
        maps it to a real bool so callers can write product.is_discontinued
        instead of comparing product.discontinued to 1 by hand. A @property,
        not a field, so it's computed fresh each access, no migration needed.
        """
        return bool(self.discontinued)

    @classmethod
    def search(cls, product_name="", category_id="", show_all=False):
        """
        Filters products by an optional product name and/or category,
        returning every non-discontinued product by default. Used by
        product_list (djtraders/views.py) to back its search form.

        product_name uses "icontains" (a case-insensitive substring
        match), same reasoning as Customer.search's company_name.
        category_id uses an exact match, since its value comes from a
        dropdown of categories already on record, not free text.
        show_all=False filters out discontinued products (discontinued
        is a plain 1/0 field, not is_discontinued -- that's a Python
        property, not something the database can filter on); show_all=
        True skips that filter, showing discontinued products too.
        """
        queryset = cls.objects.order_by("product_name")
        if product_name:
            queryset = queryset.filter(product_name__icontains=product_name)

        if category_id:
            queryset = queryset.filter(category_id=category_id)

        if not show_all:
            queryset = queryset.filter(discontinued=0)

        return queryset

    @property
    def total_revenue(self):
        """
        Total revenue this product has generated -- every order line it
        appears on, each one's own line_total (OrderDetail.line_total)
        added together. product.orderdetail_set is the reverse side of
        OrderDetail.product's FK (every OrderDetail row for this product).
        """
        return sum(line.line_total for line in self.orderdetail_set.all())

    @property
    def units_sold(self):
        """
        Total quantity of this product sold -- every order line's
        quantity added together, across every order it's appeared on.
        """
        return sum(line.quantity for line in self.orderdetail_set.all())

    @property
    def first_sold(self):
        """Date of the earliest placed order that includes this product (None if never sold)."""
        line = (self.orderdetail_set.filter(order__order_date__isnull=False)
                .order_by("order__order_date").first())
        return line.order.order_date if line else None

    @property
    def last_sold(self):
        """Date of the most recent placed order that includes this product (None if never sold)."""
        line = (self.orderdetail_set.filter(order__order_date__isnull=False)
                .order_by("-order__order_date").first())
        return line.order.order_date if line else None

    class Meta:
        managed = False
        db_table = 'products'


class Shipper(models.Model):
    """A shipping carrier. No foreign keys."""
    shipper_id = models.SmallIntegerField(primary_key=True)
    company_name = models.CharField(max_length=40)
    phone = models.CharField(max_length=24, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'shippers'


class Supplier(models.Model):
    """A product supplier. No foreign keys."""
    supplier_id = models.SmallIntegerField(primary_key=True)
    company_name = models.CharField(max_length=40)
    contact_name = models.CharField(max_length=30, blank=True, null=True)
    contact_title = models.CharField(max_length=30, blank=True, null=True)
    address = models.CharField(max_length=60, blank=True, null=True)
    city = models.CharField(max_length=15, blank=True, null=True)
    region = models.CharField(max_length=15, blank=True, null=True)
    postal_code = models.CharField(max_length=10, blank=True, null=True)
    country = models.CharField(max_length=15, blank=True, null=True)
    phone = models.CharField(max_length=24, blank=True, null=True)
    fax = models.CharField(max_length=24, blank=True, null=True)
    homepage = models.TextField(blank=True, null=True)

    # region [WHY] a fixed shared password for suppliers
    # The suppliers table has no password column, and this app's tables
    # are unmanaged (Django will not alter them), so there is nowhere to
    # store one per supplier. Every supplier logs in with this one shared
    # value -- the same demo password the customers use -- picked from a
    # dropdown, exactly like the customer login. A real app would store a
    # hashed password per supplier; next year's version of the database
    # adds that column.
    # endregion
    SHARED_PASSWORD = "pass"

    @classmethod
    def authenticate(cls, supplier_id, password):
        """
        Looks up the supplier picked in the login dropdown and checks the
        shared password. Returns the matching Supplier on success, None
        otherwise (an unknown or non-numeric supplier_id counts as a
        failure, not a crash).
        """
        try:
            supplier = cls.objects.filter(pk=int(supplier_id)).first()
        except (TypeError, ValueError):
            return None
        if supplier is None or password != cls.SHARED_PASSWORD:
            return None
        return supplier

    @property
    def formatted_address(self):
        """Address, city, region, postal_code, and country joined into one line (blank ones skipped)."""
        parts = [self.address, self.city, self.region, self.postal_code, self.country]
        return ", ".join(part for part in parts if part)

    def _placed_lines(self):
        """
        Every order line, on a placed order, for one of this supplier's
        products. product__supplier=self follows OrderDetail -> Product
        -> Supplier in one query; order_date__isnull=False leaves out an
        unplaced cart, the same "placed" rule as everywhere else.
        """
        return OrderDetail.objects.filter(
            product__supplier=self, order__order_date__isnull=False
        )

    @staticmethod
    def _line_revenue():
        """The database-side version of OrderDetail.line_total, for Sum(): unit_price * quantity * (1 - discount)."""
        return ExpressionWrapper(
            F("unit_price") * F("quantity") * (1 - F("discount")),
            output_field=FloatField(),
        )

    def summary(self):
        """Headline numbers for the Info tab: products, units sold, revenue, orders (revenue and units from placed orders only)."""
        totals = self._placed_lines().aggregate(
            units=Sum("quantity"),
            revenue=Sum(self._line_revenue()),
            orders=Count("order_id", distinct=True),
        )
        return {
            "product_count": self.product_set.count(),
            "units": totals["units"] or 0,
            "revenue": totals["revenue"] or 0,
            "orders": totals["orders"],
        }

    def order_history(self):
        """
        One row per placed order that includes at least one of this
        supplier's products, newest first: order_id, order_date, the
        customer's company name, how many of this supplier's products
        were on the order, and the units and revenue for those lines
        only -- never the rest of the order, which belongs to other
        suppliers too. values() picks the columns to group by and
        annotate() adds the per-group totals.
        """
        return (
            self._placed_lines()
            .values("order_id", "order__order_date", "order__customer__company_name")
            .annotate(
                products=Count("product_id", distinct=True),
                units=Sum("quantity"),
                revenue=Sum(self._line_revenue()),
            )
            .order_by("-order__order_date", "-order_id")
        )

    def product_revenue(self):
        """
        One row per product this supplier provides (including products
        with no sales yet, shown as zeros), largest revenue first:
        product_id, product_name, category_name, units, revenue, orders.
        """
        sales = {
            row["product_id"]: row
            for row in self._placed_lines()
            .values("product_id")
            .annotate(
                units=Sum("quantity"),
                revenue=Sum(self._line_revenue()),
                orders=Count("order_id", distinct=True),
            )
        }
        rows = []
        for product in self.product_set.select_related("category"):
            sold = sales.get(product.product_id, {})
            rows.append({
                "product_id": product.product_id,
                "product_name": product.product_name,
                "category_name": product.category.category_name if product.category else "—",
                "units": sold.get("units", 0),
                "revenue": sold.get("revenue", 0),
                "orders": sold.get("orders", 0),
            })
        return sorted(rows, key=lambda row: row["revenue"], reverse=True)


    class Meta:
        managed = False
        db_table = 'suppliers'